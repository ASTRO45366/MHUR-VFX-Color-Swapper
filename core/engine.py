"""High level operations used by the UI: catalogue, palettes, previews, export."""
import json
import math
import re
import struct
import threading
import time
from functools import wraps
from pathlib import Path

from . import pak as pakmod
from .credits import add_credits
from .amount import apply_amount
from .parts import emitter_parts
from .library import is_effect_asset, GROUPS, GROUP_DESC, GROUP_LABEL, Library
from .texture import DATA_NAME, TextureTint, endpoint_colors, is_color_texture, parse_texture, recolor_texture, texture_kind
from .uasset import Asset
from .recolor import (SAT_THR, Swap, analyse, find_fields, hex_to_rgb, l2s, lin_norm_to_hex,
                      reference, s2l)

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
DEFAULT_SPREAD = 60

PARTS = [
    ('trail', 'Trails & tails', frozenset({'trail', 'trails', 'tail', 'tails', 'ribbon', 'streak'})),
    ('smoke', 'Smoke, dust & debris', frozenset({'smoke', 'debri', 'debris', 'dust', 'steam', 'cloud', 'vapor'})),
    ('impact', 'Hit & impact', frozenset({'hit', 'impact', 'burst', 'explo', 'explosion', 'envhit', 'ground', 'slash'})),
    ('aura', 'Body, aura & hand', frozenset({'body', 'aura', 'hand', 'charge', 'aim'})),
    ('light', 'Point lights', frozenset({'light'})),
]
PART_LABEL = {k: v for k, v, _ in PARTS}


def synchronized(fn):
    @wraps(fn)
    def run(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    return run


MAX_LEVEL = 3
# _L1.._L3 (most characters), _L01.._L03, and _LVL1/_LVL4/_LVL9 (in-game skill level 1/4/9)
LEVEL_RE = re.compile(r'(?:^|_)(L|LV|LVL|Lv|Lvl|lv|lvl)0?(\d)(?=_|$)')


def level_steps(name):
    """How many skill levels below the maximum an effect/material is (None = no level in name)."""
    m = LEVEL_RE.search(name)
    if not m:
        return None
    level = int(m.group(2))
    if m.group(1).lower() == 'lvl':  # game skill levels: 9 = max, 4..8 one step below, 1..3 two
        return 0 if level >= 9 else 1 if level >= 4 else 2
    return max(0, MAX_LEVEL - level)


# Walking/running/landing dust etc. ('Other' group only, so skill and special
# effects such as a special-move dash keep being recolored).
MOVEMENT_WORDS = frozenset({'walk', 'run', 'running', 'step', 'steps', 'footstep', 'land', 'landing',
                            'jump', 'dash', 'foot', 'footsmoke', 'move', 'dust', 'airwalk'})


def is_movement(rec):
    if rec.kind != 'ps' or rec.group != 'other':
        return False
    n = re.sub(r'^PS_(ef_)?(Gasha_)?Ch\d+(V\d+)?_?', '', rec.name)
    return bool(MOVEMENT_WORDS & set(_tokens(n)))



# Solid move objects (ice, stone, cracks, spikes) get their look from textures.
# Recoloring them is optional; it is on by default only where the plain effect
# recolor would otherwise look unfinished.
OBJECT_DEFAULTS = {'Ch015': ('alpha', 'beta', 'gamma')}   # Shigaraki: decay cracks
# Characters whose moves are mostly solid objects (shown as suggestions in the UI)
OBJECT_SUGGESTED = {'Ch004', 'Ch008', 'Ch015', 'Ch034', 'Ch101'}


def check_spans(name, old, new, spans):
    """Texture data may only change inside its pixel (mip) data, at the same size."""
    if len(old) != len(new):
        raise RuntimeError(f'Safety check stopped the export: {name}: texture size changed.')
    if old == new:
        return
    mask = bytearray(len(new))
    for a, b in spans:
        mask[a:b] = b'\x01' * (b - a)
    for off in range(0, len(new), 4096):
        if new[off:off + 4096] != old[off:off + 4096]:
            for i in range(off, min(off + 4096, len(new))):
                if new[i] != old[i] and not mask[i]:
                    raise RuntimeError(f'Safety check stopped the export: {name}: non-pixel texture data changed.')


BASE_SLOT = re.compile(r'^(base_?colou?r|base|diffuse|albedo|main_?tex(ture)?|colou?r_?tex(ture)?|tex_?d|d|'
                       r'base_?colou?r_?tex(ture)?|diffuse_?tex(ture)?|albedo_?tex(ture)?|'
                       r'emissive|emissive_?(colou?r_?)?tex(ture)?|emi_?tex|em_?tex|e)(_?\d+)?$', re.I)


def base_color_params(asset):
    """Texture packages plugged into a base-colour slot of a material instance."""
    out = []
    for ei, e in enumerate(asset.exports):
        if e['class'] != 'MaterialInstanceConstant':
            continue
        for p in asset.export_props(ei):
            if p.name != 'TextureParameterValues':
                continue
            for c in p.children or []:
                d = {x.name: x for x in c.children or []}
                info, value = d.get('ParameterInfo'), d.get('ParameterValue')
                if not info or not value or not info.children:
                    continue
                name = asset.fname(asset.ux, info.children[0].vpos)
                if BASE_SLOT.match(name):
                    path = asset.object_path(struct.unpack_from('<i', asset.ux, value.vpos)[0])
                    if path:
                        out.append(path)
    return out



def objects_default(char, group):
    return group in OBJECT_DEFAULTS.get(char, ())


def pak_filename(name):
    """'Red VFX' -> 'ZZZ_Red_VFX-WindowsNoEditor_P.pak'.

    ZZZ makes the mod load after the game's own paks; the suffix is what the game
    expects. Names typed with '.pak' or the suffix already are not doubled.
    """
    base = re.sub(r'\.pak$', '', str(name or '').strip(), flags=re.I)
    base = re.sub(r'(-WindowsNoEditor)?(_P)?$', '', base, flags=re.I)
    safe = re.sub(r'[^A-Za-z0-9_\-]+', '_', base).strip('_-')[:60] or 'MHUR_VFX_Recolor'
    if safe[:3].upper() == 'ZZZ':
        safe = 'ZZZ' + safe[3:]
    else:
        safe = 'ZZZ_' + safe
    return f'{safe}-WindowsNoEditor_P.pak'
# Team-indicator colours inside effect materials (enemy/ally warnings stay readable)
INDICATOR_PARAM_RE = re.compile(r'enemy|ally|friend|myself|self_?colou?r|^self', re.I)


def color_fields(asset, indicators):
    """find_fields minus enemy/ally indicator parameters unless indicators are allowed."""
    fs = find_fields(asset)
    if indicators:
        return fs
    return [f for f in fs if not (f.kind == 'param' and INDICATOR_PARAM_RE.search(f.label))]


def _tokens(name):
    """Lower-case words of an asset/emitter name (splits _, digits and camelCase)."""
    words = re.findall(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+', re.sub(r'\d+', ' ', name.replace('_', ' ')))
    return [w.lower() for w in words]


def part_of(name):
    """Which visual part an effect/material name belongs to ('main' = bullet/core).

    Whole words only, so 'White' is not 'hit' and 'Lightning' is not a light.
    """
    n = re.sub(r'^(PS|MI|MII|M)_(ef_)?Ch\d+(V\d+)?_?', '', name)
    words = set(_tokens(n))
    if _tokens(n)[-1:] == ['light'] or 'light' in words and 'lightning' not in words:
        return 'light'
    for key, _, vocab in PARTS[:4]:
        if words & vocab:
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
        self._slot_textures = set()
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
                'object_textures': len(set().union(*(self._object_textures(r) for r in ps))) if ps else 0,
                'objects_default': (any(objects_default(char, r.group) for r in ps) if key == 'all'
                                    else objects_default(char, key)),
                'objects_suggested': char in OBJECT_SUGGESTED,
            })
        return res

    def _selection(self, a):
        keep = None if a.get('movement') else (lambda r: not is_movement(r))
        ps, mats = self.lib.scope_recs(a['char'], a['var'], a['group'],
                                       bool(a.get('indicators', False)), keep)
        mats = [r for r in mats if is_effect_asset(r.pkg)]   # never character bodies, outfits or props
        parts = set((a.get('secondary') or {}).get('parts') or [])
        material_users = {}
        material_steps = {}
        selected = []
        for r in ps:
            asset = self.lib.read(r)
            steps = level_steps(r.name) or 0
            for path in r.refs:
                material_steps.setdefault(path, set()).add(steps)
            module_parts, uses = emitter_parts(asset, part_of) if parts else ({}, {})
            default = part_of(r.name)
            for path in r.refs:
                roles = {default if p == 'main' else p for p in uses.get(path, {default})}
                material_users.setdefault(path, set()).update(roles)
            fs = color_fields(asset, bool(a.get('indicators', False)))
            for f in fs:
                roles = {default if p == 'main' else p
                         for p in module_parts.get(f.export_index, {default})}
                f.secondary = bool(roles) and roles <= parts
                f.steps = steps
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
                lv = material_steps.setdefault(parent, set())
                nlv = len(lv)
                lv.update(material_steps.get(path, ()))
                if len(old) != before or len(lv) != nlv:
                    stack.append(parent)
        conflicts = []
        for r in mats:
            asset = self.lib.read(r)
            fs = color_fields(asset, bool(a.get('indicators', False)))
            roles = material_users.get(r.pkg, {part_of(r.name)})
            if roles & parts and roles - parts:
                conflicts.append(r.name)
            own_part = part_of(r.name)
            secondary = not (roles - parts) and (own_part in parts if own_part != 'main'
                         else bool(roles) and roles <= parts)
            own = level_steps(r.name)
            users = material_steps.get(r.pkg) or {0}
            steps = own if own is not None else (next(iter(users)) if len(users) == 1 else 0)
            for f in fs:
                f.secondary = secondary
                f.steps = steps
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

    @staticmethod
    def amounts(a):
        """(main amount, second-colour amount); the second follows the main one unless set."""
        main = float(a.get('amount', 100))
        sec = a.get('secondary')
        return main, (float(sec.get('amount', main)) if sec else main)

    def _apply_amounts(self, a, r, asset, buf, touched=None):
        """Patch spawn amounts. None = nothing requested; else number of values changed."""
        main, second = self.amounts(a)
        if main == 100 and second == 100:
            return None
        if main == second:
            return apply_amount(asset, buf, main, touched=touched)
        parts = set(a['secondary'].get('parts') or [])
        module_parts, _ = emitter_parts(asset, part_of)
        default = part_of(r.name)

        def is_second(i):
            roles = {default if p == 'main' else p for p in module_parts.get(i, {default})}
            return bool(roles) and roles <= parts
        changed = (apply_amount(asset, buf, main, lambda i: not is_second(i), touched)
                   + apply_amount(asset, buf, second, is_second, touched))
        return changed or None  # nothing to scale in the targeted emitters is not an error

    @staticmethod
    def field_swap(a, f, sp, ss):
        fn = ss if f.secondary and ss else sp
        return fn.variant(getattr(f, 'steps', 0), float(a.get('level_spread', DEFAULT_SPREAD)) / 100.0)

    @synchronized
    def preview_info(self, a):
        """Palette (exact max-level colours) plus how the fields split between the colours."""
        self.validate_assignment(a)
        selected, conflicts = self._selection(a)
        ent_p, ent_s = self._selected_entries(selected)
        sp, ss = self._swaps(a, ent_p, ent_s)
        result = []
        for ent, fn in ((ent_p, sp), (ent_s, ss)):
            if ent and fn:
                _, colors = self._palette(ent, [fn(c) for c, _ in ent])
                result.extend(c for c in colors if c not in result)
        # Aligned before/after swatches: same colour buckets, original vs. new (max level).
        ent_all = list(ent_p or []) + list(ent_s or [])
        keys, before = self._palette(ent_all)
        after_colors = ([sp(c) for c, _ in ent_p or []] if sp else [c for c, _ in ent_p or []]) + \
            ([ss(c) for c, _ in ent_s or []] if ss else [c for c, _ in ent_s or []])
        _, after = self._palette(ent_all, after_colors, keys) if ent_all else (None, [])
        fields = [f for _, _, fs in selected for f in fs]
        return {'palette': result[:10], 'before': before, 'after': after, 'main_fields': sum(not f.secondary for f in fields),
                'second_fields': sum(bool(f.secondary) for f in fields),
                'shared_materials': len(conflicts),
                'second_dark': bool(ss and ss.tv < 0.2)}

    def preview(self, a):
        return self.preview_info(a)['palette']

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
        for key, default, maximum in (('amount', 100, 100), ('intensity', 1, 2.5), ('level_spread', DEFAULT_SPREAD, 100)):
            value = float(a.get(key, default))
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError(f'{key} must be between 0 and {maximum}.')
        if a.get('group') not in {'all', *GROUP_LABEL}:
            raise ValueError('Unknown effect group.')
        if a.get('var') not in self.lib.characters().get(a.get('char'), {}):
            raise ValueError('Character variation has no imported effect files.')
        if a.get('char') not in self.active_ids:
            raise ValueError('This character is not in the active game roster. Refresh the game files in Settings.')
        if a.get('objects') is not None and not isinstance(a['objects'], bool):
            raise ValueError('objects must be true or false.')
        for key in ('movement', 'indicators', 'tint_white'):
            if key in a and not isinstance(a[key], bool):
                raise ValueError(f'{key} must be true or false.')
        sec = a.get('secondary')
        if sec:
            if not isinstance(sec, dict) or not re.fullmatch(r'#[0-9a-fA-F]{6}', str(sec.get('hex', ''))):
                raise ValueError('Choose a valid secondary color.')
            if not isinstance(sec.get('parts'), list) or not set(sec['parts']) <= set(PART_LABEL):
                raise ValueError('Invalid secondary part categories.')
            value = float(sec.get('amount', a.get('amount', 100)))
            if not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError('amount must be between 0 and 100.')

    # ------------------------------------------------------------ safety
    def _check_cosmetic(self, rec, ua, buf, spans):
        """Refuse to export anything but colour / particle-amount edits of effect assets.

        Hitboxes, collision, animation, damage and movement live in blueprints, data
        assets and animation files, which are never written. Inside the effect files
        every changed byte must belong to a colour value or a spawn-amount value, so
        sizes, lifetimes, velocities, locations and similar data stay untouched.
        """
        original = self.lib.read(rec)
        problem = None
        if rec.kind not in ('ps', 'mi', 'm'):
            problem = 'unsupported asset type'
        elif not rec.pkg.startswith('/Game/Character/'):
            problem = 'asset outside character folders'
        elif ua != original.ua:
            problem = 'asset header changed'
        elif len(buf) != len(original.ux):
            problem = 'asset size changed'
        else:
            mask = bytearray(len(buf))
            for start, end in spans:
                mask[max(0, start):max(0, min(end, len(buf)))] = b'\x01' * max(0, min(end, len(buf)) - max(0, start))
            old = original.ux
            for off in range(0, len(buf), 256):
                if buf[off:off + 256] != old[off:off + 256]:
                    for i in range(off, min(off + 256, len(buf))):
                        if buf[i] != old[i] and not mask[i]:
                            problem = f'non-color data changed at byte {i}'
                            break
                if problem:
                    break
        if problem:
            raise RuntimeError(f'Safety check stopped the export: {rec.name} ({rec.pkg}): {problem}. '
                               'The mod would have changed more than effect colors, so no pak was written.')

    # ------------------------------------------------------------ export
    @synchronized
    def objects_enabled(self, a, char, var, group, choices):
        """Solid-object recolor for one skill: assignment choice > saved per-skill choice > default."""
        if a.get('objects') is not None and (a.get('group') in ('all', group)):
            if a.get('_global') is None:
                return bool(a['objects'])
        key = f'{char}:{var}:{group}'
        if key in choices:
            return bool(choices[key])
        return objects_default(char, group)

    def _object_textures(self, rec):
        """Colour textures used by a particle system's materials (character folders only)."""
        out, seen, stack = set(), set(), list(rec.refs) + ([rec.pkg] if rec.kind != 'ps' else [])
        while stack:
            path = stack.pop()
            if path in seen or path not in self.lib.recs:
                continue
            seen.add(path)
            mrec = self.lib.recs[path]
            if not is_effect_asset(path):
                continue
            stack.extend(mrec.refs)
            try:
                asset = self.lib.read(mrec)
            except Exception:
                continue
            for n in asset.names:
                if n.startswith('/Game/Character/') and is_effect_asset(n) and is_color_texture(n):
                    out.add(n)
            for n in base_color_params(asset):
                if n.startswith('/Game/Character/') and is_effect_asset(n) and not DATA_NAME.search(n.rsplit('/', 1)[-1][2:]):
                    out.add(n)
                    self._slot_textures.add(n)
        return out

    def _apply_textures(self, jobs, files, report, progress):
        """Recolor queued textures in place and add them to the pak."""
        jobs = {k: v for k, v in jobs.items() if is_effect_asset(k)}
        report['textures'] = 0
        report['textures_unavailable'] = 0
        if not jobs:
            return
        store = getattr(self, 'texture_store', None)
        got = store.get(list(jobs), progress) if store else {}
        report['textures_unavailable'] = len(jobs) - len(got)
        report['textures_need_game'] = bool(len(got) < len(jobs) and not (store and store.available()))
        for i, (pkg, fn) in enumerate(sorted(jobs.items())):
            if pkg not in got:
                continue
            ua, ux, ub = got[pkg]
            try:
                info = parse_texture(Asset(ua, ux), ux, len(ub))
            except Exception:
                info = None
            if not info or not info.mips:
                report['textures_unavailable'] += 1
                continue
            if texture_kind(pkg) != 'color' and pkg not in self._slot_textures and not info.srgb:
                continue   # linear data texture (mask / packed channels): never recolor
            if progress and i % 4 == 0:
                progress(f'Recoloring textures ({i + 1}/{len(jobs)})…', i, len(jobs))
            hex_color, mode, intensity, second = fn
            tint = TextureTint(hex_color, mode, intensity, endpoint_colors(info, ux, ub, 3000), info.srgb, second)
            nux, nub, sux, sub = recolor_texture(info, ux, ub, tint)
            check_spans(pkg, ux, nux, sux)
            check_spans(pkg, ub, nub, sub)
            rel = pkg.replace('/Game/', '', 1)
            files[rel + '.uasset'] = ua
            files[rel + '.uexp'] = nux
            if ub:
                files[rel + '.ubulk'] = nub
            report['textures'] += 1

    @synchronized
    def diagnose(self, char, var, group):
        """Plain-text report of what a skill contains and what the app recolors (for bug reports)."""
        from .recolor import _prop_map, is_color_param
        ps, _ = self.lib.scope_recs(char, var, group, True)
        lines = [f'MHUR VFX Color Swapper diagnostic report', f'Skill: {char} {var} {group}', '']
        seen = set()
        for r in sorted(ps, key=lambda r: r.name):
            flags = []
            if is_movement(r):
                flags.append('walking dust')
            if r.indicator:
                flags.append('indicator')
            lines.append(f'PS {r.name}  [group {r.group}{", " + ", ".join(flags) if flags else ""}]')
            try:
                fields = find_fields(self.lib.read(r))
                kinds = {}
                for f in fields:
                    kinds[f.kind] = kinds.get(f.kind, 0) + 1
                lines.append(f'   particle colour fields: {kinds or "none"}')
            except Exception as exc:
                lines.append(f'   (could not read: {exc})')
            stack = list(r.refs)
            while stack:
                path = stack.pop()
                if path in seen:
                    continue
                seen.add(path)
                leaf = path.rsplit('/', 1)[-1]
                if path not in self.lib.recs:
                    lines.append(f'   material {leaf}: NOT IN LIBRARY ({path})')
                    continue
                mrec = self.lib.recs[path]
                stack.extend(mrec.refs)
                asset = self.lib.read(mrec)
                found = {f.label for f in find_fields(asset)}
                lines.append(f'   material {leaf}')
                for ei, e in enumerate(asset.exports):
                    if e['class'] != 'MaterialInstanceConstant':
                        continue
                    for p in asset.export_props(ei):
                        if p.name == 'VectorParameterValues':
                            for c in p.children or []:
                                d = _prop_map(c.children)
                                name = asset.fname(asset.ux, d['ParameterInfo'].children[0].vpos)
                                val = struct.unpack_from('<4f', asset.ux, d['ParameterValue'].vpos)
                                mark = 'RECOLORED' if name in found else 'kept'
                                lines.append(f'      vector {name} = ({", ".join(f"{x:.3g}" for x in val)})  {mark}')
                        if p.name == 'TextureParameterValues':
                            for c in p.children or []:
                                d = _prop_map(c.children)
                                name = asset.fname(asset.ux, d['ParameterInfo'].children[0].vpos)
                                tex = asset.object_path(struct.unpack_from('<i', asset.ux, d['ParameterValue'].vpos)[0])
                                lines.append(f'      texture slot {name} = {tex}')
                for f in find_fields(asset):
                    if f.label.endswith('(default)'):
                        lines.append(f'      default {f.label}  RECOLORED')
                for n in asset.names:
                    if '/T_' in n and n.startswith('/Game/'):
                        kind = texture_kind(n) or ('slot' if n in self._slot_textures else '-')
                        lines.append(f'      uses texture {n.rsplit("/", 1)[-1]}  [{kind}]  {n}')
            lines.append('')
        lines.append(f'Solid-object textures for this skill: {len(set().union(*(self._object_textures(r) for r in ps))) if ps else 0}')
        return '\n'.join(lines)

    def build(self, assignments, name, progress=None, global_cfg=None, exclude=(), objects=None, compress=False):
        assignments = list(assignments)
        if global_cfg:
            base = []
            for cid, vars_ in sorted(self.lib.characters().items()):
                if cid in exclude or cid not in self.active_ids:
                    continue
                for var in sorted(vars_):
                    base.append(dict(global_cfg, char=cid, var=var, group='all', _global=True))
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
        allowed = {}   # pkg -> byte ranges the export may change (colour fields + spawn values)
        choices = {k: bool(v) for k, v in (objects or {}).items() if isinstance(k, str)}
        tex_jobs = {}  # texture pkg -> colour function (later assignments win, like effects)
        report['movement_skipped'] = 0
        total = max(1, len(assignments))
        for ai, a in enumerate(assignments):
            if a['char'] in exclude:
                continue
            selected, conflicts = self._selection(a)
            report['two_color_shared'].extend(conflicts)
            if not a.get('movement'):
                report['movement_skipped'] += sum(
                    1 for r in self.lib.scope_recs(a['char'], a['var'], a['group'], True)[0] if is_movement(r))
            ps = [r for r, _, _ in selected if r.kind == 'ps']
            mats = [r for r, _, _ in selected if r.kind != 'ps']
            sp, ss = self._swaps(a, *self._selected_entries(selected))
            if a.get('mode') != 'original':
                for r in ps + [m for m in mats if m.orphan]:
                    groups = [r.group] if r.kind == 'ps' else sorted(r.groups)
                    if any(self.objects_enabled(a, a['char'], a['var'], g, choices) for g in groups):
                        second = (a.get('secondary') or {}).get('hex')
                        for tex in self._object_textures(r):
                            tex_jobs[tex] = (a['hex'], a.get('mode', 'unify'), float(a.get('intensity', 1)), second)
            for r, asset, fields in selected:
                # continue from an earlier assignment's patch of the same asset
                buf = bytearray(patched[r.pkg][2]) if r.pkg in patched else bytearray(asset.ux)
                spans = allowed.setdefault(r.pkg, set())
                for f in fields:
                    f.apply(buf, self.field_swap(a, f, sp, ss))
                    spans.update(f.spans(asset.ux))
                    report['secondary_fields'] += int(f.secondary)
                if r.kind == 'ps':
                    edited = set()
                    done = self._apply_amounts(a, r, asset, buf, edited)
                    spans.update((pos, pos + n) for pos, n in edited)
                    if done:
                        report['amount_assets'] += 1
                    elif done is not None:
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
                        leaf = p.rsplit('/', 1)[-1]
                        if not re.search(r'(^|_)ef_', leaf):
                            continue  # character body / engine default materials: never recolored
                        (common if '/Character/' not in p else missing).add(leaf)
            if progress:
                progress(ai + 1, total)
        for pkg, r in touched.items():
            outside = r.groups - swapped.get((r.char, r.var), set())
            if outside:
                report['shared'].append(f"{r.name} (also used by {', '.join(GROUP_LABEL[g] for g in sorted(outside))})")
        report['skipped_non_effect'] = []
        for pkg in [p for p, (r, _, _) in patched.items() if r.kind != 'ps' and not is_effect_asset(p)]:
            # a character model / outfit / prop material reached through an effect: leave it out
            report['skipped_non_effect'].append(patched.pop(pkg)[0].name)
        for pkg, (r, ua, buf) in patched.items():
            self._check_cosmetic(r, ua, buf, allowed.get(pkg, ()))
        files = {}
        for pkg, (r, ua, buf) in patched.items():
            path = pkg.replace('/Game/', '', 1)
            files[path + '.uasset'] = ua
            files[path + '.uexp'] = buf
        self._apply_textures(tex_jobs, files, report,
                             (lambda t, i, n: progress(i, max(n, 1), t)) if progress else None)
        report['two_color_shared'] = sorted(set(report['two_color_shared']))
        report['amount_unsupported'] = sorted(set(report['amount_unsupported']))
        report['missing'] = sorted(missing)[:40]
        report['missing_count'] = len(missing)
        report['common_count'] = len(common)
        report['assets'] = len(patched)
        report['characters'] = len({r.char for (r, ua, b) in patched.values()})
        report['shared'] = sorted(set(report['shared']))[:30]
        if not files:
            return None, report
        add_credits(files)
        out = self.exports / pak_filename(name)
        pakmod.write_pak(out, MOUNT, files, compress)
        report['file'] = out.name
        report['size'] = out.stat().st_size
        return out, report
