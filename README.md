# Kontor

Persönliche Finanzverwaltung für den eigenen Server (Unraid/Docker): Konten, Buchungen, Kategorien und Regeln,
Verträge und Abos, Kredite, Depot mit aktuellen Kursen. Die Daten bleiben auf dem eigenen Server.

## Funktionen

- **Import:** Quicken (QIF), CSV vieler Banken mit Duplikaterkennung und Saldoabgleich, Trade Republic (Cash-Konto und Depot getrennt)
- **Online-Abruf per FinTS/HBCI** mit TAN-Freigabe (pushTAN, photoTAN, chipTAN manuell). Die PIN wird nie gespeichert.
- **Umbuchungen** zwischen eigenen Konten, automatisch verknüpft und abgeglichen
- **Kategorien, Tags und Regeln** für die automatische Zuordnung
- **Übersicht** mit Einnahmen/Ausgaben pro Monat und Ausgaben nach Kategorie
- **Verträge und Abos** mit Kündigungsfristen, Erkennung aus wiederkehrenden Zahlungen
- **Kredite** mit Tilgungsplan und Sondertilgung
- **Depot** mit Positionen, Einstand, aktuellem Kurs (über onvista, es wird nur die ISIN übertragen) und Gewinn/Verlust
- **Backup** als JSON, stündliche Sicherungen auf dem Server

## Aufbau

| Pfad | Inhalt |
|---|---|
| `app/index.html` | die komplette App (HTML/JS, ohne externe Abhängigkeiten) |
| `server/` | Python-Server: liefert die App aus, speichert die Daten, FinTS-Abruf, Kurse |
| `Dockerfile`, `docker-compose.yml`, `unraid/` | Container und Unraid-Vorlage |
| `docs/` | Planung |

Die App läuft auch ohne Server direkt im Browser (`app/index.html` öffnen); die Daten liegen dann nur in diesem Browser.

## Installation auf Unraid

Siehe [UNRAID.md](UNRAID.md).

## Lokal starten

```bash
pip install -r server/requirements.txt
HOST=127.0.0.1 PORT=8091 DATA_DIR=./data python server/app.py
```

Dann `http://localhost:8091` öffnen.

## Datenschutz

Keine Telemetrie, keine externen Skripte oder Schriften. Nach außen gehen nur der FinTS-Abruf zur eigenen Bank
und die ISINs der Depotpositionen für die Kursabfrage.
