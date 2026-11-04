"""High level operations used by the UI: catalogue, palettes, previews, export."""
import json
import math
import re
import threading
import time
from functools import wraps
from pathlib import Path

from . import pak as pakmod
from .credits import add_credits
from .amount import apply_amount
from .parts import emitter_parts
from .library import GROUPS, GROUP_DESC, GROUP_LABEL, Library
from .recolor import (SAT_THR, Swap, analyse, find_fields, l2s, lin_norm_to_hex,
                      reference)

DEFAULT_NAMES = {
    'Ch001': 'Deku', 'Ch002': 'Bakugo', 'Ch003': 'Ochaco', 'Ch004': 'Todoroki', 'Ch005': 'Iida',
    'Ch006': 'Tsuyu', 'Ch007': 'Kaminari', 'Ch008': 'Kirishima', 'Ch010': 'Momo', 'Ch011': 'Tokoyami',
    'Ch012': 'All Might', 'Ch013': 'Aizawa', 'Ch015': 'Shigaraki', 'Ch016': 'All For One',
    'Ch017': 'Dabi', 'Ch018': 'Toga', 'Ch023': 'Endeavor', 'Ch024': 'Mirio', 'Ch025': 'Nejire',
    'Ch026': 'Tamaki', 'Ch034': 'Overhaul', 'Ch037': 'Twice', 'Ch038': 'Mr. Compress', 'Ch043': 'Hawks',
    'Ch046': 'Kendo', 'Ch100': 'Mt. Lady', 'Ch101': 'Cementoss', 'Ch102': 'Ibara',
    'Ch103': 'Kurogiri', 'Ch104': 'Monoma', 'Ch105': 'Shinso', 'Ch108': 'Gentle Criminal',
    'Ch109': 'Present Mic', 'Ch111': 'Mirko', 'Ch114': 'Star and Stripe', 'Ch115': 'Lady Nagant',
    'Ch200': 'Armored All Might', 'Ch201': 'All For One (Youth)', 'Ch202': 'Deku (OFA)',
    'Ch203': 'Shoto Todoroki (Phosphor)', 'Ch204': 'Toya Todoroki',
}
MOUNT = '../../../HerovsGame/Content/'

PARTS = [
    ('trail', 'Trails & tails', re.compile(r'trail|tail|ribbon|streak', re.I)),
    ('smoke', 'Smoke, dust & debris', re.compile(r'smoke|debri|dust|steam|cloud|vapor', re.I)),
    ('impact', 'Hit & impact', re.compile(r'hit|impact|burst|explo|envhit|ground|slash', re.I)),
    ('aura', 'Body, aura & hand', re.compile(r'body|aura|hand|charge|aim', re.I)),
    ('light', 'Point lights', re.compile(r'light$|_light', re.I)),
]
PART_LABEL = {k: v for k, v, _ in PARTS}


def synchronized(fn):
    @wraps(fn)
    def run(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return run


def part_of(name):
    """Which visual part an effect/material name belongs to ('main' = bullet/core)."""
    n = re.sub(r'^(PS|MI|MII|M)_(ef_)?Ch\d+(V\d+)?_?', '', name)
    if PARTS[4][2].search(n):
        return 'light'
    for key, _, rx in PARTS[:4]:
        if rx.search(n):
            return key
    return 'main'



class Engine:
    def __init__(self, base, bundle=None):
        self.base = Path(base)
        self.lib = Library(self.base / 'library', bundle)
        self.bundled_portraits = (Path(bundle).parent if bundle else self.base) / 'portraits'
        self.update_portraits = None
        self.active_ids = set(DEFAULT_NAMES)
        self.portraits = self.base / 'portraits'
        self.exports = self.base / 'exports'
        for d in (self.portraits, self.exports, self.lib.root):
            d.mkdir(parents=True, exist_ok=True)
        self.names = dict(DEFAULT_NAMES)
        nf = self.base / 'characters.json'
        if nf.exists():
            try:
                self.names.update(json.loads(nf.read_text(encoding='utf-8')))
            except Exception:
                pass
        self.status = {'state': 'idle', 'text': '', 'done': 0, 'total': 1}
        self._pal_cache = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ loading
    @synchronized
    def load(self):
        self.status = {'state': 'busy', 'text': 'Loading character assets...', 'done': 0, 'total': 1}

        def cb(i, n):
            self.status.update(done=i, total=max(n, 1))
        try:
            self._load_game_manifest()
            self.lib.scan(cb)
        except Exception as exc:
            self.status = {'state': 'error', 'text': str(exc), 'done': 0, 'total': 1}
            raise
        self._pal_cache.clear()
        self.status = {'state': 'ready', 'text': '', 'done': 1, 'total': 1}

    @synchronized
    def import_file(self, path):
        self.status = {'state': 'busy', 'text': 'Importing default assets...', 'done': 0, 'total': 1}
        try:
            n = self.lib.import_path(path)
        finally:
            self.load()
        return n

    # ------------------------------------------------------------ catalogue
    def _load_game_manifest(self):
        from .game_update import library_base_id, read_manifest
        manifest, generation = read_manifest(self.base)
        if generation and manifest.get('library_base') != library_base_id(self.lib.archive_path):
            generation = None
        self.active_ids = set(manifest['characters']) if generation else set(DEFAULT_NAMES)
        self.lib.update_archive = generation / 'library.zip' if generation else None
        self.update_portraits = generation / 'portraits' if generation else None

    def portrait_path(self, char):
        for directory in (self.portraits, self.update_portraits, self.bundled_portraits):
            if directory is None:
                continue
            for ext in ('png', 'jpg', 'jpeg', 'webp'):
                path = directory / f'{char}.{ext}'
                if path.is_file():
                    return path
        return None

    def portrait_url(self, char):
        path = self.portrait_path(char)
        return f'/portraits/{path.name}?t={path.stat().st_mtime_ns}' if path else None

    def characters(self):
        found = self.lib.characters()
        out = []
        for cid in sorted(set(found) & self.active_ids):
            vars_ = found.get(cid, {})
            out.append({
                'id': cid,
                'name': self.names.get(cid, f'Character {cid}'),
                'portrait': self.portrait_url(cid),
                'variants': [{'key': k, 'label': 'Default' if k == 'base' else k.replace('Var', 'Variation '),
                              'effects': n} for k, n in sorted(vars_.items(), key=lambda kv: (kv[0] != 'base', kv[0]))],
                'effects': sum(vars_.values()),
            })
        return out

    def _entries(self, rec):
        if rec.ent is None:
            a = self.lib.read(rec)
            fields = find_fields(a)
            ent = []
            for f in fields:
                es = f.entries(a.ux)
                for c in es:
                    ent.append((c, 1.0 / len(es)))
            rec.ent = ent
        return rec.ent

    def _scope_entries(self, char, var, group, ind):
        ps, mats = self.lib.scope_recs(char, var, group, ind)
        ent = []
        for r in ps + mats:
            ent += self._entries(r)
        return ps, mats, ent

    @staticmethod
    def _bucket(rgb):
        m, h, s = analyse(rgb)
        if m <= 0.02:
            return None
        return 'g' if s < SAT_THR else int(h * 24) % 24

    def _palette(self, ent, new=None, keys=None, top=6):
        """Colour swatches. ent = original entries; new = parallel transformed colours."""
        acc = {}
        for i, (rgb, w) in enumerate(ent):
            k = self._bucket(rgb)
            if k is None:
                continue
            c = new[i] if new else rgb
            m = max(c)
            n = (0, 0, 0) if m <= 1e-6 else tuple(x / m for x in c)
            a = acc.setdefault(k, [0.0, [0.0, 0.0, 0.0]])
            a[0] += w
            for j in range(3):
                a[1][j] += n[j] * w
        if keys is None:
            keys = [k for k, _ in sorted(acc.items(), key=lambda kv: -kv[1][0])[:top]]
        out = []
        for k in keys:
            if k in acc and acc[k][0] > 0:
                w, sm = acc[k]
                out.append(lin_norm_to_hex(tuple(x / w for x in sm)))
        return keys, out

    @synchronized
    def groups(self, char, var):
        res = []
        ps_all = [r for r in self.lib.recs.values() if r.kind == 'ps' and r.char == char and r.var == var]
        for key, label, desc in [('all', 'All Effects', 'Every effect of this character at once')] + list(GROUPS):
            ps = [r for r in ps_all if key == 'all' or r.group == key]
            if not ps:
                continue
            _, mats, ent = self._scope_entries(char, var, key, True)
            keys, pal = self._palette(ent)
            self._pal_cache[(char, var, key)] = (keys, ent)
            res.append({
                'key': key, 'label': label, 'desc': desc, 'effects': len(ps), 'materials': len(mats),
                'palette': pal,
                'id': f'VFX_{char[2:]}_{key.upper()}' if key != 'all' else f'VFX_{char[2:]}_ALL',
                'files': [r.name for r in ps][:200],
            })
        return res

    def _selection(self, a):
        ps, mats = self.lib.scope_recs(a['char'], a['var'], a['group'],
                                       bool(a.get('indicators', False)))
        parts = set((a.get('secondary') or {}).get('parts') or [])
        material_users = {}
        selected = []
        for r in ps:
            asset = self.lib.read(r)
            module_parts, uses = emitter_parts(asset, part_of) if parts else ({}, {})
            default = part_of(r.name)
            for path in r.refs:
                roles = {default if p == 'main' else p for p in uses.get(path, {default})}
                material_users.setdefault(path, set()).update(roles)
            fs = find_fields(asset)
            for f in fs:
                roles = {default if p == 'main' else p
                         for p in module_parts.get(f.export_index, {default})}
                f.secondary = bool(roles) and roles <= parts
            selected.append((r, asset, fs))
        # Propagate roles through parent materials. Shared primary/secondary
        # materials remain primary; per-emitter particle colors still split.
        stack = list(material_users)
        while stack:
            path = stack.pop()
            if path not in self.lib.recs:
                continue
            for parent in self.lib.recs[path].refs:
                old = material_users.setdefault(parent, set())
                before = len(old)
                old.update(material_users[path])
                if len(old) != before:
                    stack.append(parent)
        conflicts = []
        for r in mats:
            asset = self.lib.read(r)
            fs = find_fields(asset)
            roles = material_users.get(r.pkg, {part_of(r.name)})
            if roles & parts and roles - parts:
                conflicts.append(r.name)
            own_part = part_of(r.name)
            secondary = not (roles - parts) and (own_part in parts if own_part != 'main'
                         else bool(roles) and roles <= parts)
            for f in fs:
                f.secondary = secondary
            selected.append((r, asset, fs))
        return selected, conflicts

    @staticmethod
    def _selected_entries(selected):
        primary, secondary = [], []
        for r, asset, fs in selected:
            for f in fs:
                es = f.entries(asset.ux)
                target = secondary if f.secondary else primary
                target.extend((c, 1.0 / len(es)) for c in es)
        return primary, secondary

    def _ents(self, recs):
        ent = []
        for r in recs:
            ent += self._entries(r)
        return ent

    def _swaps(self, a, ent_p, ent_s):
        sp = self._swap(a, ent_p)
        sec = a.get('secondary')
        ss = Swap(sec['hex'], 'original' if a.get('mode') == 'original' else 'unify',
                  reference(ent_s), float(a.get('intensity', 1.0)), True) if sec else None
        return sp, ss

    @synchronized
    def preview(self, a):
        self.validate_assignment(a)
        selected, _ = self._selection(a)
        ent_p, ent_s = self._selected_entries(selected)
        sp, ss = self._swaps(a, ent_p, ent_s)
        result = []
        for ent, fn in ((ent_p, sp), (ent_s, ss)):
            if ent and fn:
                _, colors = self._palette(ent, [fn(c) for c, _ in ent])
                result.extend(c for c in colors if c not in result)
        return result[:10]

    @staticmethod
    def _swap(a, ent):
        return Swap(a['hex'], a.get('mode', 'shift'), reference(ent),
                    float(a.get('intensity', 1.0)), bool(a.get('tint_white', False)))

    def parts_info(self):
        return [{'key': k, 'label': l} for k, l, _ in PARTS]

    def validate_assignment(self, a):
        if not isinstance(a, dict):
            raise ValueError('Invalid effect settings.')
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(a.get('hex', ''))):
            raise ValueError('Choose a valid six-digit color.')
        if a.get('mode', 'shift') not in ('shift', 'unify', 'original'):
            raise ValueError('Unknown color mode.')
        for key, default, maximum in (('amount', 100, 100), ('intensity', 1, 2.5)):
            value = float(a.get(key, default))
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f'{key} must be between 0 and {maximum}.')
        if a.get('group') not in {'all', *GROUP_LABEL}:
            raise ValueError('Unknown effect group.')
        if a.get('var') not in self.lib.characters().get(a.get('char'), {}):
            raise ValueError('Character variation has no imported effect files.')
        if a.get('char') not in self.active_ids:
            raise ValueError('This character is not in the active game roster. Refresh the game files in Settings.')
        sec = a.get('secondary')
        if sec:
            if not isinstance(sec, dict) or not re.fullmatch(r'#[0-9a-fA-F]{6}', str(sec.get('hex', ''))):
                raise ValueError('Choose a valid secondary color.')
            if not isinstance(sec.get('parts'), list) or not set(sec['parts']) <= set(PART_LABEL):
                raise ValueError('Invalid secondary part categories.')

    # ------------------------------------------------------------ export
    @synchronized
    def build(self, assignments, name, progress=None, global_cfg=None, exclude=()):
        assignments = list(assignments)
        if global_cfg:
            base = []
            for cid, vars_ in sorted(self.lib.characters().items()):
                if cid in exclude or cid not in self.active_ids:
                    continue
                for var in sorted(vars_):
                    base.append(dict(global_cfg, char=cid, var=var, group='all'))
            assignments = base + assignments
        assignments = [a for a in assignments if a.get('char') not in exclude]
        for a in assignments:
            self.validate_assignment(a)
        patched = {}
        report = {'assignments': len(assignments), 'shared': [], 'two_color_shared': [],
                  'amount_unsupported': [], 'amount_assets': 0, 'secondary_fields': 0,
                  'secondary_requested': any(a.get('secondary') and a.get('mode') != 'original'
                                             for a in assignments)}
        missing, common = set(), set()
        swapped, touched = {}, {}
        total = max(1, len(assignments))
        for ai, a in enumerate(assignments):
            if a['char'] in exclude:
                continue
            selected, conflicts = self._selection(a)
            report['two_color_shared'].extend(conflicts)
            ps = [r for r, _, _ in selected if r.kind == 'ps']
            mats = [r for r, _, _ in selected if r.kind != 'ps']
            sp, ss = self._swaps(a, *self._selected_entries(selected))
            for r, asset, fields in selected:
                buf = bytearray(asset.ux)
                for f in fields:
                    fn = ss if f.secondary and ss else sp
                    f.apply(buf, fn)
                    report['secondary_fields'] += int(f.secondary)
                amount = float(a.get('amount', 100))
                if r.kind == 'ps' and amount != 100:
                    if apply_amount(asset, buf, amount):
                        report['amount_assets'] += 1
                    else:
                        report['amount_unsupported'].append(r.name)
                if buf != asset.ux:
                    patched[r.pkg] = (r, asset.ua, bytes(buf))
                else:
                    patched.pop(r.pkg, None)
            swapped.setdefault((a['char'], a['var']), set()).update(
                set(GROUP_LABEL) if a['group'] == 'all' else {a['group']})
            for r in mats:
                touched[r.pkg] = r
            for r in ps:
                for p in r.refs:
                    if p not in self.lib.recs:
                        (common if p.startswith('/Game/Effect/Common') else missing).add(p.rsplit('/', 1)[-1])
            if progress:
                progress(ai + 1, total)
        for pkg, r in touched.items():
            outside = r.groups - swapped.get((r.char, r.var), set())
            if outside:
                report['shared'].append(f"{r.name} (also used by {', '.join(GROUP_LABEL[g] for g in sorted(outside))})")
        files = {}
        for pkg, (r, ua, buf) in patched.items():
            path = pkg.replace('/Game/', '', 1)
            files[path + '.uasset'] = ua
            files[path + '.uexp'] = buf
        report['two_color_shared'] = sorted(set(report['two_color_shared']))
        report['amount_unsupported'] = sorted(set(report['amount_unsupported']))
        report['missing'] = sorted(missing)[:40]
        report['missing_count'] = len(missing)
        report['common_count'] = len(common)
        report['assets'] = len(files) // 2
        report['characters'] = len({r.char for (r, ua, b) in patched.values()})
        report['shared'] = sorted(set(report['shared']))[:30]
        if not files:
            return None, report
        add_credits(files)
        safe = re.sub(r'[^A-Za-z0-9_\-]+', '_', name).strip('_') or 'MHUR_VFX_Recolor'
        out = self.exports / f'{safe}-WindowsNoEditor_P.pak'
        pakmod.write_pak(out, MOUNT, files)
        report['file'] = out.name
        report['size'] = out.stat().st_size
        return out, report
