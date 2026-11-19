# Kontor

Persönliche Finanzverwaltung für den eigenen Server (Unraid/Docker): Konten, Buchungen, Kategorien und Regeln,
Verträge und Abos, Kredite, Depot mit aktuellen Kursen. Die Daten bleiben auf dem eigenen Server.

## Funktionen

- **Import:** Quicken (QIF), CSV vieler Banken mit Duplikaterkennung und Saldoabgleich, Trade Republic (Cash-Konto und Depot getrennt)
- **Online-Abruf per FinTS/HBCI** mit TAN-Freigabe (pushTAN, photoTAN, chipTAN manuell). Die PIN wird nie gespeichert.
- **Umbuchungen** zwischen eigenen Konten, automatisch verknüpft und abgeglichen
- **Belege an Buchungen** (Rechnungen, Fotos): im Buchungsdialog oder beim Hochladen mit Vorschlägen aus dem Dateinamen
- **Sparen und Tilgung** getrennt von den Ausgaben: Umbuchungen auf Spar-, Depot- und Rentenkonten zählen als Sparen, Kreditraten als Tilgung plus Zinsen
- **Kategorien, Tags und Regeln** für die automatische Zuordnung, auch als Umbuchung auf ein Konto; Tags für viele Buchungen auf einmal per Mehrfachauswahl
- **Kontogruppen** nach Kontoart oder selbst angelegt, mit Summen und als Buchungsfilter
- **Sparkonten** mit Zinssatz-Verlauf und Zinshochrechnung, **Rentenkonten** mit Auszahlungstermin, Prognose zum Auszahlungstag, Fondsguthaben und Umbuchung der Beiträge aus Sammelabbuchungen
- **Geldfluss** als Sankey-Diagramm: Einnahmen → Konten → Ausgaben
- **Übersicht** mit Einnahmen/Ausgaben pro Monat und Ausgaben nach Kategorie
- **Einstellungen** für Schriftgröße, Hell/Dunkel und Farbschema (pro Browser)
- **Verträge und Abos** mit Kündigungsfristen, Erkennung aus wiederkehrenden Zahlungen
- **Kredite** mit Tilgungsplan und Sondertilgung
- **Depot** mit Positionen, Einstand, aktuellem Kurs (über onvista, es wird nur die ISIN übertragen) und Gewinn/Verlust
- **Backup** als JSON, stündliche, tägliche und Sicherungen vor jedem Update auf dem Server

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
