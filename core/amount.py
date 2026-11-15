"""Patch existing Cascade spawn settings without resizing cooked exports.

The amount is meant to look proportional: 40 % should look like 40 % of the
effect, and only 0 % makes it invisible. Spawn rates scale exactly, but burst
counts are integers: many big effects (a flame mesh, a beam, a slash) spawn a
single particle per burst, and plain rounding would delete them below 50 %.
So a non-zero burst keeps at least one particle while the amount is above 0,
and the part that could not be removed from the count is taken off the
emitter's opacity instead (count x opacity = requested amount).
"""
import math
import struct

ALPHA_PROPS = (  # first match wins; later modules would overwrite earlier ones
    ('ParticleModuleColorScaleOverLife', 'AlphaScaleOverLife'),
    ('ParticleModuleColorOverLife', 'AlphaOverLife'),
    ('ParticleModuleColor', 'StartAlpha'),
    ('ParticleModuleColor_Seeded', 'StartAlpha'),
)
CURVE_FLOATS = ('Constant', 'Min', 'Max', 'MinOutput', 'MaxOutput', 'OutVal', 'ArriveTangent', 'LeaveTangent')


def _lod_groups(asset):
    """[(lod_export_index, [module export indices])] for every emitter LOD level."""
    def obj(prop):
        return struct.unpack_from('<i', asset.ux, prop.vpos)[0]

    def arr(prop):
        n = struct.unpack_from('<i', asset.ux, prop.vpos)[0]
        if n < 0 or 4 + n * 4 > prop.size:
            return ()
        return struct.unpack_from(f'<{n}i', asset.ux, prop.vpos + 4)

    groups = []
    for ei, e in enumerate(asset.exports):
        if not e['class'].endswith('Emitter'):
            continue
        levels = next((p for p in asset.export_props(ei) if p.name == 'LODLevels'), None)
        for idx in (arr(levels) if levels else ()):
            if idx <= 0:
                continue
            lp = {p.name: p for p in asset.export_props(idx - 1)}
            mods = [m for m in (arr(lp['Modules']) if 'Modules' in lp else ())]
            for key in ('RequiredModule', 'SpawnModule', 'TypeDataModule'):
                if key in lp:
                    mods.append(obj(lp[key]))
            groups.append((idx - 1, sorted({m - 1 for m in mods if m > 0})))
    return groups


def apply_amount(asset, buf, percent, include=None, touched=None):
    """Scale spawn settings; include(export_index) limits it to some emitters.

    Returns the number of values changed; touched (a set) receives (offset, length)
    of every edited value for the cosmetic-only safety check.
    """
    value = float(percent)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('Effect amount must be between 0 and 100.')
    if value == 100:
        return 0
    factor = value / 100
    edits = set()
    flags = set()  # 1-byte bool edits
    curve_objects = {}  # Distribution export -> factor (the runtime may evaluate it instead of the LUT)

    def ok(i):
        return include is None or include(i)

    def scale(pos, k, fmt='<f'):
        if pos in edits:
            return None
        old = struct.unpack_from(fmt, asset.ux, pos)[0]
        if old < 0 or not math.isfinite(old):
            return None
        struct.pack_into(fmt, buf, pos, old * k)
        edits.add(pos)
        return old

    def distribution(prop, k):
        """Scale a RawDistributionFloat; returns the largest original value seen."""
        peak = 0.0
        for p in prop.children or []:
            if p.name in ('MinValue', 'MaxValue') and p.type == 'FloatProperty':
                old = scale(p.vpos, k)
                peak = max(peak, old or 0.0)
            elif p.name == 'Distribution' and p.type == 'ObjectProperty':
                idx = struct.unpack_from('<i', asset.ux, p.vpos)[0]
                if idx > 0:
                    curve_objects[idx - 1] = k
            elif p.name == 'Table':
                for v in p.children or []:
                    if v.name == 'Values' and v.inner == 'FloatProperty':
                        count = struct.unpack_from('<i', asset.ux, v.vpos)[0]
                        if count < 0 or 4 + count * 4 > v.size:
                            raise ValueError('Invalid lookup table')
                        for j in range(count):
                            old = scale(v.vpos + 4 + j * 4, k)
                            peak = max(peak, old or 0.0)
        return peak

    def burst_count(pos):
        """Integer burst count: never rounds a visible burst away above 0 %."""
        old = struct.unpack_from('<i', asset.ux, pos)[0]
        if old <= 0 or pos in edits:
            return (old, old) if old > 0 else (0, 0)
        new = 0 if factor == 0 else max(1, int(math.floor(old * factor + .5)))
        struct.pack_into('<i', buf, pos, new)
        edits.add(pos)
        return old, new

    def fade(group, k):
        """Multiply an emitter's opacity by k (used when its count cannot shrink further)."""
        props = {i: {p.name: p for p in asset.export_props(i)} for i in group}
        for cls, name in ALPHA_PROPS:
            for i in group:
                if asset.exports[i]['class'] == cls and name in props[i]:
                    distribution(props[i][name], k)
                    return True
        for i in group:  # GPU sprites: alpha = A * ColorScale.w + ColorBias.w
            if asset.exports[i]['class'] == 'ParticleModuleTypeDataGpu' and 'ResourceData' in props[i]:
                for c in props[i]['ResourceData'].children or []:
                    if c.name in ('ColorScale', 'ColorBias'):
                        scale(c.vpos + 12, k)
                return True
        return False

    for lod, group in _lod_groups(asset):
        if not ok(lod):
            continue
        wanted = got = 0.0
        has_rate = False
        for i in group:
            cls = asset.exports[i]['class']
            if cls == 'ParticleModuleSpawn':
                for p in asset.export_props(i):
                    if p.name == 'Rate' and p.sname == 'RawDistributionFloat':
                        has_rate |= distribution(p, factor) > 0
                    elif p.name == 'BurstList':
                        for burst in p.children or []:
                            for c in burst.children or []:
                                if c.name in ('Count', 'CountLow') and c.type == 'IntProperty':
                                    old, new = burst_count(c.vpos)
                                    if c.name == 'Count':
                                        wanted += old * factor
                                        got += new
            elif cls == 'ParticleModuleSpawnPerUnit':
                for p in asset.export_props(i):
                    if p.name == 'SpawnPerUnit' and p.sname == 'RawDistributionFloat':
                        has_rate |= distribution(p, factor) > 0
            elif cls == 'ParticleModuleRequired':
                for p in asset.export_props(i):
                    if p.name == 'SpawnRate' and p.sname == 'RawDistributionFloat':
                        has_rate |= distribution(p, factor) > 0
        if factor == 0:
            for p in asset.export_props(lod):
                if p.name == 'bEnabled' and p.type == 'BoolProperty':
                    buf[p.bool_pos] = 0
                    edits.add(p.bool_pos)
                    flags.add(p.bool_pos)
        elif got > wanted + 1e-6 and not has_rate:
            fade(group, wanted / got)

    def walk(props, k):
        for p in props:
            if p.type == 'FloatProperty' and p.name in CURVE_FLOATS:
                scale(p.vpos, k)
            if p.children:
                walk(p.children, k)
    for i, k in curve_objects.items():
        if asset.exports[i]['class'].startswith('DistributionFloat'):
            walk(asset.export_props(i), k)
    if touched is not None:
        touched.update((pos, 1 if pos in flags else 4) for pos in edits)
    return len(edits)
