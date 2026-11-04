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
DATA = Path(sys.executable).parent if getattr(sys, 'frozen', False) else BASE
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true', help='Run local server without opening a window')
    parser.add_argument('--port', type=int, default=0, help='Local HTTP port (default: choose a free port)')
    parser.add_argument('--data-dir', type=Path, default=DATA, help='Optional folder for exports, imports and settings')
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
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
            if app.last_ping and time.time() - app.last_ping > 25:
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
        try:
            (DATA / 'startup-error.log').write_text(details, encoding='utf-8')
        except OSError:
            pass
        if sys.stderr:
            sys.stderr.write(details)
        if sys.platform.startswith('win') and '--no-browser' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                'The app could not start. Put the EXE in a writable folder and try again.\n'
                'Details are in startup-error.log beside the EXE.', 'VFX Color Swapper', 0x10)
        sys.exit(1)
