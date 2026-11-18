"""Kontor-Server für Unraid.

Liefert die App aus, speichert die Daten als JSON in DATA_DIR (mit stündlichen Sicherungen)
und ruft Umsätze per FinTS ab (siehe fints_session.py).

Nur Standardbibliothek; python-fints wird erst beim ersten Abruf geladen.
Umgebungsvariablen:
  PORT              Port im Container (Standard 8080)
  DATA_DIR          Datenordner (Standard /data)
  APP_DIR           Ordner mit index.html (Standard ../app neben diesem Skript)
  APP_PASSWORD      wenn gesetzt: Anmeldung per Browser-Dialog (Benutzername beliebig)
  FINTS_PRODUCT_ID  bei der Deutschen Kreditwirtschaft registrierte Produkt-ID
  BACKUP_KEEP       Anzahl stündlicher Sicherungen (Standard 72)
  BACKUP_DAYS       Anzahl täglicher Sicherungen (Standard 30)

Sicherungen in DATA_DIR/backups: stündlich und täglich beim Speichern, dazu bei jedem
Start mit einer neuen Version (kontor-vor-<version>-<zeit>.json, die letzten 10 bleiben).
"""
import base64
import hmac
import json
import mimetypes
import os
import shutil
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlparse

import drop
import fints_session
import quotes

HERE = os.path.dirname(os.path.abspath(__file__))


def _version():
    """Die Versionsnummer steht in der Datei VERSION im Hauptordner (im Container neben server/)."""
    for p in (os.path.join(HERE, '..', 'VERSION'), os.path.join(HERE, 'VERSION')):
        try:
            with open(p, encoding='utf-8') as f:
                return f.read().strip()
        except OSError:
            pass
    return 'unbekannt'


VERSION = _version()
PORT = int(os.environ.get('PORT', '8080'))
HOST = os.environ.get('HOST', '0.0.0.0')   # 127.0.0.1 = nur von diesem Rechner erreichbar
DATA_DIR = os.path.abspath(os.environ.get('DATA_DIR', '/data'))
APP_DIR = os.path.abspath(os.environ.get('APP_DIR', os.path.join(HERE, '..', 'app')))
PASSWORD = os.environ.get('APP_PASSWORD', '')
BACKUP_KEEP = int(os.environ.get('BACKUP_KEEP', '72'))
BACKUP_DAYS = int(os.environ.get('BACKUP_DAYS', '30'))
UPDATE_KEEP = 10
MAX_BODY = 64 * 1024 * 1024

DATA_FILE = os.path.join(DATA_DIR, 'kontor.json')
OLD_DATA_FILE = os.path.join(DATA_DIR, 'finanzmanager.json')   # Name bis zur Umbenennung in Kontor
BACKUP_DIR = os.path.join(DATA_DIR, 'backups')
LOCK = threading.Lock()


def log(msg):
    print(f'{datetime.now():%Y-%m-%d %H:%M:%S} {msg}', flush=True)


# ---------- Datenablage ----------

def read_store():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {'rev': 0, 'saved': None, 'data': None}


def write_store(store):
    """Atomar schreiben: erst in eine Temp-Datei, dann umbenennen."""
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, DATA_FILE)


BACKUP_KINDS = {
    # Art: (Ordner, Erkennung am Dateinamen, wie viele bleiben)
    'hourly': (BACKUP_DIR, lambda f: f.startswith('kontor-') and f[7:8].isdigit(), lambda: BACKUP_KEEP),
    'daily': (os.path.join(BACKUP_DIR, 'taeglich'), lambda f: f.startswith('kontor-'), lambda: BACKUP_DAYS),
    'update': (BACKUP_DIR, lambda f: f.startswith('kontor-vor-'), lambda: UPDATE_KEEP),
}


def backup_files(kind):
    folder, match, _ = BACKUP_KINDS[kind]
    try:
        files = [f for f in os.listdir(folder) if f.endswith('.json') and match(f)]
    except FileNotFoundError:
        return []
    # Sicherungen nach Versionswechseln sind nach Version benannt, nicht nach Zeit: nach Alter sortieren
    return sorted(files, key=(lambda f: os.path.getmtime(os.path.join(folder, f))) if kind == 'update' else None)


def backup_copy(kind, name):
    """Kopie anlegen (falls noch nicht vorhanden) und die ältesten über dem Limit löschen."""
    if not os.path.exists(DATA_FILE):
        return
    folder, _, keep = BACKUP_KINDS[kind]
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, name)
    if os.path.exists(target):
        return
    shutil.copy2(DATA_FILE, target)
    for old in backup_files(kind)[:-keep()]:
        try:
            os.remove(os.path.join(folder, old))
        except OSError:
            pass


def backup_if_due():
    """Vor dem Speichern: höchstens eine Sicherung pro Stunde und eine pro Tag."""
    now = datetime.now()
    backup_copy('hourly', f'kontor-{now:%Y%m%d-%H}.json')
    backup_copy('daily', f'kontor-{now:%Y%m%d}.json')


def backup_on_version_change():
    """Beim ersten Start einer neuen Version den Stand davor sichern."""
    marker = os.path.join(DATA_DIR, 'version.txt')
    try:
        with open(marker, encoding='utf-8') as f:
            last = f.read().strip()
    except OSError:
        last = ''
    if last == VERSION:
        return
    if os.path.exists(DATA_FILE):
        name = f'kontor-vor-{VERSION}-{datetime.now():%Y%m%d-%H%M%S}.json'
        backup_copy('update', name)
        log(f'Version {last or "?"} -> {VERSION}, Sicherung {name}')
    with open(marker, 'w', encoding='utf-8') as f:
        f.write(VERSION)


def backup_overview():
    out = {'dir': BACKUP_DIR}
    for kind in BACKUP_KINDS:
        files = backup_files(kind)
        out[kind] = {'count': len(files), 'last': files[-1] if files else None}
    out['update']['files'] = backup_files('update')
    return out


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = 'Kontor/' + VERSION

    def log_message(self, fmt, *args):
        # Kein Logging von Anfragen: in Bodies stehen PINs und Kontodaten.
        pass

    # --- Hilfen ---
    def send_json(self, code, obj, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            raise ValueError('Anfrage zu groß')
        raw = self.rfile.read(n) if n else b''
        return json.loads(raw.decode('utf-8')) if raw else {}

    def authorized(self):
        if not PASSWORD:
            return True
        h = self.headers.get('Authorization', '')
        if h.startswith('Basic '):
            try:
                user_pw = base64.b64decode(h[6:]).decode('utf-8')
                pw = user_pw.split(':', 1)[1] if ':' in user_pw else ''
                if hmac.compare_digest(pw.encode('utf-8'), PASSWORD.encode('utf-8')):
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm="Kontor", charset="UTF-8"')
        self.send_header('Content-Length', '0')
        self.end_headers()
        return False

    def common_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')

    def end_headers(self):
        self.common_headers()
        super().end_headers()

    # --- Routen ---
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/health':
            # ohne Anmeldung, damit der Docker-Healthcheck funktioniert; verrät nichts über die Daten
            return self.send_json(200, {'ok': True, 'version': VERSION, 'fints': fints_session.available(),
                                        'productId': bool(fints_session.PRODUCT_ID), 'auth': bool(PASSWORD)})
        if not self.authorized():
            return
        if path == '/api/data':
            with LOCK:
                store = read_store()
            return self.send_json(200, store)
        if path == '/api/backups':
            return self.send_json(200, backup_overview())
        if path.startswith('/api/fints/'):
            s = fints_session.get(path.rsplit('/', 1)[-1])
            return self.send_json(200, s.public()) if s else self.send_json(404, {'error': 'Abruf nicht gefunden oder abgelaufen.'})
        if path.startswith('/api/drop') or path.startswith('/api/archive'):
            return self.drop_get(path, parse_qs(urlparse(self.path).query))
        return self.serve_static(path)

    # --- Eingangsordner und Archiv ---
    def send_file(self, name, data, download):
        ctype = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Disposition', f"{'attachment' if download else 'inline'}; filename*=UTF-8''{quote(name)}")
        self.end_headers()
        self.wfile.write(data)

    def drop_get(self, path, q):
        arg = lambda k: (q.get(k) or [''])[0]
        try:
            if path == '/api/drop':
                if not drop.available():
                    return self.send_json(200, {'dir': drop.DROP_DIR, 'available': False, 'files': [], 'inbox': []})
                return self.send_json(200, dict(drop.listing(), available=True))
            if path == '/api/drop/file':
                return self.send_file(arg('name'), drop.read(arg('box'), arg('name')), arg('dl') == '1')
            if path == '/api/drop/pdf':
                return self.send_json(200, drop.pdf_info(arg('box'), arg('name')))
            if path == '/api/archive/file':
                name, data = drop.archive_read(arg('path'), arg('kind'))
                return self.send_file(name, data, arg('dl') == '1')
        except (FileNotFoundError, ValueError) as e:
            return self.send_json(404, {'error': str(e)})
        except Exception as e:
            return self.send_json(500, {'error': f'{type(e).__name__}: {e}'})
        return self.send_json(404, {'error': 'Nicht gefunden'})

    def drop_post(self, path, body):
        try:
            if path == '/api/drop/inbox':
                return self.send_json(200, {'name': drop.to_inbox(body.get('name'), body.get('reason'))})
            if path == '/api/drop/requeue':
                return self.send_json(200, {'name': drop.requeue(body.get('name'))})
            if path == '/api/drop/archive':
                return self.send_json(200, drop.archive(body.get('box'), body.get('name'), body.get('acct')))
            if path == '/api/drop/trash':
                drop.trash(body.get('box'), body.get('name'))
                return self.send_json(200, {'ok': True})
            if path == '/api/archive/delete':
                drop.archive_delete(body.get('path'), body.get('kind') or '')
                return self.send_json(200, {'ok': True})
        except (FileNotFoundError, ValueError) as e:
            return self.send_json(404, {'error': str(e)})
        except Exception as e:
            return self.send_json(500, {'error': f'{type(e).__name__}: {e}'})
        return self.send_json(404, {'error': 'Nicht gefunden'})

    def do_PUT(self):
        path = urlparse(self.path).path
        if not self.authorized():
            return
        if path == '/api/archive/upload':
            q = parse_qs(urlparse(self.path).query)
            n = int(self.headers.get('Content-Length') or 0)
            if n > MAX_BODY:
                return self.send_json(413, {'error': 'Datei zu groß'})
            try:
                qa = lambda k: (q.get(k) or [''])[0]
                return self.send_json(200, drop.archive_upload(qa('acct'), qa('name'), self.rfile.read(n), qa('kind'), qa('year')))
            except ValueError as e:
                return self.send_json(400, {'error': str(e)})
        if path != '/api/data':
            return self.send_json(404, {'error': 'Nicht gefunden'})
        try:
            data = self.read_json()
        except Exception as e:
            return self.send_json(400, {'error': f'Ungültige Daten: {e}'})
        if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('tx'), list):
            return self.send_json(400, {'error': 'Das sieht nicht nach Kontor-Daten aus.'})
        expected = self.headers.get('If-Match', '')
        with LOCK:
            store = read_store()
            if expected != '' and str(store['rev']) != expected:
                return self.send_json(409, {'error': 'Auf dem Server liegt ein neuerer Stand.', 'rev': store['rev']})
            backup_if_due()
            store = {'rev': store['rev'] + 1, 'saved': datetime.now().isoformat(timespec='seconds'), 'data': data}
            write_store(store)
        return self.send_json(200, {'rev': store['rev'], 'saved': store['saved']})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.authorized():
            return
        try:
            body = self.read_json()
        except Exception as e:
            return self.send_json(400, {'error': f'Ungültige Anfrage: {e}'})
        if path.startswith('/api/drop/') or path.startswith('/api/archive/'):
            return self.drop_post(path, body if isinstance(body, dict) else {})
        if path == '/api/quotes':
            isins = body.get('isins') if isinstance(body, dict) else None
            if not isinstance(isins, list):
                return self.send_json(400, {'error': 'isins fehlt'})
            return self.send_json(200, {'quotes': quotes.quotes(isins)})
        if path == '/api/fints/start':
            if not fints_session.available():
                return self.send_json(503, {'error': 'Die FinTS-Bibliothek ist im Container nicht installiert.'})
            try:
                s = fints_session.start(body, os.path.join(DATA_DIR, 'fints'))
            except ValueError as e:
                return self.send_json(400, {'error': str(e)})
            return self.send_json(200, s.public())
        if path.startswith('/api/fints/') and path.endswith('/answer'):
            sid = path.split('/')[3]
            s = fints_session.get(sid)
            if not s:
                return self.send_json(404, {'error': 'Abruf nicht gefunden oder abgelaufen.'})
            s.answer(body)
            return self.send_json(200, s.public())
        if path.startswith('/api/fints/') and path.endswith('/cancel'):
            s = fints_session.get(path.split('/')[3])
            if s:
                s.cancel()
            return self.send_json(200, {'ok': True})
        return self.send_json(404, {'error': 'Nicht gefunden'})

    def serve_static(self, path):
        rel = unquote(path).lstrip('/') or 'index.html'
        if rel.endswith('/'):
            rel += 'index.html'
        full = os.path.abspath(os.path.join(APP_DIR, rel))
        if not (full == APP_DIR or full.startswith(APP_DIR + os.sep)) or not os.path.isfile(full):
            self.send_response(404)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        with open(full, 'rb') as f:
            body = f.read()
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype in ('application/javascript', 'application/json'):
            ctype += '; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(body)


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE) and os.path.exists(OLD_DATA_FILE):
        os.replace(OLD_DATA_FILE, DATA_FILE)
        log('Datendatei finanzmanager.json in kontor.json umbenannt')
    backup_on_version_change()
    if not os.path.isfile(os.path.join(APP_DIR, 'index.html')):
        log(f'index.html nicht gefunden in {APP_DIR}')
        sys.exit(1)
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    srv.daemon_threads = True
    log(f'Kontor {VERSION} auf Port {PORT}, Daten in {DATA_DIR}, '
        f'Anmeldung {"an" if PASSWORD else "AUS"}, FinTS {"bereit" if fints_session.available() else "nicht installiert"}'
        f'{"" if fints_session.PRODUCT_ID else " (ohne Produkt-ID)"}')
    drop.setup(DATA_DIR)
    log(f'Eingangsordner {drop.DROP_DIR} {"bereit" if drop.available() else "FEHLT oder nicht beschreibbar"}')
    threading.Thread(target=fints_session.janitor, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
