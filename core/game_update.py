"""Read installed game PAKs, discover complete characters, and stage small updates.

Only original base/patch PAKs are opened. Extraction, image conversion and saved
updates stay in this app's data folder. The installed game is never written to.
"""
import hashlib
import json
import lzma
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

from .library import KEEP_PREFIX, Library, is_effect_asset

DEFAULT_AES = '0x332F41B1130F125444A35F420EC6D05EA3E27A972A36DAD90C83FC6958D941C7'
BASE_PAK = re.compile(r'^(?:HerovsGame|pakchunk\d+)-WindowsNoEditor(?:_\d+_P)?\.pak$', re.I)
STALL_SECONDS = 600


class UpdateCancelled(ValueError):
    def __init__(self):
        super().__init__('Game update cancelled. The previous library was kept.')


_GLOBS = {}


def glob_match(pattern, name):
    """repak-style include glob ('*' within a folder, '**/' across folders)."""
    rx = _GLOBS.get(pattern)
    if rx is None:
        out, i = [], 0
        while i < len(pattern):
            if pattern.startswith('**/', i):
                out.append('(?:.*/)?')
                i += 3
            elif pattern[i] == '*':
                out.append('[^/]*')
                i += 1
            else:
                out.append(re.escape(pattern[i]))
                i += 1
        rx = _GLOBS[pattern] = re.compile(''.join(out) + '$')
    return bool(rx.match(name))


def run_tool(args, cwd, label, secret='', cancel=None, watch=None, stall=None):
    """Run a bundled reader; watch() -> progress count (resets the stall timer when it grows).

    Output goes to a file (a pipe can fill up and block the reader), the user can
    cancel, and a reader that stops making progress is stopped instead of leaving
    the app on a loading screen forever.
    """
    stall = stall or STALL_SECONDS
    cancel = cancel or (lambda: False)
    log = Path(cwd) / f'reader-{uuid.uuid4().hex[:6]}.log'
    with log.open('wb') as out:
        proc = subprocess.Popen([str(a) for a in args], cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        last_seen, last_change = None, time.time()
        try:
            while proc.poll() is None:
                time.sleep(0.4)
                if cancel():
                    raise UpdateCancelled()
                seen = watch() if watch else log.stat().st_size
                if seen != last_seen:
                    last_seen, last_change = seen, time.time()
                elif time.time() - last_change > stall:
                    raise ValueError(f'{label} stopped responding (no progress for {max(1, stall // 60)} minutes). '
                                     'Close the game if it is updating, then try again. The previous library was kept.')
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
    output = log.read_bytes().decode('utf-8', 'replace')
    log.unlink(missing_ok=True)
    if proc.returncode:
        message = output[-1500:].replace(secret, '<game key>') if secret else output[-1500:]
        raise ValueError(f'{label} failed. Check the game path and key, or update the reader if the game format changed.\n{message}')
    return output


def normalize_key(aes_key):
    key = str(aes_key or DEFAULT_AES).strip()
    if not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{64}', key):
        raise ValueError('The game key must contain 64 hexadecimal digits.')
    return key if key.startswith('0x') else '0x' + key


CHAR_PATH = re.compile(r'^(?:HerovsGame/Content|Game|Content)/Character/(Ch\d+)/(.+)$')


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.write-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_manifest(base):
    base = Path(base)
    try:
        data = json.loads((base / 'game-update.json').read_text(encoding='utf-8'))
        generation = (base / 'game-updates' / data['generation']).resolve()
        root = (base / 'game-updates').resolve()
        if (not generation.is_relative_to(root) or generation == root
                or not (generation / 'library.zip').is_file()
                or not isinstance(data['characters'], list) or not data['characters']
                or any(not re.fullmatch(r'Ch\d+', cid) for cid in data['characters'])):
            raise ValueError('Invalid update manifest')
        return data, generation
    except (OSError, ValueError, KeyError, TypeError):
        return {}, None


def library_base_id(path):
    """An old delta cache must never be reused without its original base."""
    if not path.is_file():
        return 'local-only'
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def game_folder(value):
    path = Path(str(value).strip().strip('"'))
    if not str(value).strip():
        raise ValueError('Choose the installed game folder or its Content/Paks folder.')
    for candidate in (path, path / 'HerovsGame/Content/Paks', path / 'Content/Paks', path / 'Paks'):
        if candidate.is_dir() and any(p.is_file() and BASE_PAK.fullmatch(p.name) for p in candidate.iterdir()):
            return candidate.resolve()
    raise ValueError('No original MHUR game PAK was found in that folder.')


def detect_game_folder():
    roots = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
            roots.append(Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
    except (ImportError, OSError):
        pass
    for drive in 'CDEFB':
        roots.extend(Path(drive + ':/') / name for name in ('SteamLibrary', 'Program Files (x86)/Steam', 'Steam'))
    for root in list(roots):
        try:
            text = (root / 'steamapps/libraryfolders.vdf').read_text(encoding='utf-8')
            roots.extend(Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s*"([^"]+)"', text))
        except OSError:
            pass
    for root in roots:
        path = root / 'steamapps/common/My Hero Ultra Rumble/HerovsGame/Content/Paks'
        if path.is_dir():
            return str(path)
    return ''


def original_paks(folder):
    folder = game_folder(folder)
    return sorted((p for p in folder.iterdir() if p.is_file() and BASE_PAK.fullmatch(p.name)),
                  key=lambda p: ('_P.' in p.name, [int(n) for n in re.findall(r'\d+', p.name)], p.name))


def fingerprint(paks):
    data = [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in paks]
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def discover(entries):
    """Require pawn registration, default blueprint, costume portrait and particles.

    NPC face icons and preloaded parameter tables alone do not qualify.
    Names are deliberately not used as a hardcoded whitelist for future IDs.
    """
    flags = defaultdict(set)
    images = defaultdict(list)
    assets = {}
    for name, pak in entries.items():
        match = CHAR_PATH.fullmatch(name)
        if not match:
            continue
        cid, relative = match.groups()
        stem = PurePosixPath(name).stem
        if name.endswith('.uasset'):
            if stem == f'PA_{cid}':
                flags[cid].add('pawn')
            if stem == f'BP_{cid}Default':
                flags[cid].add('blueprint')
            if stem.startswith('PS_'):
                flags[cid].add('particles')
            if '/GUI/Costume/L/' in name and re.fullmatch(r'T_ui_Thumb_4_\d+_L', stem):
                images[cid].append(name)
                flags[cid].add('portrait')
            if stem.startswith(KEEP_PREFIX):
                assets[name] = pak
    active = sorted(cid for cid, markers in flags.items()
                    if markers >= {'pawn', 'blueprint', 'particles', 'portrait'})
    portraits = {}
    for cid in active:
        default = f'T_ui_Thumb_4_{int(cid[2:]) * 1000000}_L'
        portraits[cid] = min(images[cid], key=lambda n: (PurePosixPath(n).stem != default, n))
    assets = {n: p for n, p in assets.items()
              if not PurePosixPath(n).stem.startswith('PS_') or CHAR_PATH.fullmatch(n)[1] in active}
    return active, assets, portraits


def write_bundle(target, records):
    """Lossless LZMA blocks with random access, compatible with the built-in library."""
    members, catalog = {}, []
    groups = defaultdict(list)
    for r in records:
        catalog.append(Library.record_data(r))
        relative = r.pkg.replace('/Game/', '', 1)
        groups[r.char].extend(((relative + '.uasset', r.ua), (relative + '.uexp', r.ux)))
    with zipfile.ZipFile(target, 'w') as archive:
        block_number = 0
        for cid, files in sorted(groups.items()):
            payload, pending = bytearray(), []

            def flush():
                nonlocal payload, pending, block_number
                if not pending:
                    return
                block = f'blocks/{cid}-{block_number}.xz'
                archive.writestr(block, lzma.compress(payload, preset=6))
                for name, offset, size in pending:
                    members[name] = [block, offset, size]
                payload, pending = bytearray(), []
                block_number += 1

            for name, path in sorted(files, key=lambda pair: (PurePosixPath(pair[0]).suffix, pair[0])):
                data = path.read_bytes()
                if payload and len(payload) + len(data) > 16 * 1024 * 1024:
                    flush()
                pending.append((name, len(payload), len(data)))
                payload.extend(data)
            flush()
        archive.writestr('catalog.json', json.dumps({'format': 2, 'records': catalog, 'members': members},
                         separators=(',', ':')), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


class GameUpdater:
    def __init__(self, engine, tools):
        self.engine, self.tools = engine, Path(tools)

    def run(self, folder, aes_key='', progress=None, force=False, cancel=None):
        engine = self.engine
        progress = progress or (lambda *args: None)
        cancel = cancel or (lambda: False)
        folder = game_folder(folder)
        paks = original_paks(folder)
        stamp = fingerprint(paks)
        previous, _ = read_manifest(engine.base)
        base_id = library_base_id(engine.lib.archive_path)
        if (previous.get('fingerprint') == stamp and previous.get('library_base') == base_id
                and not force):
            return dict(cached=True, characters=len(previous['characters']), added=[], changed_assets=0,
                        text='Your installed game files are already current.')
        key = normalize_key(aes_key)
        for name in ('repak.exe', 'umodel.exe', 'SDL2.dll'):
            if not (self.tools / name).is_file():
                raise ValueError('A bundled game reader is missing. Extract a fresh copy of the app.')
        root = engine.base / 'game-updates'
        root.mkdir(exist_ok=True)
        generation_name = 'game-' + uuid.uuid4().hex[:12]
        generation = root / generation_name
        generation.mkdir()

        def run(args, cwd, label, watch=None, stall=STALL_SECONDS):
            return run_tool(args, cwd, label, key, cancel, watch, stall)

        manifest_path = engine.base / 'game-update.json'
        old_manifest = manifest_path.read_bytes() if manifest_path.is_file() else None
        committed = False
        try:
            with tempfile.TemporaryDirectory(prefix='read-', dir=root) as temporary:
                work = Path(temporary)
                entries = {}
                for i, pak in enumerate(paks):
                    progress(f'Reading game archive index {i + 1} of {len(paks)}…', i, len(paks))
                    output = run([self.tools / 'repak.exe', '-a', key, 'list', pak], work, 'Game index')
                    for line in output.splitlines():
                        name = line.strip().replace('\\', '/')
                        path = PurePosixPath(name)
                        if path.is_absolute() or '..' in path.parts:
                            raise ValueError('Unsafe path in game archive; previous assets were kept.')
                        if CHAR_PATH.fullmatch(name):
                            entries[name] = pak
                active, assets, pictures = discover(entries)
                if not active:
                    raise ValueError('No complete playable character data was found. The previous roster was kept.')
                requests = defaultdict(set)
                # A few filename globs avoid an expensive index scan for hundreds
                # of literal directories and exclude meshes/textures/animations.
                for prefix in ('HerovsGame/Content', 'Game', 'Content'):
                    if any(name.startswith(prefix + '/Character/') for name in entries):
                        for pak in paks:
                            for asset_prefix in KEEP_PREFIX:
                                requests[pak].add(f'{prefix}/Character/Ch*/**/{asset_prefix}*')
                            requests[pak].add(f'{prefix}/Character/Ch*/GUI/Costume/L/T_ui_Thumb_4_*000000_L.*')
                for name in pictures.values():
                    if re.fullmatch(r'T_ui_Thumb_4_\d+000000_L', PurePosixPath(name).stem):
                        continue
                    for ext in ('.uasset', '.uexp', '.ubulk'):
                        part = name[:-7] + ext
                        if part in entries:
                            requests[entries[part]].add(part)
                raw = work / 'raw'
                raw.mkdir()
                expected = sum(1 for name, pak in entries.items() if any(
                    glob_match(pattern, name) for pattern in requests[pak]))
                started = time.time()

                def extracted():
                    return sum(len(f) for _, _, f in os.walk(raw))

                def show(i):
                    done = extracted()
                    secs = int(time.time() - started)
                    total = max(expected, done, 1)
                    progress(f'Extracting effect files from the game: {done:,} of ~{total:,} '
                             f'({secs // 60}:{secs % 60:02d}). The first update can take several minutes.', done, total)
                    return done
                for i, pak in enumerate(paks):
                    includes = sorted(requests[pak])
                    batch, budget = [], 0
                    batches = []
                    for item in includes:
                        if budget + len(item) > 18000:
                            batches.append(batch)
                            batch, budget = [], 0
                        batch.append(item)
                        budget += len(item) + 8
                    if batch:
                        batches.append(batch)
                    for j, batch in enumerate(batches):
                        show(i)
                        args = [self.tools / 'repak.exe', '-a', key, 'unpack', pak, '-o', raw, '-q', '-f']
                        for item in batch:
                            args.extend(('-i', item))
                        run(args, work, 'Selective game extraction', watch=lambda: show(i))
                progress('Decoding character pictures…', 0, 1)
                image_stems = [PurePosixPath(p).stem for p in pictures.values()]
                image_output = work / 'pictures'
                args = [self.tools / 'umodel.exe', '-export', '-game=ue4.27', '-path=' + str(raw),
                        '-png', '-noanim', '-out=' + str(image_output)]
                args.extend('-pkg=' + stem for stem in image_stems)
                run(args, work, 'Character picture reader',
                    watch=lambda: sum(len(f) for _, _, f in os.walk(image_output)) if image_output.exists() else 0)
                image_dest = generation / 'portraits'
                image_dest.mkdir()
                for cid, path in pictures.items():
                    matches = list(image_output.rglob(PurePosixPath(path).stem + '.png'))
                    if not matches:
                        raise ValueError(f'Could not decode the portrait for {cid}; the previous roster was kept.')
                    shutil.copy2(matches[0], image_dest / (cid + '.png'))
                candidate = Library(work / '_parse')
                for i, name in enumerate(sorted(assets)):
                    ua = raw.joinpath(*PurePosixPath(name).parts)
                    ux = ua.with_suffix('.uexp')
                    if ua.is_file() and ux.is_file():
                        rec = candidate._parse(ua, ux)
                        if rec:
                            candidate.recs[rec.pkg] = rec
                    if i % 100 == 0:
                        progress('Checking updated effect assets…', i, len(assets))
                supported = {r.char for r in candidate.recs.values() if r.kind == 'ps'}
                if not set(active) <= supported:
                    raise ValueError('Some character effects use an unsupported asset format. The previous roster was kept.')
                keep = {pkg for pkg, r in candidate.recs.items() if r.kind == 'ps' and r.char in active}
                # every effect material of an active character, also ones the game spawns from
                # blueprints (decals, post-process overlays, gates) that no particle system references
                keep |= {pkg for pkg, r in candidate.recs.items()
                         if r.kind in ('mi', 'm') and r.char in active and is_effect_asset(pkg)}
                stack = list(keep)
                while stack:
                    for ref in candidate.recs[stack.pop()].refs:
                        if ref in candidate.recs and ref not in keep and \
                                is_effect_asset(ref):   # no body/outfit/prop materials
                            keep.add(ref)
                            stack.append(ref)
                baseline = Library(work / '_baseline', engine.lib.archive_path)
                baseline.scan()
                changed = []
                try:
                    for i, pkg in enumerate(sorted(keep)):
                        rec, original = candidate.recs[pkg], baseline.recs.get(pkg)
                        if original is None:
                            changed.append(rec)
                        else:
                            asset = baseline.read(original)
                            if rec.ua.read_bytes() != asset.ua or rec.ux.read_bytes() != asset.ux:
                                changed.append(rec)
                        if i % 100 == 0:
                            progress('Preparing the local effect library…', i, len(keep))
                finally:
                    if getattr(baseline, 'archive', None):
                        baseline.archive.close()
                progress('Compressing updated effects…', 0, 1)
                write_bundle(generation / 'library.zip', changed)
                if fingerprint(original_paks(folder)) != stamp:
                    raise ValueError('The game changed during this scan. Try again after its update finishes.')
                before = set(previous.get('characters', engine.active_ids))
                metadata = dict(generation=generation_name, characters=active, fingerprint=stamp,
                                library_base=base_id,
                                updated=time.strftime('%Y-%m-%d %H:%M:%S'), game_folder=str(folder),
                                changed_assets=len(changed))
                atomic_json(manifest_path, metadata)
                try:
                    engine.load()
                except Exception:
                    if old_manifest is None:
                        manifest_path.unlink(missing_ok=True)
                    else:
                        atomic_json(manifest_path, json.loads(old_manifest))
                    engine.load()
                    raise
                committed = True
                progress('Cleaning up temporary extracted files…', 0, 1)
                return dict(cached=False, characters=len(active), added=sorted(set(active) - before),
                            removed=sorted(before - set(active)), changed_assets=len(changed),
                            text='Character list, native portraits and effect assets were refreshed.')
        finally:
            if not committed:
                # Only this job's newly created generation can be removed.
                resolved = generation.resolve()
                if resolved.parent == root.resolve() and resolved.name == generation_name:
                    shutil.rmtree(resolved)
