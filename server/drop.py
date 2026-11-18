"""Eingangsordner und Archiv für Kontoauszüge.

DROP_DIR       Ordner, in den heruntergeladene Bankdateien gelegt werden (z. B. eine Unraid-Freigabe).
DROP_DIR/Inbox Dateien, die die App nicht zuordnen konnte, mit Begründung in .gruende.json.
ARCHIVE_DIR    abgelegte Kontoauszüge, ein Unterordner je Konto.
RECEIPT_DIR    Belege zu Buchungen (Rechnungen usw.), je Konto und Jahr ein Unterordner.
TRASH_DIR      verworfene oder gelöschte Dateien; nichts wird hart gelöscht.

Die Zuordnung selbst macht die App (gleiche Logik wie beim Import von Hand). Der Server listet, liefert,
liest PDF-Text und verschiebt Dateien.
"""
import json
import os
import re
import shutil
import time
from datetime import datetime

DROP_DIR = os.path.abspath(os.environ.get('DROP_DIR', '/eingang'))
INBOX = 'Inbox'
TEMP_EXT = ('.crdownload', '.part', '.tmp', '.download', '.partial')
SETTLE_SECONDS = 5            # erst verarbeiten, wenn die Datei so lange unverändert ist
MAX_FILE = 50 * 1024 * 1024
IBAN_RE = re.compile(r'\b([A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,4})?)\b')
DATE_RE = re.compile(r'\b(\d{1,2})\.(\d{1,2})\.(20\d\d)\b')


def setup(data_dir):
    global ARCHIVE_DIR, TRASH_DIR, RECEIPT_DIR
    ARCHIVE_DIR = os.path.join(data_dir, 'kontoauszuege')
    RECEIPT_DIR = os.path.join(data_dir, 'belege')
    TRASH_DIR = os.path.join(data_dir, 'papierkorb')
    try:
        os.makedirs(os.path.join(DROP_DIR, INBOX), exist_ok=True)
    except OSError:
        pass


def available():
    return os.path.isdir(DROP_DIR) and os.access(DROP_DIR, os.W_OK)


def _box_dir(box):
    return os.path.join(DROP_DIR, INBOX) if box == 'inbox' else DROP_DIR


def _safe_name(name):
    name = str(name or '')
    if not name or name != os.path.basename(name) or name in ('.', '..') or name.startswith('.') or '\\' in name or '/' in name:
        raise ValueError('Ungültiger Dateiname')
    return name


def _safe_folder(acct):
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', str(acct or '').strip()).strip('. ')
    if not s:
        raise ValueError('Konto fehlt')
    return s


def _unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 2
    while os.path.exists(f'{base} ({i}){ext}'):
        i += 1
    return f'{base} ({i}){ext}'


def _kind(name):
    n = name.lower()
    return 'pdf' if n.endswith('.pdf') else 'csv' if n.endswith(('.csv', '.txt')) else 'other'


def _reasons_file():
    return os.path.join(DROP_DIR, INBOX, '.gruende.json')


def _reasons():
    try:
        with open(_reasons_file(), 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_reasons(r):
    tmp = _reasons_file() + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _reasons_file())


def _entries(folder, settle):
    out = []
    try:
        names = os.listdir(folder)
    except OSError:
        return out
    now = time.time()
    for n in sorted(names):
        p = os.path.join(folder, n)
        if n.startswith('.') or not os.path.isfile(p) or n.lower().endswith(TEMP_EXT) or n.lower() == 'desktop.ini':
            continue
        st = os.stat(p)
        if settle and now - st.st_mtime < SETTLE_SECONDS:
            continue
        out.append({'name': n, 'size': st.st_size, 'mtime': datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds'), 'kind': _kind(n)})
    return out


def listing():
    reasons = _reasons()
    inbox = _entries(os.path.join(DROP_DIR, INBOX), False)
    for e in inbox:
        e['reason'] = reasons.get(e['name'], '')
    return {'dir': DROP_DIR, 'files': _entries(DROP_DIR, True), 'inbox': inbox}


def read(box, name):
    p = os.path.join(_box_dir(box), _safe_name(name))
    if os.path.getsize(p) > MAX_FILE:
        raise ValueError('Datei größer als 50 MB')
    with open(p, 'rb') as f:
        return f.read()


def pdf_info(box, name):
    """Text der ersten Seiten, gefundene IBANs und Datumsangaben."""
    from pypdf import PdfReader
    p = os.path.join(_box_dir(box), _safe_name(name))
    reader = PdfReader(p)
    if reader.is_encrypted:
        try:
            reader.decrypt('')
        except Exception:
            return {'text': '', 'ibans': [], 'dates': [], 'error': 'PDF ist verschlüsselt'}
    text = ''
    for page in reader.pages[:3]:
        try:
            text += (page.extract_text() or '') + '\n'
        except Exception:
            pass
    ibans = sorted({m.replace(' ', '') for m in IBAN_RE.findall(text) if 15 <= len(m.replace(' ', '')) <= 34})
    dates = sorted({f'{y}-{int(m):02d}-{int(d):02d}' for d, m, y in DATE_RE.findall(text) if 1 <= int(m) <= 12 and 1 <= int(d) <= 31})
    return {'text': text[:6000], 'ibans': ibans, 'dates': dates}


def to_inbox(name, reason):
    name = _safe_name(name)
    src = os.path.join(DROP_DIR, name)
    dst = _unique(os.path.join(DROP_DIR, INBOX, name))
    shutil.move(src, dst)
    r = _reasons()
    r[os.path.basename(dst)] = str(reason or '')[:500]
    _save_reasons(r)
    return os.path.basename(dst)


def requeue(name):
    """Aus der Inbox zurück in den Eingang, damit die App es erneut versucht."""
    name = _safe_name(name)
    dst = _unique(os.path.join(DROP_DIR, name))
    shutil.move(os.path.join(DROP_DIR, INBOX, name), dst)
    r = _reasons()
    r.pop(name, None)
    _save_reasons(r)
    # Zeitstempel erneuern, sonst wartet die Prüfung nicht; neu ist es ja nicht
    return os.path.basename(dst)


def _forget_reason(box, name):
    if box == 'inbox':
        r = _reasons()
        if r.pop(name, None) is not None:
            _save_reasons(r)


def archive(box, name, acct):
    """Datei aus Eingang oder Inbox ins Archiv des Kontos verschieben. Gibt den Pfad relativ zum Archiv zurück."""
    name = _safe_name(name)
    folder = os.path.join(ARCHIVE_DIR, _safe_folder(acct))
    os.makedirs(folder, exist_ok=True)
    dst = _unique(os.path.join(folder, name))
    shutil.move(os.path.join(_box_dir(box), name), dst)
    _forget_reason(box, name)
    return {'path': os.path.relpath(dst, ARCHIVE_DIR).replace(os.sep, '/'), 'size': os.path.getsize(dst)}


def trash(box, name):
    name = _safe_name(name)
    os.makedirs(TRASH_DIR, exist_ok=True)
    shutil.move(os.path.join(_box_dir(box), name), _unique(os.path.join(TRASH_DIR, name)))
    _forget_reason(box, name)


# ---------- Archiv ----------

def _root(kind):
    """Ablage: Kontoauszüge (Standard) oder Belege zu Buchungen (kind='beleg')."""
    return RECEIPT_DIR if kind == 'beleg' else ARCHIVE_DIR


def _archive_path(rel, kind=''):
    base = os.path.abspath(_root(kind))
    full = os.path.abspath(os.path.join(base, str(rel or '')))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        raise FileNotFoundError('Datei nicht im Archiv')
    return full


def archive_upload(acct, name, data, kind='', year=''):
    name = _safe_name(os.path.basename(str(name or '').replace('\\', '/')))
    if len(data) > MAX_FILE:
        raise ValueError('Datei größer als 50 MB')
    folder = os.path.join(_root(kind), _safe_folder(acct))
    if kind == 'beleg' and re.fullmatch(r'(19|20)\d\d', str(year or '')):
        folder = os.path.join(folder, str(year))
    os.makedirs(folder, exist_ok=True)
    dst = _unique(os.path.join(folder, name))
    with open(dst, 'wb') as f:
        f.write(data)
    return {'path': os.path.relpath(dst, _root(kind)).replace(os.sep, '/'), 'size': len(data)}


def archive_read(rel, kind=''):
    p = _archive_path(rel, kind)
    with open(p, 'rb') as f:
        return os.path.basename(p), f.read()


def archive_delete(rel, kind=''):
    p = _archive_path(rel, kind)
    os.makedirs(TRASH_DIR, exist_ok=True)
    shutil.move(p, _unique(os.path.join(TRASH_DIR, os.path.basename(p))))
