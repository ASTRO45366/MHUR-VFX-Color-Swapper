"""Build a compressed library of supported particles and their material graph.

Usage: python compact_library.py PATH_TO_ORIGINAL_LIBRARY library.zip
Never deletes source files. Textures, meshes and animations stay in the game.
"""
import json
import sys
import zipfile
from pathlib import Path
from core.library import KEEP_PREFIX, Library


def compact(source, target):
    lib = Library(source)
    paths = sorted(f for f in lib.root.rglob('*.uasset')
                   if f.stem.startswith(KEEP_PREFIX))
    for i, ua in enumerate(paths):
        ux = ua.with_suffix('.uexp')
        if ux.is_file():
            r = lib._parse(ua, ux)
            if r:
                lib.recs[r.pkg] = r
        if i % 500 == 0:
            print(f'Parsed {i}/{len(paths)}', flush=True)
    keep = {p for p, r in lib.recs.items() if r.kind == 'ps'}
    stack = list(keep)
    while stack:
        for ref in lib.recs[stack.pop()].refs:
            if ref in lib.recs and ref not in keep:
                keep.add(ref)
                stack.append(ref)
    catalog = []
    raw = 0
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for pkg in sorted(keep):
            r = lib.recs[pkg]
            rel = pkg.replace('/Game/', '', 1)
            for ext, path in (('.uasset', r.ua), ('.uexp', r.ux)):
                data = path.read_bytes()
                raw += len(data)
                archive.writestr(rel + ext, data)
            catalog.append(lib.record_data(r))
        archive.writestr('catalog.json', json.dumps(catalog))
    report = {'particles': sum(r.kind == 'ps' for p, r in lib.recs.items() if p in keep),
              'materials': sum(r.kind != 'ps' for p, r in lib.recs.items() if p in keep),
              'supported_records': len(lib.recs), 'kept_records': len(keep),
              'raw_bytes': raw, 'zip_bytes': Path(target).stat().st_size}
    print(json.dumps(report, indent=2))
    Path(target).with_suffix('.report.json').write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    compact(Path(sys.argv[1]), Path(sys.argv[2]))
