"""Identify named emitters and the modules/materials they actually use."""
import struct


def emitter_parts(asset, classify):
    modules, materials = {}, {}

    def object_index(prop):
        return struct.unpack_from('<i', asset.ux, prop.vpos)[0]

    def array_indices(prop):
        n = struct.unpack_from('<i', asset.ux, prop.vpos)[0]
        if n < 0 or 4 + n * 4 > prop.size:
            return []
        return struct.unpack_from(f'<{n}i', asset.ux, prop.vpos + 4)

    for ei, e in enumerate(asset.exports):
        if not e['class'].endswith('Emitter'):
            continue
        props = {p.name: p for p in asset.export_props(ei)}
        emitter = props.get('EmitterName')
        name = asset.fname(asset.ux, emitter.vpos) if emitter else e['name']
        levels = props.get('LODLevels')
        if not levels:
            continue
        for idx in array_indices(levels):
            if idx <= 0:
                continue
            lp = {p.name: p for p in asset.export_props(idx - 1)}
            required = lp.get('RequiredModule')
            matpath = None
            if required and object_index(required) > 0:
                rp = asset.export_props(object_index(required) - 1)
                mat = next((p for p in rp if p.name == 'Material'), None)
                matpath = asset.object_path(object_index(mat)) if mat else None
            part = classify(name)
            if part == 'main' and matpath:
                part = classify(matpath.rsplit('/', 1)[-1])
            if matpath:
                materials.setdefault(matpath, set()).add(part)
            indices = list(array_indices(lp['Modules'])) if 'Modules' in lp else []
            for key in ('RequiredModule', 'SpawnModule', 'TypeDataModule'):
                if key in lp:
                    indices.append(object_index(lp[key]))
            for module in indices:
                if module > 0:
                    modules.setdefault(module - 1, set()).add(part)
    return modules, materials
