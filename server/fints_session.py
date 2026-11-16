"""FinTS-Abruf in einem eigenen Thread, damit die App zwischendurch nach TAN oder Verfahren fragen kann.

Ablauf: start() legt eine Sitzung an und startet den Thread. Der Thread meldet über state, was er braucht:
  running   arbeitet (message sagt woran)
  choose    mehrere TAN-Verfahren, die App schickt {"mechanism": code}
  medium    mehrere TAN-Medien (z. B. Handys), die App schickt {"medium": index}
  tan       TAN nötig; bei decoupled (App-Freigabe) schickt die App {"confirm": true}, sonst {"tan": "123456"}
  done      fertig, result enthält Konten, Salden und Umsätze
  error     message enthält den Grund
Die PIN lebt nur im Thread und im python-fints-Client und wird nie gespeichert oder geloggt.
Gespeichert wird je Zugang nur der Client-Zustand (System-ID, gewähltes TAN-Verfahren), damit die Bank
das Gerät wiedererkennt und nicht bei jedem Abruf eine neue TAN verlangt.
"""
import base64
import hashlib
import os
import re
import threading
import time
import uuid
from datetime import date, datetime, timedelta

PRODUCT_ID = os.environ.get('FINTS_PRODUCT_ID', '').strip()
WAIT_SECONDS = 300          # so lange wartet ein Abruf auf TAN oder Auswahl
KEEP_SECONDS = 15 * 60      # danach wird eine Sitzung aufgeräumt

SESSIONS = {}
LOCK = threading.Lock()


def available():
    try:
        import fints.client  # noqa: F401
        return True
    except Exception:
        return False


def get(sid):
    with LOCK:
        return SESSIONS.get(sid)


def janitor():
    while True:
        time.sleep(60)
        now = time.time()
        with LOCK:
            for sid in [k for k, s in SESSIONS.items() if now - s.updated > KEEP_SECONDS]:
                SESSIONS.pop(sid, None)


class Cancelled(Exception):
    pass


class Session:
    def __init__(self, mode):
        self.id = uuid.uuid4().hex
        self.mode = mode
        self.state = 'running'
        self.message = 'Verbinde mit der Bank …'
        self.ask = None          # Daten für choose / medium / tan
        self.result = None
        self.updated = time.time()
        self._event = threading.Event()
        self._reply = None
        self._cancel = False
        self.q = 0             # Nummer der aktuellen Frage; Antworten müssen sie mitschicken

    def public(self):
        return {'id': self.id, 'mode': self.mode, 'state': self.state, 'message': self.message,
                'ask': self.ask, 'result': self.result, 'updated': self.updated}

    def step(self, message):
        self.state, self.message, self.ask = 'running', message, None
        self.updated = time.time()
        if self._cancel:
            raise Cancelled()

    def wait(self, state, message, ask):
        """Wartet auf eine Antwort der App und gibt sie zurück."""
        self._reply = None
        self._event.clear()
        self.q += 1
        self.state, self.message, self.ask = state, message, dict(ask, q=self.q)
        self.updated = time.time()
        if not self._event.wait(WAIT_SECONDS):
            raise TimeoutError('Keine Antwort innerhalb von 5 Minuten, der Abruf wurde abgebrochen.')
        if self._cancel:
            raise Cancelled()
        self.step('Weiter …')
        return self._reply or {}

    def answer(self, reply):
        # Nur annehmen, wenn wirklich gefragt wurde; sofort auf „running“, damit die App
        # nicht die alte Frage noch einmal anzeigt und ein zweiter Klick verloren geht.
        if self.state not in ('choose', 'medium', 'tan') or self._event.is_set() or reply.get('q') != self.q:
            return
        self._reply = reply
        self.state, self.message, self.ask = 'running', 'Weiter …', None
        self.updated = time.time()
        self._event.set()

    def cancel(self):
        self._cancel = True
        self._event.set()


def start(body, state_dir):
    mode = body.get('mode') or 'fetch'
    if mode not in ('test', 'fetch'):
        raise ValueError('Unbekannter Modus.')
    cfg = {k: str(body.get(k) or '').strip() for k in ('blz', 'url', 'login', 'customer', 'mechanism', 'since')}
    pin = str(body.get('pin') or '')
    if not re.fullmatch(r'\d{8}', cfg['blz']):
        raise ValueError('Die Bankleitzahl hat 8 Ziffern.')
    if not cfg['url'].startswith('https://'):
        raise ValueError('Die FinTS-Adresse muss mit https:// beginnen.')
    if not cfg['login'] or not pin:
        raise ValueError('Anmeldename und PIN fehlen.')
    if not PRODUCT_ID:
        # python-fints 4 verlangt sie zwingend, und die Banken lehnen ohne sie ab
        raise ValueError('Im Container ist keine FinTS-Produkt-ID eingetragen (FINTS_PRODUCT_ID). '
                         'Ohne die Registrierung bei der Deutschen Kreditwirtschaft ist kein Abruf möglich.')
    s = Session(mode)
    with LOCK:
        SESSIONS[s.id] = s
    threading.Thread(target=run, args=(s, cfg, pin, state_dir), daemon=True).start()
    return s


def _state_file(state_dir, cfg):
    h = hashlib.sha256(f"{cfg['blz']}|{cfg['login']}|{cfg['customer']}".encode('utf-8')).hexdigest()[:24]
    return os.path.join(state_dir, h + '.bin')


def _mech_list(client):
    out = []
    for code, m in (client.get_tan_mechanisms() or {}).items():
        if str(code) == '999':
            continue  # Ein-Schritt-Verfahren ohne TAN, nicht mehr zulässig
        name = getattr(m, 'name', '') or str(code)
        out.append({'code': str(code), 'name': name, 'decoupled': bool(getattr(m, 'decoupled_max_poll_number', None))})
    return out


def _handle_tan(s, client, res):
    from fints.client import NeedTANResponse
    while isinstance(res, NeedTANResponse):
        ask = {'challenge': (res.challenge or '').strip(), 'decoupled': bool(getattr(res, 'decoupled', False))}
        html = getattr(res, 'challenge_html', None)
        if html:
            ask['challenge'] = re.sub(r'<br\s*/?>', '\n', str(html))
            ask['challenge'] = re.sub(r'<[^>]+>', '', ask['challenge']).strip()
        matrix = getattr(res, 'challenge_matrix', None)
        if matrix:
            mime, data = matrix
            ask['image'] = f'data:{mime};base64,{base64.b64encode(data).decode("ascii")}'
        if getattr(res, 'challenge_hhduc', None):
            ask['flicker'] = True
        reply = s.wait('tan', 'Die Bank möchte eine Freigabe.', ask)
        res = client.send_tan(res, '' if ask['decoupled'] else str(reply.get('tan') or '').strip())
    return res


def _money(amount_obj):
    """python-fints/mt940 Amount oder Decimal -> Cent"""
    v = getattr(amount_obj, 'amount', amount_obj)
    return int((v * 100).to_integral_value()) if v is not None else None


def _tx_row(t):
    d = t.data
    day = d.get('date') or d.get('entry_date')
    amount = _money(d.get('amount'))
    payee = (d.get('applicant_name') or '').strip()
    purpose = d.get('purpose') or ''
    if isinstance(purpose, (list, tuple)):
        purpose = ' '.join(purpose)
    posting = (d.get('posting_text') or '').strip()
    memo = ' · '.join(x for x in [re.sub(r'\s+', ' ', purpose).strip(), posting if posting and posting != payee else ''] if x)
    return {
        'date': day.isoformat() if hasattr(day, 'isoformat') else str(day),
        'amount': amount,
        'payee': payee or posting,
        'memo': memo,
        'iban': (d.get('applicant_iban') or '').replace(' ', ''),
        'ref': (d.get('end_to_end_reference') or d.get('customer_reference') or '').strip(),
    }


def run(s, cfg, pin, state_dir):
    client = None
    try:
        from fints.client import FinTS3PinTanClient, NeedTANResponse
        os.makedirs(state_dir, exist_ok=True)
        sf = _state_file(state_dir, cfg)
        blob = None
        if os.path.exists(sf):
            with open(sf, 'rb') as f:
                blob = f.read()
        kwargs = {'customer_id': cfg['customer'] or None, 'product_id': PRODUCT_ID}
        if blob:
            kwargs['from_data'] = blob
        client = FinTS3PinTanClient(cfg['blz'], cfg['login'], pin, cfg['url'], **kwargs)
        pin = None

        # TAN-Verfahren: gemerktes, vorgegebenes, einziges, oder die App fragt
        s.step('Frage TAN-Verfahren ab …')
        if not client.get_current_tan_mechanism():
            client.fetch_tan_mechanisms()
            mechs = _mech_list(client)
            pick = next((m for m in mechs if m['code'] == cfg['mechanism']), None)
            if not pick and len(mechs) == 1:
                pick = mechs[0]
            if not pick and mechs:
                reply = s.wait('choose', 'Welches TAN-Verfahren nutzt du?', {'mechanisms': mechs})
                pick = next((m for m in mechs if m['code'] == str(reply.get('mechanism'))), mechs[0])
            if pick:
                client.set_tan_mechanism(pick['code'])
        if client.is_tan_media_required() and not client.selected_tan_medium:
            media = client.get_tan_media()[1]
            if len(media) == 1:
                client.set_tan_medium(media[0])
            elif media:
                names = [getattr(m, 'tan_medium_name', None) or str(i + 1) for i, m in enumerate(media)]
                reply = s.wait('medium', 'Welches Gerät soll die TAN bekommen?', {'media': names})
                i = int(reply.get('medium') or 0)
                client.set_tan_medium(media[i if 0 <= i < len(media) else 0])

        result = {'mechanism': str(client.get_current_tan_mechanism() or ''), 'accounts': []}
        with client:
            if client.init_tan_response:
                _handle_tan(s, client, client.init_tan_response)
            s.step('Lese Konten …')
            accounts = _handle_tan(s, client, client.get_sepa_accounts())
            since = None
            if cfg['since']:
                try:
                    since = date.fromisoformat(cfg['since'])
                except ValueError:
                    since = None
            since = since or (date.today() - timedelta(days=90))
            for acc in accounts:
                row = {'iban': getattr(acc, 'iban', '') or '', 'number': getattr(acc, 'accountnumber', '') or '',
                       'bic': getattr(acc, 'bic', '') or '', 'balance': None, 'tx': [], 'error': None}
                if s.mode == 'fetch':
                    try:
                        s.step(f'Saldo {row["iban"] or row["number"]} …')
                        bal = _handle_tan(s, client, client.get_balance(acc))
                        if bal is not None:
                            bd = getattr(bal, 'date', None)
                            row['balance'] = {'amount': _money(getattr(bal, 'amount', None)),
                                              'date': bd.isoformat() if hasattr(bd, 'isoformat') else date.today().isoformat()}
                        s.step(f'Umsätze {row["iban"] or row["number"]} seit {since:%d.%m.%Y} …')
                        txs = _handle_tan(s, client, client.get_transactions(acc, since, date.today()))
                        row['tx'] = [_tx_row(t) for t in (txs or [])]
                    except (Cancelled, TimeoutError):
                        raise
                    except Exception as e:
                        row['error'] = _friendly(e)
                result['accounts'].append(row)
        # Zustand ohne PIN merken (System-ID, TAN-Verfahren), damit die Bank das Gerät wiedererkennt
        try:
            with open(sf, 'wb') as f:
                f.write(client.deconstruct(including_private=True))
        except Exception:
            pass
        s.result = result
        s.state, s.message, s.ask = 'done', 'Fertig.', None
    except Cancelled:
        s.state, s.message, s.ask = 'error', 'Abgebrochen.', None
    except Exception as e:
        s.state, s.message, s.ask = 'error', _friendly(e), None
    finally:
        pin = None
        client = None
        s.updated = time.time()


def _friendly(e):
    name, text = type(e).__name__, str(e)
    if 'PIN' in name or re.search(r'\bPIN\b.*(falsch|ungültig|wrong)', text, re.I):
        return 'Die Bank hat die PIN abgelehnt. Bitte prüfen. Achtung: nach mehreren Fehlversuchen sperrt die Bank den Zugang.'
    if isinstance(e, TimeoutError):
        return text
    if 'product' in text.lower() and 'regist' in text.lower():
        return 'Die Bank verlangt eine registrierte Produkt-ID (FINTS_PRODUCT_ID im Container eintragen).'
    if 'ConnectionError' in name or 'Timeout' in name or 'SSL' in name:
        return 'Die Bank war nicht erreichbar. Stimmt die FinTS-Adresse?'
    return f'Die Bank hat den Abruf abgelehnt: {text[:300]}' if text else f'Fehler beim Abruf ({name}).'
