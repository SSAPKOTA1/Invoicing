# Lieferantenkonto & Mahnungs-Tracker

Desktopanwendung für Windows: ein **Lieferantenkonto (offene Posten)** mit allen Rechnungen, Mahnungen
(Zahlungserinnerung, 1./2./3. Mahnung, Inkasso, Mahnbescheid), Gebühren, Zinsen und Zahlungen – jederzeit mit
korrektem offenem Saldo, vollständigem Verlauf und Abweichungswarnungen. Mehrere Benutzer arbeiten gleichzeitig
mit denselben Daten. Keine Cloud, keine Registrierung: Die Daten liegen auf einem **PostgreSQL-Server in Ihrem eigenen Netz**
(das kann auch ein normaler PC sein, der immer eingeschaltet ist – auch bei nur einem Benutzer).

> **Wichtig:** Zinssätze, Pauschalen und Zuordnungsregeln sind **Voreinstellungen zur Überprüfung** und
> **keine Rechtsberatung**. Prüfen Sie Basiszinssatz, Aufschläge (B2B 9 Prozentpunkte, B2C 5) und die Verzugspauschale
> (40 €) unter *Einstellungen* selbst.

---

## Für Anwender

**Es gibt genau eine Datenbank: PostgreSQL.** Vor der ersten Nutzung braucht die Firma *einmalig* einen PostgreSQL-Server
(siehe unten, ca. 15 Minuten). Die Anwendung selbst muss nicht installiert werden:

1. Auf GitHub unter **Actions → (letzter grüner Lauf) → Artifacts** oder unter **Releases** die Datei
   `SupplierApp-windows-x64.zip` herunterladen.
2. ZIP-Datei **entpacken** – auf den eigenen PC (z. B. `C:\SupplierApp`) **oder in die gemeinsame Netzwerkfreigabe**
   (z. B. `\\PCNAME\Lieferantenkonto\Programm`); dann braucht jeder PC nur eine Verknüpfung auf `SupplierApp.exe`.
3. `SupplierApp.exe` doppelklicken. Beim ersten Start fragt die Anwendung nach dem Server (Name, Datenbank, Benutzer, Passwort);
   danach legt der Erste den **Administrator** an. Python, Tesseract und Bibliotheken sind bereits enthalten.

**Windows SmartScreen:** Die Anwendung ist nicht signiert. Windows kann deshalb warnen
(„Der Computer wurde durch Windows geschützt“). Klicken Sie auf **„Weitere Informationen“ → „Trotzdem ausführen“**.

### PostgreSQL-Server einrichten (einmalig, IT)

Der Server kann auf dem PC oder NAS laufen, das auch die Freigabe mit dem Programm bereitstellt; er muss während der Arbeitszeit
eingeschaltet sein.

1. PostgreSQL 16 oder neuer installieren (kostenlos, postgresql.org; Windows-Installer, Standardwerte) und das Passwort des Administrators `postgres` merken.
2. `scripts/setup_server.sql` öffnen, das Passwort ändern und ausführen: `psql -U postgres -f setup_server.sql` (legt Benutzer und Datenbank `supplierapp` an).
3. Netzwerk freigeben: in `postgresql.conf` `listen_addresses = '*'` (oder die Server-Adresse), in `pg_hba.conf` eine Zeile `host supplierapp supplierapp 192.168.1.0/24 scram-sha-256` (mit Zertifikat `hostssl`; Adressbereich des Firmennetzes anpassen), Port 5432 nur im internen Netz in der Firewall öffnen. PostgreSQL-Dienst neu starten.

**Auf jedem PC:** beim ersten Start (oder später *Einstellungen → Datenbank → Verbindung ändern …*) Server, Datenbank (`supplierapp`), Benutzer und Passwort eintragen, *Verbindung testen*, speichern. Die Tabellen legt die Anwendung beim ersten Start selbst an.

**Programm im gemeinsamen Ordner:** Ist die Anwendung in einer Freigabe abgelegt, trägt der Administrator einmalig *Einstellungen → Datenbank → Server für alle PCs hinterlegen* ein. Das legt `connection.json` (ohne Passwort) neben `SupplierApp.exe`; jeder PC, der das Programm von dort startet, kennt den Server und fragt nur noch nach dem Datenbank-Passwort und der Anmeldung. Hinweise: Der Start vom Netzlaufwerk ist etwas langsamer; zum **Aktualisieren** muss das Programm auf allen PCs geschlossen sein (laufende Programmdateien sind gesperrt), dann den Programmordner ersetzen.

**Daten der früheren Version (`supplier.db`, Einzelplatz) übernehmen:** *Einstellungen → Datenbank → Daten der früheren Version importieren …* (nur in eine leere Datenbank; die Datei bleibt unverändert; Rechnungen, Mahnungen, Zahlungen, Gesellschaften/Hotels und Dokumente werden übernommen, eine frühere PIN und persönliche Einstellungen nicht).

### Wo liegen meine Daten?

| Inhalt | Ort |
|---|---|
| Rechnungen, Buchungen, Benutzer, **Dokumentdateien** | PostgreSQL-Datenbank auf dem Server |
| Verbindungseinstellungen, persönliche Einstellungen (Design, gewählte Gesellschaft/Hotel), Zwischenspeicher der Dokumente, Protokolle | `%APPDATA%\SupplierApp\` auf dem jeweiligen PC (`connection.json`, `prefs.json`, `documents`, `logs`) |
| Manuelle Sicherungen (ZIP) | frei wählbar, Vorschlag `%APPDATA%\SupplierApp\backups\` |

Unter *Einstellungen → Pfade* öffnet ein Klick den lokalen Ordner. Das Datenbank-Passwort wird nur auf Wunsch (Option „Passwort speichern“) in `connection.json` abgelegt; Benutzerpasswörter liegen nur als Hash in der Datenbank.

### Schnellstart

1. **Dokumente importieren** (Strg+I) bzw. Dateien per Drag & Drop in den Bereich *Dokumente* ziehen (PDF, PNG, JPG, TIFF, TXT).
2. Die Anwendung liest den Text (PDF-Textebene, sonst OCR), erkennt Dokumentart, Absender, Datum, Beträge und alle
   Referenznummern und **schlägt** eine Zuordnung **vor**. Unsichere Felder sind gelb markiert, ein Klick auf ein Feld zeigt die
   Fundstelle im erkannten Text.
3. Sie prüfen/korrigieren und klicken **„Übernehmen & buchen“**. **Ohne Ihre Bestätigung wird nichts gebucht.**
4. Die Buchungen entstehen, der offene Saldo wird neu berechnet, Abweichungen werden markiert.

### Wichtige Regeln der Buchhaltung

* Eine **Mahnung ist keine neue Schuld.** Ihre Gesamtsumme wiederholt die offene Rechnung plus Gebühren/Zinsen. Gebucht werden nur
  *zusätzliche* Gebühren, Zinsen, Pauschalen und Inkassokosten – wiederholt eine spätere Mahnung eine frühere Gebühr, entsteht sie nicht doppelt.
* Buchungen sind **unveränderlich** (nur Anhängen). Korrekturen erfolgen durch **Stornobuchungen**.
* **Zahlungen** werden standardmäßig nach § 367 BGB zugeordnet (Kosten → Zinsen → Hauptforderung); alternativ älteste Rechnung zuerst
  oder manuell. Teilzahlungen aktualisieren den Status automatisch; Überzahlungen erscheinen als **Guthaben**.
* Pro Schreiben vergleicht die Anwendung **„Gefordert“ mit „Konto zeigt“** und warnt, z. B.
  „Mahnung fordert 1.015,00 €, Konto zeigt 1.005,00 €, Differenz 10,00 €: Gebühr doppelt? Zahlung nicht berücksichtigt?“.

### Bedienung

| Taste | Aktion |
|---|---|
| Strg+K / Strg+F | globale Suche (Firma, Rechnungsnummer, Aktenzeichen, IBAN, Betrag, Volltext; Satzzeichen egal: `RE-2024/001` findet `re2024001`) |
| Strg+I | Dokumente importieren |
| Strg+P | Zahlung erfassen |
| Strg+N | neuer Lieferant |
| Strg+1 … Strg+7 | Bereiche der Navigation |
| Strg+T | Hell/Dunkel umschalten |
| Strg+L | sperren (Entsperren mit dem eigenen Passwort) |
| F5 | aktualisieren |

### Gesellschaften und Hotels

* **Einstellungen → Gesellschaften & Hotels**: Gesellschaften anlegen und ihnen Hotels zuordnen (Umbenennen/Löschen; Löschen nur ohne zugeordnete Belege).
* **Zuordnung**: Eine Rechnung/Zahlung/ein Dokument gehört zu einem **Hotel** (die Gesellschaft ergibt sich automatisch) oder nur zu einer **Gesellschaft**. Beim Import, in „Rechnung erfassen“ und später über **Zuordnung ändern …** im Vorgang einstellbar. Beim Import wird das Hotel anhand des Empfängers im Text vorgeschlagen.
* **Ansicht** (oben rechts): *Alle Gesellschaften*, *Gesellschaft (alle Hotels)* oder *einzelnes Hotel*. Der Filter wirkt auf **alle** Bereiche – Übersicht, Lieferanten, Vorgänge, Dokumente, Buchungen, Berichte, Suche – und wird beim nächsten Start wiederhergestellt. Nicht zugeordnete Dokumente bleiben in jeder Ansicht sichtbar, damit nichts verloren geht.

### Fälligkeitsdatum

Beim Import steht im Prüfformular das Feld **Fälligkeitsdatum** (mit Schaltflächen +14 / +30 / +60 Tage). Wird keins erkannt, wird *Rechnungsdatum + Zahlungsziel* vorgeschlagen und als unsicher markiert. Später änderbar im Vorgang: **Fälligkeit ändern …** (Rechnung) und **Frist ändern …** (markierte Mahnung); jede Änderung wird protokolliert.

### Erkennung von Rechnungen

Die Erkennung kennt Rechnungen auf Deutsch, Englisch, Französisch, Italienisch, Spanisch und Niederländisch: Überschriften wie *Rechnung, Beleg, Faktura, Honorarnote, Abrechnung, Invoice, Tax invoice, Facture, Fattura, Factura, Factuur*; Beträge als *Netto / Brutto / MwSt*, *Summe, Gesamt, Total, Gesamtbetrag, Endsumme, Zu zahlen, Rechnungsbetrag*, *Montant HT / Total TTC / TVA*, *Imponibile / IVA / Totale*, *Base imponible / Total factura*, *Subtotaal / BTW / Totaal*; Zahlen in Tabellen (Spalten „Netto – MwSt – Brutto“, Summenzeile „Gesamt 100,00 19,00 119,00“), mehrere Steuersätze, Zahlformate wie `1.234,56`, `1 234,56`, `1'234.56`, `1,234.56`; Daten wie `15.03.2024`, `15/03/24`, `15 March 2024`, `15 mars 2024`; Zahlungsziele wie *30 Tage netto*, *Net 30*, *Zahlbar bis …*, *sofort fällig* (Skonto-Daten werden nicht als Fälligkeit gelesen).
Netto, MwSt und Brutto werden gegeneinander geprüft (Netto + MwSt = Brutto). Fehlt ein Wert, wird er berechnet und im Prüfformular als „berechnet“ markiert. Eigene Begriffe für einzelne Lieferanten tragen Sie unter **Einstellungen → Erkennung: eigene Begriffe** ein.

### Berichte drucken

Berichte → **Druckvorschau …** / **Drucken …**: A4 mit Kopfzeile (Titel, Filter, Gesellschaft/Hotel), wiederholter Tabellenkopf auf jeder Seite und „Seite x von y“. Breite Tabellen werden quer gedruckt (in der Vorschau/im Druckdialog änderbar). Über einen PDF-Drucker lässt sich auch eine PDF-Datei erzeugen.

### Mehrere Benutzer gleichzeitig

Jeder Benutzer startet die Anwendung auf seinem eigenen PC und meldet sich mit eigenem Namen und Passwort an. Änderungen von Kollegen erscheinen nach wenigen Sekunden automatisch; gleichzeitige Buchungen werden sicher nacheinander verarbeitet (keine doppelten Zahlungen, keine doppelten Rechnungsnummern). Beim allerersten Start legen Sie den Administrator an; dieser legt unter *Einstellungen → Benutzer* die Kollegen an. Rollen: **Administrator** (alles, Benutzer, Server), **Bearbeiter** (importieren, buchen, Berichte), **Lesen** (nur ansehen und drucken; die Datenbank verweigert jede Änderung). Nach 5 falschen Passwörtern wird ein Benutzer gesperrt; der Administrator entsperrt ihn. Ein vergessenes Administrator-Passwort setzt `SupplierAppConsole.exe --set-password BENUTZER` zurück (auf einem PC mit Datenbankzugang).

* Die Anwendung sperrt sich nach einstellbarer Leerlaufzeit (*Einstellungen → Sicherheit*); zum Entsperren genügt das eigene Passwort.
* Alle PCs müssen dieselbe Programmversion verwenden; ein PC mit neuerer Version aktualisiert die Datenbank beim Start, ältere Versionen melden dann, dass sie aktualisiert werden müssen.
* Die Volltextsuche findet Wortanfänge ohne Rücksicht auf Groß-/Kleinschreibung und Umlaute (ü = u).
* Ausgelegt für kleine Teams (bis ca. 20 gleichzeitige Benutzer); Buchungen werden aus Sicherheitsgründen serverweit nacheinander ausgeführt.

### Sicherung und Wiederherstellung

*Einstellungen → Sicherung*: erzeugt eine ZIP-Datei mit allen Tabellen und Dokumenten (mit Prüfsummen). Die Wiederherstellung (nur Administratoren) prüft die
Datei, sichert vorher den aktuellen Stand und ersetzt dann die Daten. Zusätzlich empfiehlt sich eine nächtliche Sicherung des Servers, z. B. mit
`pg_dump -Fc -U supplierapp supplierapp > supplierapp.dump` (Windows-Aufgabenplanung).

**Daten ohne das Programm ansehen:** mit jedem PostgreSQL-Werkzeug (pgAdmin, DBeaver, `psql`) und denselben Zugangsdaten; Tabellen z. B. `invoices`, `ledger_entries`, `payments`, `parties`.

### Problemlösung

| Problem | Lösung |
|---|---|
| Keine Texterkennung bei Scans | *Einstellungen → Texterkennung → Prüfen*. Das ausgelieferte Paket enthält Tesseract (Ordner `tesseract`). Ohne ihn werden nur PDFs mit Textebene gelesen. |
| „Der Datenbank-Server ist nicht erreichbar“ | Läuft der Server-PC? Stimmen Name/Adresse, Port 5432 (Firewall) und Passwort? Unter *Verbindung ändern …* mit *Verbindung testen* prüfen. |
| „Die Datenbank ist gerade belegt“ | Ein Kollege bucht gerade; nach einigen Sekunden erneut versuchen. |
| Speicherplatz knapp | Beim Import erscheint eine Meldung; Dokumente werden nicht kopiert und nichts wird gebucht. |
| Beschädigte PDF/Bilder | Werden mit einer Meldung abgelehnt, die Anwendung läuft weiter. |
| Fehlerdetails | `%APPDATA%\SupplierApp\logs\supplier_app.log` |

---

## Für Entwickler

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m supplier_app                                 # GUI starten
# alle Befehle brauchen einen PostgreSQL-Server; Verbindung z. B. per Umgebungsvariable:
export SUPPLIERAPP_PG_DSN="host=localhost user=postgres password=... dbname=postgres"   # Programm / --selfcheck / --screenshots
export SUPPLIER_TEST_PG_DSN="$SUPPLIERAPP_PG_DSN"                                         # Tests (legen je Test eine eigene Datenbank an)
python -m supplier_app --selfcheck                     # Datenbank (Wegwerf-Schema), Migrationen, alle Screens offscreen (Exit-Code 0)
QT_QPA_PLATFORM=offscreen python -m pytest --cov=supplier_app
python -m supplier_app --screenshots artifacts/screenshots   # Screenshots (Demo-Daten, dunkel + hell)
python scripts/generate_fixtures.py                    # synthetische Test-PDFs/-Scans neu erzeugen
```

Für OCR-Tests wird Tesseract mit `deu` und `eng` benötigt (Linux: `apt-get install tesseract-ocr tesseract-ocr-deu`); ohne Tesseract werden
diese Tests mit Begründung übersprungen.

### Architektur

`views → controllers → services → repositories → database`, Modelle sind Dataclasses/Enums.

* `services/ledger/` – **reine** Ledger-Engine (kein DB-/Qt-Zugriff): Salden, Zahlungszuordnung, Mahnungsbuchungen, Abgleich,
  Verzugszinsen (Basiszins + Aufschlag, act/365, `Decimal` ROUND_HALF_UP), Altersstruktur. Geld = ganzzahlige Cent.
* `database/` – PostgreSQL-Zugriff (psycopg 3): `?`-Platzhalter, Transaktionen mit Savepoint je Schreibbefehl, globale Advisory-Lock für Schreibvorgänge, Änderungszähler für die Live-Aktualisierung; nummerierte Migrationen (transaktionelles DDL, Trigger für das unveränderliche Hauptbuch, Volltextindex).
* `ocr/` – PDF-Textebene, Tesseract (`deu+eng`, gebündelt → Einstellungen → PATH), OpenCV-Vorverarbeitung.
* `ai/` – regelbasiert (kein LLM): `DocumentClassifier`, `FieldExtractor`, `ReferenceExtractor`, `SenderMatcher`, `LinkMatcher` hinter Interfaces.
* `reports/` – Berichte und CSV/Excel/PDF-Export, Dashboard-Export (PNG/PDF).
* `i18n/de.json` – alle UI-Texte.

Dokumentation: `docs/DECISIONS.md` (Annahmen), `docs/VERIFICATION.md` (Nachweise), `TASK.md` (Arbeitsstand).

### Paket bauen (Windows)

`scripts/build_exe.ps1` baut mit PyInstaller (`packaging/SupplierApp.spec`), kopiert `tesseract.exe`, DLLs und `deu`/`eng`-Daten nach
`dist\SupplierApp\tesseract` und erzeugt `dist\SupplierApp-windows-x64.zip`. GitHub Actions (`.github/workflows/ci.yml`; Windows-Lauf mit PostgreSQL via `scripts/ci_postgres_windows.ps1`, Linux-Lauf mit PostgreSQL-Container und Coverage-Schwellen) führt Tests,
Selbstcheck, Screenshots, Build und Selbstcheck der gebauten EXE aus; `release.yml` hängt das ZIP bei Tags `vX.Y.Z` an ein Release.
