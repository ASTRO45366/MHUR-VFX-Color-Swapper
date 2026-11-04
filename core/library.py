"""Default-asset library: import, catalogue and group MHUR effect assets."""
import os
import json
import lzma
import re
import shutil
import struct
import zipfile
from collections import defaultdict, OrderedDict
from pathlib import Path

from . import pak as pakmod
from .recolor import INDICATOR_RE, find_fields
from .uasset import Asset

PKG_RE = re.compile(r'^/Game/Character/(Ch\d+)(?:/Variation/(Var\d+))?/(.*)$')
KEEP_PREFIX = ('PS_', 'MI_', 'M_', 'MII_')

GROUPS = [
    ('basic', 'Basic Attack', 'Normal combo and finishing attack effects'),
    ('alpha', 'Alpha', 'Skill 1'),
    ('beta', 'Beta', 'Skill 2'),
    ('gamma', 'Gamma', 'Skill 3'),
    ('special', 'Special', 'Special / ultimate move'),
    ('other', 'Other', 'Movement, weapons, emotes and misc'),
]
GROUP_LABEL = {k: v for k, v, _ in GROUPS}
GROUP_DESC = {k: d for k, _, d in GROUPS}


def classify(name):
    n = re.sub(r'^PS_Ch\d+(V\d+)?_?', '', name)
    low = n.lower()
    m = re.search(r'skill0?([123])', low)
    if m:
        return {'1': 'alpha', '2': 'beta', '3': 'gamma'}[m.group(1)]
    toks = [t for t in re.split(r'[_\W]+|(?<=[a-z])(?=[A-Z])', n) if t]
    tl = [t.lower() for t in toks]
    if 'sp' in tl or 'special' in low or low.startswith('sp') and not low.startswith('spl'):
        return 'special'
    if 'attack' in low or 'kill' in low:
        return 'basic'
    return 'other'


class Rec:
    __slots__ = ('pkg', 'ua', 'ux', 'kind', 'char', 'var', 'name', 'group', 'refs',
                 'fields', 'indicator', 'groups', 'ind_only', 'ent', 'nfields')

    def __init__(self):
        self.refs = set()
        self.fields = []
        self.groups = set()
        self.group = None
        self.indicator = False
        self.ind_only = False
        self.ent = None
        self.nfields = 0


class Library:
    def __init__(self, root, archive_path=None):
        self.root = Path(root)
        self.archive_path = Path(archive_path) if archive_path else self.root.parent / 'library.zip'
        self._blocks = OrderedDict()
        self._members = {}
        self.recs = {}          # pkg -> Rec
        self.update_archive = None
        self._update_reader = None
        self.scanned = False
        self.progress = (0, 1)

    # ------------------------------------------------------------- import
    def _place(self, uasset_bytes, uexp_bytes, stem):
        a = Asset(uasset_bytes, uexp_bytes)
        pkg = next((n for n in a.names if n.startswith('/Game/Character/')
                    and n.rsplit('/', 1)[-1] == stem), None)
        if not pkg or not PKG_RE.match(pkg):
            return None
        base = self.root / pkg.replace('/Game/', '', 1).lstrip('/')
        if not base.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Asset package points outside the library')
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix('.uasset').write_bytes(uasset_bytes)
        base.with_suffix('.uexp').write_bytes(uexp_bytes)
        return pkg

    def import_path(self, path, log=print):
        """Stream supported asset pairs instead of loading entire FModel dumps."""
        path = Path(path)
        count = 0
        def place(name, ua, ux):
            nonlocal count
            stem = Path(name).stem
            try:
                if stem.startswith(KEEP_PREFIX) and self._place(ua, ux, stem):
                    count += 1
            except Exception as exc:
                log(f'skip {name}: {exc}')
        if path.is_dir():
            for f in path.rglob('*.uasset'):
                x = f.with_suffix('.uexp')
                if f.stem.startswith(KEEP_PREFIX) and x.is_file():
                    place(f.name, f.read_bytes(), x.read_bytes())
        elif path.suffix.lower() == '.zip':
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                for n in sorted(names):
                    if (n.endswith('.uasset') and Path(n).stem.startswith(KEEP_PREFIX)
                            and n[:-7] + '.uexp' in names):
                        place(n, archive.read(n), archive.read(n[:-7] + '.uexp'))
        elif path.suffix.lower() == '.pak':
            _, files = pakmod.read_pak(path)
            for n, data in files.items():
                if (n.endswith('.uasset') and Path(n).stem.startswith(KEEP_PREFIX)
                        and n[:-7] + '.uexp' in files):
                    place(n, data, files[n[:-7] + '.uexp'])
        else:
            raise ValueError('Unsupported file type (use .zip, .pak or a folder)')
        return count

    @staticmethod
    def record_data(r):
        return {k: sorted(getattr(r, k)) if k == 'refs' else getattr(r, k)
                for k in ('pkg', 'kind', 'char', 'var', 'name', 'group',
                          'refs', 'indicator', 'nfields')}

    @staticmethod
    def from_data(data, ua, ux):
        r = Rec()
        for key, value in data.items():
            if key in ('pkg', 'kind', 'char', 'var', 'name', 'group',
                       'refs', 'indicator', 'nfields'):
                setattr(r, key, set(value) if key == 'refs' else value)
        r.ua, r.ux = ua, ux
        return r

    # ------------------------------------------------------------- scan
    def scan(self, progress=None):
        self.recs.clear()
        if self._update_reader and getattr(self._update_reader, 'archive', None):
            self._update_reader.archive.close()
        self._update_reader = None
        if getattr(self, 'archive', None):
            self.archive.close()
        self.archive = None
        self._blocks.clear()
        self._members = {}
        archive_path = self.archive_path
        if archive_path.is_file():
            self.archive = zipfile.ZipFile(archive_path)
            catalog = json.loads(self.archive.read('catalog.json'))
            if isinstance(catalog, dict):
                if catalog.get('format') != 2:
                    raise ValueError('Unsupported bundled library format')
                self._members = catalog['members']
                catalog = catalog['records']
            for data in catalog:
                rel = data['pkg'].replace('/Game/', '', 1)
                r = self.from_data(data, rel + '.uasset', rel + '.uexp')
                self.recs[r.pkg] = r
        if self.update_archive and Path(self.update_archive).is_file():
            reader = Library(self.root.parent / '_no_loose_updates', self.update_archive)
            reader.scan()
            for r in reader.recs.values():
                r.ua, r.ux = ('update', r.ua), ('update', r.ux)
                self.recs[r.pkg] = r
            self._update_reader = reader
        cfile = self.root.parent / 'cache' / 'scan-v2.json'
        try:
            cache = json.loads(cfile.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            cache = {}
        newcache = {}
        files = sorted(f for f in self.root.rglob('*.uasset')
                       if f.stem.startswith(KEEP_PREFIX))
        total = len(files)
        for i, f in enumerate(files):
            self.progress = (i, total)
            if progress and i % 25 == 0:
                progress(i, total)
            ux = f.with_suffix('.uexp')
            if not ux.is_file():
                continue
            key = f.relative_to(self.root).as_posix()
            sig = [f.stat().st_mtime_ns, f.stat().st_size,
                   ux.stat().st_mtime_ns, ux.stat().st_size]
            previous = cache.get(key)
            if previous and previous[0] == sig:
                r = self.from_data(previous[1], f, ux) if previous[1] else None
            else:
                r = self._parse(f, ux)
            newcache[key] = [sig, self.record_data(r) if r else None]
            if r is not None:
                self.recs[r.pkg] = r
        if files:
            cfile.parent.mkdir(parents=True, exist_ok=True)
            cfile.write_text(json.dumps(newcache), encoding='utf-8')
        self._link()
        self.scanned = True
        self.progress = (total, total)

    def _parse(self, f, ux):
        try:
            a = Asset(f.read_bytes(), ux.read_bytes())
            pkg = next((n for n in a.names if n.startswith('/Game/Character/')
                        and n.rsplit('/', 1)[-1] == f.stem), None)
            m = PKG_RE.match(pkg) if pkg else None
            if not m:
                return None
            r = Rec()
            r.pkg, r.ua, r.ux = pkg, f, ux
            r.char, r.var = m.group(1), m.group(2) or 'base'
            r.name = pkg.rsplit('/', 1)[1]
            r.kind = ('ps' if r.name.startswith('PS_') else
                      'mi' if r.name.startswith(('MI_', 'MII_')) else
                      'm' if r.name.startswith('M_') else 'other')
            if r.kind == 'other':
                return None
            r.fields = []          # recomputed on demand (keeps cache small)
            r.nfields = len(find_fields(a))
            for k, imp in enumerate(a.imports):
                if imp[1] in ('Material', 'MaterialInstanceConstant'):
                    p = a.object_path(-(k + 1))
                    if p:
                        r.refs.add(p)
            if r.kind == 'ps':
                r.group = classify(r.name)
                r.indicator = bool(INDICATOR_RE.search(r.name))
            return r
        except Exception as e:
            print('scan skip', f, e)
            return None

    def _link(self):
        """Work out which effect groups use each material (transitively)."""
        users = defaultdict(set)   # mat pkg -> {(group, indicator)}
        for r in self.recs.values():
            if r.kind != 'ps':
                continue
            stack = list(r.refs)
            seen = set()
            while stack:
                p = stack.pop()
                if p in seen or p not in self.recs:
                    continue
                seen.add(p)
                users[p].add((r.char, r.var, r.group, r.indicator))
                stack.extend(self.recs[p].refs)
        for pkg, u in users.items():
            r = self.recs[pkg]
            r.groups = {g for (_, _, g, _) in u}
            r.ind_only = all(ind for (_, _, _, ind) in u)

    # ------------------------------------------------------------- queries
    def characters(self):
        out = defaultdict(lambda: defaultdict(int))
        for r in self.recs.values():
            if r.kind == 'ps':
                out[r.char][r.var] += 1
        return out

    def scope_recs(self, char, var, group, include_indicators):
        """PS + material recs affected by a swap of (char, var, group|'all')."""
        ps = [r for r in self.recs.values() if r.kind == 'ps' and r.char == char and r.var == var
              and (group == 'all' or r.group == group)
              and (include_indicators or not r.indicator)]
        mats = {}
        stack = [p for r in ps for p in r.refs]
        while stack:
            p = stack.pop()
            if p in mats or p not in self.recs:
                continue
            m = self.recs[p]
            if m.ind_only and not include_indicators:
                continue
            mats[p] = m
            stack.extend(m.refs)
        return ps, list(mats.values())

    def read(self, rec):
        if isinstance(rec.ua, Path):
            return Asset(rec.ua.read_bytes(), rec.ux.read_bytes())
        if isinstance(rec.ua, tuple):
            return Asset(self._update_reader._bundle_bytes(rec.ua[1]),
                         self._update_reader._bundle_bytes(rec.ux[1]))
        return Asset(self._bundle_bytes(rec.ua), self._bundle_bytes(rec.ux))

    def _bundle_bytes(self, name):
        if not self._members:
            return self.archive.read(name)
        block, start, size = self._members[name]
        if block not in self._blocks:
            data = lzma.decompress(self.archive.read(block))
            # Bound the decompressed library cache; no extraction to disk.
            while self._blocks and sum(map(len, self._blocks.values())) + len(data) > 32 * 1024 * 1024:
                self._blocks.popitem(last=False)
            self._blocks[block] = data
        self._blocks.move_to_end(block)
        data = self._blocks[block]
        if start < 0 or size < 0 or start + size > len(data):
            raise ValueError('Invalid bundled asset bounds')
        return data[start:start + size]
