"""Aktuelle Kurse über die öffentliche onvista-Schnittstelle (ohne Anmeldung, inoffiziell).

An onvista geht nur die ISIN, keine Stückzahlen oder Beträge.
Bevorzugt wird der Handelsplatz von Trade Republic (LS Exchange), dann andere Euro-Plätze.
Ergebnisse werden 60 Sekunden zwischengespeichert, die ISIN-Zuordnung bis zum Neustart.
"""
import json
import re
import time
import urllib.parse
import urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Kontor)', 'Accept': 'application/json'}
BASE = 'https://api.onvista.de/api/v1'
PREFERRED = ['_LSX', '@_LUSG', '_GAT', '_TRO', '_GER', '@_BBF', '_QUO', '_FRA', '_STU', '_MUN', '_HAM', '_DUS', '_BPS', '@_WM']
CACHE_SECONDS = 60

_entities = {}   # isin -> (entityType, entityValue, name)
_quotes = {}     # isin -> (zeit, ergebnis)


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        return json.load(r)


def _entity(isin):
    if isin not in _entities:
        q = _get(f'{BASE}/instruments/query?searchValue={urllib.parse.quote(isin)}')
        hit = next((x for x in q.get('list', []) if x.get('isin') == isin), None)
        if not hit:
            raise LookupError('bei onvista nicht gefunden')
        _entities[isin] = (hit['entityType'], hit['entityValue'], hit.get('name') or isin)
    return _entities[isin]


def _pick(markets):
    """Euro-Kurs vom bevorzugten Handelsplatz; sonst der jüngste Euro-Kurs; sonst der jüngste überhaupt."""
    ok = [m for m in markets if m.get('last') is not None]
    eur = [m for m in ok if m.get('isoCurrency') == 'EUR']
    for code in PREFERRED:
        m = next((m for m in eur if (m.get('market') or {}).get('codeMarket') == code), None)
        if m:
            return m
    pool = eur or ok
    return max(pool, key=lambda m: m.get('datetimeLast') or '') if pool else None


def quote(isin):
    now = time.time()
    hit = _quotes.get(isin)
    if hit and now - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        et, ev, name = _entity(isin)
        snap = _get(f'{BASE}/instruments/{et}/{ev}/snapshot')
        m = _pick((snap.get('quoteList') or {}).get('list') or [])
        if not m:
            raise LookupError('kein Kurs verfügbar')
        res = {'price': float(m['last']), 'currency': m.get('isoCurrency') or '', 'time': m.get('datetimeLast') or '',
               'market': (m.get('market') or {}).get('name') or '', 'name': name,
               'prev': m.get('previousLast'), 'changePct': m.get('performancePct')}
    except Exception as e:
        res = {'error': str(e)[:200] or type(e).__name__}
    _quotes[isin] = (now, res)
    return res


def quotes(isins):
    out = {}
    for isin in isins[:100]:
        isin = str(isin).strip().upper()
        if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}\d', isin):
            out[isin] = quote(isin)
    return out
