# Kontor auf Unraid

Der Container liefert die App aus, speichert alle Daten in `/mnt/user/appdata/kontor`
und ruft Umsätze per FinTS bei der Bank ab. Es werden keine Daten an Dritte geschickt,
nur an deine Bank. Die PIN wird nie gespeichert.

## 1. Code auf den Server holen

Im Unraid-Terminal (oben rechts `>_`):

```bash
git clone https://github.com/wumonline/kontor.git /mnt/user/appdata/kontor-src
```

Später aktualisieren mit `cd /mnt/user/appdata/kontor-src && git pull`, danach Schritt 2 wiederholen.

Ohne Git: auf GitHub unter **Code → Download ZIP** herunterladen und nach `/mnt/user/appdata/kontor-src` entpacken.

## 2. Image bauen

Im Unraid-Terminal (oben rechts `>_`):

```bash
cd /mnt/user/appdata/kontor-src
docker build -t kontor:latest -t kontor:$(cat VERSION) .
```

Für spätere Updates siehe [Updates und Versionen](#updates-und-versionen).

## 3. Container anlegen

Vorlage einmalig kopieren:

```bash
cp /mnt/user/appdata/kontor-src/unraid/kontor.xml /boot/config/plugins/dockerMan/templates-user/my-kontor.xml
```

Dann im Reiter **Docker** → **Container hinzufügen** → Vorlage **kontor** wählen:

| Feld | Empfehlung |
|---|---|
| Web-Port | 8090 (oder ein freier Port) |
| Daten | `/mnt/user/appdata/kontor` |
| Passwort | unbedingt setzen, der Benutzername im Anmeldefenster ist beliebig |
| Eingangsordner | `/mnt/user/finanzen/eingang`, siehe Abschnitt 6 |
| FinTS-Produkt-ID | siehe Abschnitt 5 |

**Anwenden**, danach ist die App unter `http://<unraid-ip>:8090` erreichbar.

Alternativ mit Docker Compose: `docker-compose.yml` in diesem Ordner anpassen und `docker compose up -d --build`.

## 4. Bisherige Daten übernehmen

Die Daten aus dem Browser-Prototyp liegen nur in diesem Browser. So kommen sie auf den Server:

1. Im bisherigen Browser-Prototyp unter **Konten & Daten** ein **Backup herunterladen**.
2. Die App über `http://<unraid-ip>:8090` öffnen, dort **Backup wiederherstellen** und die Datei wählen.

Unten links steht dann „Daten liegen auf deinem Server“.
Abgelegte Kontoauszüge (PDF/CSV) sind nicht im Backup und müssen bei Bedarf neu abgelegt werden.

## 5. Online-Abruf (FinTS)

1. **Konten & Daten** → Institut → **Online-Zugang einrichten** → Verfahren „FinTS / HBCI“.
2. Bankleitzahl, FinTS-Adresse und Anmeldename eintragen. Die FinTS-Adresse nennt die Bank
   (oft im Hilfebereich unter „Finanzsoftware“ oder „HBCI/FinTS“).
3. **Verbindung testen**: PIN eingeben, TAN-Verfahren wählen, in der Banking-App freigeben.
   Die App zeigt die Konten, die die Bank meldet. Damit sie automatisch zugeordnet werden,
   bei den Konten die IBAN eintragen.
4. **Umsätze abrufen**: holt Umsätze und Saldo. Schon vorhandene Buchungen werden übersprungen,
   der Saldo landet als „Stand laut Bank“ beim Konto.

**Produkt-ID:** Banken verlangen seit 2019 eine bei der Deutschen Kreditwirtschaft registrierte
Software-Kennung. Die Registrierung ist kostenlos (Antrag über die Website der Deutschen Kreditwirtschaft
zum FinTS-Produktregistrierungsverfahren) und dauert einige Wochen. Ohne sie ist kein Abruf möglich:
Die Bibliothek python-fints verlangt sie zwingend, und die App sperrt die Knöpfe mit einem Hinweis.
Die Nummer im Container als `FINTS_PRODUCT_ID` eintragen.

Die Bank erkennt den Server nach dem ersten Abruf wieder (der Zustand liegt in `appdata/kontor/fints`).
Eine erneute starke Freigabe verlangt sie dann typischerweise erst nach 90 Tagen.

## 6. Eingangsordner für Bankdateien

Im Container ist `/eingang` ein eigener Ordner, standardmäßig `/mnt/user/finanzen/eingang`.
Gib die Freigabe `finanzen` per SMB frei (Reiter **Shares**), dann kannst du heruntergeladene Dateien vom PC direkt
dort hineinlegen oder den Download-Ordner des Browsers dorthin zeigen lassen.

Solange die App in einem Browser offen ist, prüft sie den Ordner jede Minute:

| Datei | Was passiert |
|---|---|
| CSV mit Umsätzen | Import, wenn IBAN oder Kontonummer (in der Datei oder im Dateinamen) zu genau einem Konto passt. Duplikate werden übersprungen, Regeln angewendet. |
| Trade-Republic-Export | Import, sobald Cash-Konto und Depot einmal von Hand angelegt sind |
| Depotübersicht (z. B. ING) | Bestand abgleichen, sobald das Depot über die Depotnummer bekannt ist |
| PDF-Kontoauszug | Ablage beim Konto, wenn IBAN oder Kontonummer im Text zu genau einem Konto passt |
| alles andere | kommt nach `eingang/Inbox`, mit Begründung unter **Import → Eingang** |

In der Inbox kannst du Dateien von Hand importieren, einem Konto zuordnen, erneut prüfen lassen
(z. B. nachdem du beim Konto die IBAN eingetragen hast) oder verwerfen. Verarbeitete Dateien liegen danach in
`appdata/kontor/kontoauszuege/<Konto>`, verworfene in `appdata/kontor/papierkorb`. Gelöscht wird nichts.

Belege zu Buchungen (Rechnungen, Fotos) liegen in `appdata/kontor/belege/<Konto>/<Jahr>`. Ein PDF in der
Inbox lässt sich mit **Als Beleg …** einer Buchung zuordnen.

PDFs müssen echten Text enthalten. Eingescannte Auszüge ohne Texterkennung landen in der Inbox.

## Sicherheit

- **Passwort setzen.** Ohne Passwort kann jeder im Heimnetz die Finanzdaten sehen.
- Nicht ins Internet freigeben. Für den Zugriff von unterwegs WireGuard (in Unraid eingebaut) nutzen.
- Zwischen Browser und Server läuft die PIN unverschlüsselt über HTTP, solange kein HTTPS davor sitzt.
  Im eigenen Netz ist das vertretbar; mit einem Reverse Proxy (z. B. Nginx Proxy Manager) und HTTPS ist es besser.

## Updates und Versionen

Die laufende Version steht in Kontor unter **Konten & Daten → Backup**. Die Versionsnummer steht in der Datei
`VERSION`; jede Version ist auf GitHub als Tag markiert (z. B. `v0.3.0`), mit einer Notiz unter **Releases**.

Update im Unraid-Terminal:

```bash
cd /mnt/user/appdata/kontor-src && curl -fsSL https://github.com/wumonline/kontor/archive/refs/heads/main.tar.gz | tar xz --strip-components=1 && docker build -t kontor:latest -t kontor:$(cat VERSION) .
```

Danach den Container **neu anlegen**, nicht nur neu starten (ein Neustart behält das alte Image):
Docker → Kontor → **Edit** → **Apply**. Ist Apply ausgegraut, ein Feld kurz ändern und zurücksetzen.

Zurück zu einer früheren Version: Docker → Kontor → **Edit**, bei **Repository** statt `kontor:latest`
z. B. `kontor:0.3.0` eintragen → **Apply**. `docker images kontor` zeigt, welche Versionen vorhanden sind.
Alte Images löschen mit `docker rmi kontor:0.3.0`.

## Sicherungen

Der Server sichert `kontor.json` selbst nach `appdata/kontor/backups`:

- stündlich beim Speichern, die letzten 72 bleiben (`BACKUP_KEEP`),
- täglich in `backups/taeglich`, die letzten 30 bleiben (`BACKUP_DAYS`),
- beim ersten Start einer neuen Version als `kontor-vor-<version>-<zeit>.json`, die letzten 10 bleiben.

Wiederherstellen: Container stoppen, die gewünschte Sicherung als `kontor.json` nach `appdata/kontor` kopieren,
Container starten. Oder die Datei in Kontor über **Backup wiederherstellen** laden.
Den `appdata`-Ordner zusätzlich mit dem Unraid-Plugin „Appdata Backup“ sichern.
