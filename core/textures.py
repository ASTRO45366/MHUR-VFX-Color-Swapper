"""On-demand texture source for the optional solid-object recolor.

Textures are big, so they are not part of the effect library. When an export
needs some (ice, stone, cracks...), exactly those files are extracted from the
installed game with the bundled reader and kept in `texture-cache/` for next
time. Original game files are only read, never changed.
"""
import json
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from .game_update import fingerprint, normalize_key, original_paks, run_tool

PAK_PREFIXES = ('HerovsGame/Content', 'Game', 'Content')


class TextureStore:
    def __init__(self, base, tools, prefs_reader):
        self.root = Path(base) / 'texture-cache'
        self.tools = Path(tools)
        self.prefs = prefs_reader      # () -> dict with game_folder / game_aes

    # ---------------------------------------------------------------- paths
    @staticmethod
    def rel(pkg):
        """'/Game/Character/Ch004/Effect/Tex/T_x' -> 'Character/Ch004/Effect/Tex/T_x'."""
        return pkg.replace('/Game/', '', 1).lstrip('/')

    def _cached(self, pkg):
        base = self.root.joinpath(*PurePosixPath(self.rel(pkg)).parts)
        ua, ux, ub = (base.with_name(base.name + ext) for ext in ('.uasset', '.uexp', '.ubulk'))
        if ua.is_file() and ux.is_file():
            return ua.read_bytes(), ux.read_bytes(), ub.read_bytes() if ub.is_file() else b''
        return None

    def available(self):
        prefs = self.prefs()
        if not prefs.get('game_folder'):
            return False
        try:
            original_paks(prefs['game_folder'])
            return all((self.tools / n).is_file() for n in ('repak.exe',))
        except (OSError, ValueError):
            return False

    # ---------------------------------------------------------------- index
    def _index(self, paks, key, cancel):
        """{archive member name: pak path} for textures, rebuilt when the game changes."""
        stamp = fingerprint(paks)
        path = self.root / 'index.json'
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('fingerprint') == stamp:
                return {n: Path(p) for n, p in data['entries'].items()}
        except (OSError, ValueError, KeyError):
            pass
        entries = {}
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            for pak in paks:
                out = run_tool([self.tools / 'repak.exe', '-a', key, 'list', pak], tmp, 'Game index', key, cancel)
                for line in out.splitlines():
                    name = line.strip().replace('\\', '/')
                    stem = PurePosixPath(name).name
                    if '/Character/' in name and stem.startswith('T_') and '..' not in name:
                        entries[name] = pak
        path.write_text(json.dumps({'fingerprint': stamp, 'entries': {n: str(p) for n, p in entries.items()}}),
                        encoding='utf-8')
        return entries

    # ---------------------------------------------------------------- fetch
    def get(self, pkgs, progress=None, cancel=None):
        """{pkg: (uasset, uexp, ubulk)} for the requested textures; missing ones are left out."""
        progress = progress or (lambda *a: None)
        found, missing = {}, []
        for pkg in sorted(set(pkgs)):
            got = self._cached(pkg)
            if got:
                found[pkg] = got
            else:
                missing.append(pkg)
        if not self.available():
            return found
        prefs = self.prefs()
        paks = original_paks(prefs['game_folder'])
        stamp_file = self.root / 'game.json'
        stamp = fingerprint(paks)
        try:
            old = json.loads(stamp_file.read_text(encoding='utf-8')).get('fingerprint')
        except (OSError, ValueError):
            old = None
        if old is not None and old != stamp:
            # the game was updated: cached textures may be outdated
            shutil.rmtree(self.root, ignore_errors=True)
            found, missing = {}, sorted(set(pkgs))
        self.root.mkdir(parents=True, exist_ok=True)
        stamp_file.write_text(json.dumps({'fingerprint': stamp}), encoding='utf-8')
        if not missing:
            return found
        key = normalize_key(prefs.get('game_aes'))
        progress('Finding textures in the game files…', 0, 1)
        index = self._index(paks, key, cancel)
        wanted = {}
        for pkg in missing:
            rel = self.rel(pkg)
            for prefix in PAK_PREFIXES:
                name = f'{prefix}/{rel}.uasset'
                if name in index:
                    for ext in ('.uasset', '.uexp', '.ubulk'):
                        member = name[:-7] + ext
                        if member in index:
                            wanted.setdefault(index[member], []).append(member)
                    break
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=self.root) as tmp:
            raw = Path(tmp) / 'raw'
            raw.mkdir()
            for i, (pak, members) in enumerate(sorted(wanted.items())):
                for start in range(0, len(members), 150):
                    batch = members[start:start + 150]
                    progress(f'Reading {len(missing)} texture(s) from the game…', i, len(wanted))
                    args = [self.tools / 'repak.exe', '-a', key, 'unpack', pak, '-o', raw, '-q', '-f']
                    for m in batch:
                        args += ['-i', m]
                    run_tool(args, tmp, 'Texture extraction', key, cancel)
            for pkg in missing:
                rel = self.rel(pkg)
                for prefix in PAK_PREFIXES:
                    src = raw.joinpath(*PurePosixPath(f'{prefix}/{rel}').parts)
                    if src.with_name(src.name + '.uasset').is_file():
                        dest = self.root.joinpath(*PurePosixPath(rel).parts)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        for ext in ('.uasset', '.uexp', '.ubulk'):
                            f = src.with_name(src.name + ext)
                            if f.is_file():
                                shutil.move(str(f), str(dest.with_name(dest.name + ext)))
                        break
                got = self._cached(pkg)
                if got:
                    found[pkg] = got
        return found
