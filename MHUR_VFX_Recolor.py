#!/usr/bin/env python3
"""MHUR VFX Color Swapper - launcher.  Run:  python MHUR_VFX_Recolor.py"""
import os
import argparse
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
import traceback
from pathlib import Path

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).parent if getattr(sys, 'frozen', False) else BASE
DATA_FOLDER = 'MHUR VFX Swapper Data'
# Everything the app writes (exports, settings, game data, caches, logs) lives in
# one folder beside the EXE instead of cluttering the EXE's folder.
DATA = APP_DIR / DATA_FOLDER
LEGACY_ITEMS = ('settings.json', 'characters.json', 'game-update.json', 'game-updates', 'library',
                'library.zip', 'portraits', 'exports', 'cache', 'logs', 'startup-error.log')
# Without a ping for this long the window is considered gone. Browsers throttle
# timers in hidden/minimised windows (about one per minute after 5 minutes), so
# this must be generous; closing the window normally is reported right away.
PING_TIMEOUT = 15 * 60
CLOSE_GRACE = 8
sys.path.insert(0, str(BASE))

from server import App, serve  # noqa: E402


def open_window(url):
    """Open as a chrome-less app window when Edge/Chrome is present, else default browser."""
    cands = []
    if sys.platform.startswith('win'):
        for env in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
            root = os.environ.get(env)
            if root:
                cands += [Path(root) / 'Microsoft/Edge/Application/msedge.exe',
                          Path(root) / 'Google/Chrome/Application/chrome.exe']
    else:
        cands = [Path(p) for p in (shutil.which('google-chrome'), shutil.which('chromium'),
                                   shutil.which('chromium-browser'), shutil.which('microsoft-edge')) if p]
    for exe in cands:
        if exe.exists():
            try:
                subprocess.Popen([str(exe), f'--app={url}', '--window-size=1400,900'])
                return
            except Exception:
                pass
    webbrowser.open(url)


def prepare_data_dir(data):
    """Create the data folder and move files an older version left beside the EXE."""
    data.mkdir(parents=True, exist_ok=True)
    if data.parent != APP_DIR or not getattr(sys, 'frozen', False):
        return
    for name in LEGACY_ITEMS:
        old, new = APP_DIR / name, data / name
        if old.exists() and not new.exists():
            try:
                shutil.move(str(old), str(new))
            except OSError:
                pass  # in use / read-only: the app still works, the old copy stays


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='Run local server without opening a window')
    parser.add_argument('--port', type=int, default=0, help='Local HTTP port (default: choose a free port)')
    parser.add_argument('--data-dir', type=Path, default=DATA, help='Optional folder for exports, imports and settings')
    args = parser.parse_args()
    prepare_data_dir(args.data_dir)
    external = args.data_dir / 'library.zip'
    bundle = external if external.is_file() else BASE / 'library.zip'
    app = App(args.data_dir, BASE / 'web', bundle)
    srv = serve(app, args.port)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=app.initialize, daemon=True).start()
    url = f'http://127.0.0.1:{port}/'
    if sys.stdout:
        print(f'MHUR VFX Color Swapper running at {url}\nClose the window to quit (or press Ctrl+C).', flush=True)
    if not args.no_browser:
        open_window(url)
    try:
        while True:
            time.sleep(1)
            # Let a local import/export finish if the window closes mid-job.
            if app.initializing or app.has_running_jobs():
                continue
            if app.closed_at and time.time() - app.closed_at > CLOSE_GRACE and \
                    (not app.last_ping or app.last_ping < app.closed_at):
                break   # window was closed (and not just reloaded)
            if app.last_ping and time.time() - app.last_ping > PING_TIMEOUT:
                break
            if not app.last_ping and time.time() - app.started > 120:
                break
    except KeyboardInterrupt:
        pass
    srv.shutdown()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        details = traceback.format_exc()
        for folder in (DATA, APP_DIR):
            try:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / 'startup-error.log').write_text(details, encoding='utf-8')
                break
            except OSError:
                continue
        if sys.stderr:
            sys.stderr.write(details)
        if sys.platform.startswith('win') and '--no-browser' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                'The app could not start. Put the EXE in a writable folder and try again.\n'
                f'Details are in "{DATA_FOLDER}\\startup-error.log" beside the EXE.', 'VFX Color Swapper', 0x10)
        sys.exit(1)
