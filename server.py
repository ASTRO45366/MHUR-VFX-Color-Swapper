"""Tiny local web server that powers the UI (stdlib only)."""
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from core.engine import Engine
from preferences import Preferences
from core.game_update import GameUpdater, detect_game_folder, read_manifest, game_folder, original_paks, fingerprint, library_base_id


class App:
    def __init__(self, base, web=None, bundle=None):
        self.base = Path(base)
        self.web = Path(web) if web else self.base / 'web'
        self.engine = Engine(base, bundle)
        self.preferences = Preferences(base)
        self.engine.bundled_portraits = self.web.parent / 'portraits'
        self.tools = self.web.parent / 'tools'
        self.game_status = {'state': 'idle', 'text': ''}
        self.initializing = False
        self.jobs = {}
        self.last_ping = None
        self.started = time.time()

    def initialize(self):
        self.initializing = True
        try:
            self.engine.load()
            prefs = self.preferences.read()
            if prefs['auto_game_update'] and prefs['game_folder']:
                try:
                    self.refresh_game(prefs)
                except Exception:
                    # A bad path/key/new format must not prevent using the prior library.
                    pass
        finally:
            self.initializing = False

    def refresh_game(self, prefs, job=None, force=False):
        with self.engine._lock:
            self.game_status = {'state': 'busy', 'text': 'Reading installed game files…'}
            def progress(text, done, total):
                self.engine.status = {'state': 'busy', 'text': text, 'done': done, 'total': max(total, 1)}
                if job is not None:
                    job.update(text=text, done=done, total=max(total, 1))
            try:
                result = GameUpdater(self.engine, self.tools).run(prefs['game_folder'], prefs['game_aes'], progress, force)
                self.game_status = {'state': 'ready', 'text': result['text']}
                return result
            except Exception as exc:
                self.game_status = {'state': 'error', 'text': str(exc)}
                raise
            finally:
                if self.engine.lib.scanned:
                    self.engine.status = {'state': 'ready', 'text': '', 'done': 1, 'total': 1}

    def update_info(self):
        manifest, _ = read_manifest(self.base)
        if manifest and manifest.get('library_base') != library_base_id(self.engine.lib.archive_path):
            manifest = {}
        prefs = self.preferences.read()
        folder = prefs['game_folder'] or detect_game_folder()
        changed = None
        try:
            if prefs['game_folder'] and manifest:
                changed = fingerprint(original_paks(folder)) != manifest['fingerprint']
        except (OSError, ValueError):
            pass
        return dict(self.game_status, detected_folder=folder, last_update=manifest.get('updated'),
                    characters=len(manifest.get('characters', [])), changed=changed)

    def job(self, fn):
        jid = uuid.uuid4().hex[:8]
        self.jobs[jid] = {'state': 'running', 'done': 0, 'total': 1, 'text': ''}

        def run():
            try:
                self.jobs[jid]['result'] = fn(self.jobs[jid])
                self.jobs[jid]['state'] = 'done'
            except Exception as e:
                traceback.print_exc()
                self.jobs[jid].update(state='error', error=str(e))
        threading.Thread(target=run, daemon=True).start()
        return jid

    def has_running_jobs(self):
        return any(job['state'] == 'running' for job in tuple(self.jobs.values()))


def make_handler(app: App):
    web = app.web
    eng = app.engine

    class H(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype='application/json', extra=None):
            if not isinstance(body, (bytes, bytearray)):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path, download=False):
            if not path.is_file():
                return self._send(404, {'error': 'not found'})
            ctype = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
            extra = {'Content-Disposition': f'attachment; filename="{path.name}"'} if download else None
            self._send(200, path.read_bytes(), ctype, extra)

        def _body(self):
            n = int(self.headers.get('Content-Length') or 0)
            return self.rfile.read(n) if n else b''

        def _local_request(self):
            expected = f'127.0.0.1:{self.server.server_address[1]}'
            origin = self.headers.get('Origin')
            if (self.headers.get('Host') != expected
                    or (origin is not None and origin != f'http://{expected}')
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.close_connection = True
                self._send(403, {'error': 'Only the local app can access this endpoint.'})
                return False
            return True

        def do_GET(self):
            if not self._local_request():
                return
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            p = unquote(u.path)
            try:
                if p == '/api/settings':
                    return self._send(200, app.preferences.read())
                if p == '/api/game/status':
                    return self._send(200, app.update_info())
                if p in ('/', '/index.html'):
                    return self._file(web / 'index.html')
                if p == '/favicon.ico':
                    icon = web / 'converter.ico'
                    return self._file(icon if icon.is_file() else web.parent / 'converter.ico')
                if p.startswith('/portraits/'):
                    cid = Path(p).stem
                    path = eng.portrait_path(cid) if cid.startswith('Ch') and cid[2:].isdigit() else None
                    return self._file(path) if path else self._send(404, {'error': 'portrait not found'})
                if p.startswith('/exports/'):
                    return self._file(eng.exports / Path(p).name, download=True)
                if p == '/api/ping':
                    app.last_ping = time.time()
                    return self._send(200, {'ok': True})
                if p == '/api/state':
                    status = eng.status
                    if app.initializing and status['state'] == 'ready':
                        status = {'state': 'busy', 'text': 'Checking installed game data…', 'done': 0, 'total': 1}
                    return self._send(200, {'status': status,
                                            'characters': eng.characters() if status['state'] == 'ready' else []})
                if p == '/api/groups':
                    return self._send(200, eng.groups(q['char'], q['var']))
                if p == '/api/parts':
                    return self._send(200, eng.parts_info())
                if p == '/api/job':
                    return self._send(200, app.jobs.get(q.get('id'), {'state': 'error', 'error': 'unknown job'}))
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {'error': str(e)})
            self._send(404, {'error': 'not found'})

        def do_POST(self):
            if not self._local_request():
                return
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            p = u.path
            try:
                data = self._body()
                if p == '/api/settings':
                    return self._send(200, app.preferences.update(json.loads(data)))
                if p == '/api/game/update':
                    req = json.loads(data)
                    prefs = app.preferences.read()
                    prefs.update({k: req[k] for k in ('game_folder', 'game_aes', 'auto_game_update') if k in req})
                    game_folder(prefs['game_folder'])
                    app.preferences.update(prefs)
                    return self._send(200, {'job': app.job(lambda job: app.refresh_game(prefs, job, bool(req.get('force'))))})
                if p == '/api/preview':
                    return self._send(200, {'palette': eng.preview(json.loads(data))})
                if p == '/api/export':
                    req = json.loads(data)

                    def run(job):
                        job['text'] = 'Building mod...'

                        def prog(i, n):
                            job.update(done=i, total=n)
                        out, rep = eng.build(req.get('assignments', []), req.get('name') or 'MHUR_VFX_Recolor', prog,
                                             req.get('global'), set(req.get('exclude', [])))
                        if out is None:
                            raise RuntimeError('Nothing changed. Colors and particle amount match the originals, or the selected assets have no supported fields.')
                        rep['url'] = '/exports/' + out.name
                        rep['path'] = str(out)
                        return rep
                    return self._send(200, {'job': app.job(run)})
                if p == '/api/import':
                    name = Path(q.get('name', 'import.zip')).name
                    tmp = Path(tempfile.mkdtemp()) / name
                    tmp.write_bytes(data)

                    def run(job):
                        job['text'] = 'Importing default assets...'
                        try:
                            return {'imported': eng.import_file(tmp)}
                        finally:
                            shutil.rmtree(tmp.parent)
                    return self._send(200, {'job': app.job(run)})
                if p == '/api/import_path':
                    src = json.loads(data)['path'].strip().strip('"')

                    def run(job):
                        job['text'] = 'Importing default assets...'
                        return {'imported': eng.import_file(src)}
                    return self._send(200, {'job': app.job(run)})
                if p == '/api/portrait':
                    cid = ''.join(c for c in q['char'] if c.isalnum())
                    ext = q.get('ext', 'png').lower()
                    if ext not in ('png', 'jpg', 'jpeg', 'webp'):
                        return self._send(400, {'error': 'unsupported image type'})
                    for e in ('png', 'jpg', 'jpeg', 'webp'):
                        f = eng.portraits / f'{cid}.{e}'
                        if f.exists():
                            f.unlink()
                    (eng.portraits / f'{cid}.{ext}').write_bytes(data)
                    return self._send(200, {'url': eng.portrait_url(cid)})
                if p == '/api/rename':
                    req = json.loads(data)
                    eng.names[req['char']] = req['name'].strip()[:40]
                    (app.base / 'characters.json').write_text(json.dumps(eng.names, indent=2), encoding='utf-8')
                    return self._send(200, {'ok': True})
                if p == '/api/open_exports':
                    d = str(eng.exports)
                    if sys.platform.startswith('win'):
                        os.startfile(d)  # noqa
                    elif sys.platform == 'darwin':
                        subprocess.Popen(['open', d])
                    else:
                        subprocess.Popen(['xdg-open', d])
                    return self._send(200, {'ok': True})
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, {'error': str(e)})
            except Exception as e:
                traceback.print_exc()
                return self._send(500, {'error': str(e)})
            self._send(404, {'error': 'not found'})

    return H


def serve(app, port=0):
    srv = ThreadingHTTPServer(('127.0.0.1', port), make_handler(app))
    srv.daemon_threads = True
    return srv
