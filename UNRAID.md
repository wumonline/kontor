# Finanzmanager auf Unraid

Der Container liefert die App aus, speichert alle Daten in `/mnt/user/appdata/finanzmanager`
und ruft Umsätze per FinTS bei der Bank ab. Es werden keine Daten an Dritte geschickt,
nur an deine Bank. Die PIN wird nie gespeichert.

## 1. Dateien auf den Server kopieren

Diesen Ordner `finanzmanager` (mit `app`, `server`, `unraid`, `Dockerfile`) auf eine Freigabe kopieren,
zum Beispiel nach `/mnt/user/appdata/finanzmanager-src`. Der Ordner `import-test` wird nicht gebraucht.

## 2. Image bauen

Im Unraid-Terminal (oben rechts `>_`):

```bash
cd /mnt/user/appdata/finanzmanager-src
docker build -t finanzmanager:latest .
```

Nach jedem Update der App-Dateien diesen Befehl wiederholen und den Container neu starten.

## 3. Container anlegen

Vorlage einmalig kopieren:

```bash
cp /mnt/user/appdata/finanzmanager-src/unraid/finanzmanager.xml /boot/config/plugins/dockerMan/templates-user/my-finanzmanager.xml
```

Dann im Reiter **Docker** → **Container hinzufügen** → Vorlage **finanzmanager** wählen:

| Feld | Empfehlung |
|---|---|
| Web-Port | 8090 (oder ein freier Port) |
| Daten | `/mnt/user/appdata/finanzmanager` |
| Passwort | unbedingt setzen, der Benutzername im Anmeldefenster ist beliebig |
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

Die Bank erkennt den Server nach dem ersten Abruf wieder (der Zustand liegt in `appdata/finanzmanager/fints`).
Eine erneute starke Freigabe verlangt sie dann typischerweise erst nach 90 Tagen.

## Sicherheit

- **Passwort setzen.** Ohne Passwort kann jeder im Heimnetz die Finanzdaten sehen.
- Nicht ins Internet freigeben. Für den Zugriff von unterwegs WireGuard (in Unraid eingebaut) nutzen.
- Zwischen Browser und Server läuft die PIN unverschlüsselt über HTTP, solange kein HTTPS davor sitzt.
  Im eigenen Netz ist das vertretbar; mit einem Reverse Proxy (z. B. Nginx Proxy Manager) und HTTPS ist es besser.

## Sicherungen

Der Server legt stündlich eine Kopie in `appdata/finanzmanager/backups` ab und behält die letzten 72.
Den `appdata`-Ordner zusätzlich mit dem Unraid-Plugin „Appdata Backup“ sichern.
