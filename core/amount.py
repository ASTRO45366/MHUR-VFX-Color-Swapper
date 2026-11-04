"""Patch existing Cascade spawn settings without resizing cooked exports."""
import math
import struct


def apply_amount(asset, buf, percent):
    value = float(percent)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('Effect amount must be between 0 and 100.')
    if value == 100:
        return 0
    factor = value / 100
    edits = set()
    distributions = set()

    def scale(pos, integer=False):
        if pos in edits:
            return
        fmt = '<i' if integer else '<f'
        old = struct.unpack_from(fmt, asset.ux, pos)[0]
        if old < 0 or not math.isfinite(old):
            return
        new = int(math.floor(old * factor + .5)) if integer else old * factor
        struct.pack_into(fmt, buf, pos, new)
        edits.add(pos)

    def distribution(prop):
        for p in prop.children or []:
            if p.name in ('MinValue', 'MaxValue') and p.type == 'FloatProperty':
                scale(p.vpos)
            elif p.name == 'Distribution' and p.type == 'ObjectProperty':
                idx = struct.unpack_from('<i', asset.ux, p.vpos)[0]
                if idx > 0:
                    distributions.add(idx - 1)
            elif p.name == 'Table':
                for v in p.children or []:
                    if v.name == 'Values' and v.inner == 'FloatProperty':
                        count = struct.unpack_from('<i', asset.ux, v.vpos)[0]
                        if count < 0 or 4 + count * 4 > v.size:
                            raise ValueError('Invalid spawn lookup table')
                        for j in range(count):
                            scale(v.vpos + 4 + j * 4)

    for i, e in enumerate(asset.exports):
        if e['class'] == 'ParticleModuleSpawn':
            for p in asset.export_props(i):
                if p.name == 'Rate' and p.sname == 'RawDistributionFloat':
                    distribution(p)
                elif p.name == 'BurstList':
                    for burst in p.children or []:
                        for c in burst.children or []:
                            if c.name in ('Count', 'CountLow') and c.type == 'IntProperty':
                                scale(c.vpos, True)
        elif e['class'] == 'ParticleModuleSpawnPerUnit':
            for p in asset.export_props(i):
                if p.name == 'SpawnPerUnit' and p.sname == 'RawDistributionFloat':
                    distribution(p)
        elif e['class'] == 'ParticleModuleRequired':
            for p in asset.export_props(i):
                if p.name == 'SpawnRate' and p.sname == 'RawDistributionFloat':
                    distribution(p)
        elif value == 0 and e['class'] == 'ParticleLODLevel':
            for p in asset.export_props(i):
                if p.name == 'bEnabled' and p.type == 'BoolProperty':
                    buf[p.bool_pos] = 0
                    edits.add(p.bool_pos)

    # The runtime can evaluate a Distribution object instead of its cooked LUT.
    def walk(props):
        for p in props:
            if p.type == 'FloatProperty' and p.name in (
                    'Constant', 'Min', 'Max', 'MinOutput', 'MaxOutput',
                    'OutVal', 'ArriveTangent', 'LeaveTangent'):
                scale(p.vpos)
            if p.children:
                walk(p.children)
    for i in distributions:
        if asset.exports[i]['class'].startswith('DistributionFloat'):
            walk(asset.export_props(i))
    return len(edits)
