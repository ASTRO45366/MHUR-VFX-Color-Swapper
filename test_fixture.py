"""Optional local game cache for integration tests. Never ship or modify it."""
import json
import os
import shutil
import tempfile
from pathlib import Path

from core.engine import Engine
from core.game_update import read_manifest


def open_test_engine(case):
    assets = Path(os.environ.get('MHUR_VFX_TEST_DATA', Path(__file__).parent)).resolve()
    temporary = tempfile.TemporaryDirectory(prefix='mhur-tests-')
    case.addClassCleanup(temporary.cleanup)
    base = Path(temporary.name)
    manifest, generation = read_manifest(assets)
    if generation:
        shutil.copytree(generation, base / 'game-updates' / 'fixture')
        (base / 'game-update.json').write_text(json.dumps(dict(manifest, generation='fixture')), encoding='utf-8')
    engine = Engine(base, assets / 'library.zip')
    engine.bundled_portraits = assets / 'portraits'
    engine.load()

    def close():
        for reader in (engine.lib, engine.lib._update_reader):
            if reader and reader.archive:
                reader.archive.close()

    case.addClassCleanup(close)
    return engine
