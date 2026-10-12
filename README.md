# Lieferantenkonto & Mahnungs-Tracker

Offline-Desktopanwendung für Windows: ein **Lieferantenkonto (offene Posten)** mit allen Rechnungen, Mahnungen
(Zahlungserinnerung, 1./2./3. Mahnung, Inkasso, Mahnbescheid), Gebühren, Zinsen und Zahlungen – jederzeit mit
korrektem offenem Saldo, vollständigem Verlauf und Abweichungswarnungen. Keine Cloud, keine Registrierung,
keine Zugangsdaten.

> **Zwei Versionen:** Dieser Zweig (`claude/zen-cannon-x8l4cj`) enthält die **SQLite-Version** (Einzelplatz, gemeinsamer Ordner oder optional PostgreSQL-Server).
> Die Version, die **ausschließlich PostgreSQL** verwendet, ist im Zweig [`postgresql-version`](https://github.com/SSAPKOTA1/Invoicing/tree/postgresql-version) gesichert.

> **Wichtig:** Zinssätze, Pauschalen und Zuordnungsregeln sind **Voreinstellungen zur Überprüfung** und
> **keine Rechtsberatung**. Prüfen Sie Basiszinssatz, Aufschläge (B2B 9 Prozentpunkte, B2C 5) und die Verzugspauschale
> (40 €) unter *Einstellungen* selbst.

---

## Für Anwender (nichts installieren)

1. Auf GitHub unter **Actions → (letzter grüner Lauf) → Artifacts** oder unter **Releases** die Datei
   `SupplierApp-windows-x64.zip` herunterladen.
2. ZIP-Datei **entpacken** (z. B. nach `C:\SupplierApp`).
3. `SupplierApp.exe` doppelklicken. Python, Tesseract und Bibliotheken sind bereits enthalten.

**Windows SmartScreen:** Die Anwendung ist nicht signiert. Windows kann deshalb warnen
(„Der Computer wurde durch Windows geschützt“). Klicken Sie auf **„Weitere Informationen“ → „Trotzdem ausführen“**.

### Wo liegen meine Daten?

| Inhalt | Ort |
|---|---|
| Datenbank, Dokumente, Protokolle | `%APPDATA%\SupplierApp\` (Datenbank `supplier.db`, Ordner `documents`, `logs`) |
| Automatische Sicherungen vor Datenbank-Updates | `%APPDATA%\SupplierApp\backups\migrations\` |
| Manuelle Sicherungen (ZIP) | frei wählbar, Vorschlag `%APPDATA%\SupplierApp\backups\` |
| Exporte | `%APPDATA%\SupplierApp\exports\` (Vorschlag) |

Unter *Einstellungen → Pfade* öffnet ein Klick den Datenordner.

### Schnellstart

1. **Einstellungen → Demo-Daten laden** zeigt alle Funktionen mit erfundenen Beispieldaten – oder
2. **Dokumente importieren** (Strg+I) bzw. Dateien per Drag & Drop in den Bereich *Dokumente* ziehen (PDF, PNG, JPG, TIFF, TXT).
3. Die Anwendung liest den Text (PDF-Textebene, sonst OCR), erkennt Dokumentart, Absender, Datum, Beträge und alle
   Referenznummern und **schlägt** eine Zuordnung **vor**. Unsichere Felder sind gelb markiert, ein Klick auf ein Feld zeigt die
   Fundstelle im erkannten Text.
4. Sie prüfen/korrigieren und klicken **„Übernehmen & buchen“**. **Ohne Ihre Bestätigung wird nichts gebucht.**
5. Die Buchungen entstehen, der offene Saldo wird neu berechnet, Abweichungen werden markiert.

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
| Strg+L | sperren (wenn PIN aktiv) |
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

### Mehrbenutzer ohne Server: gemeinsamer Ordner

Für kleine Teams (2–5 Personen) ohne eigenen Server: Alle PCs verwenden **denselben Ordner im Netzwerk** (Freigabe eines immer eingeschalteten Windows-PCs oder NAS, z. B. `\\BUERO-PC\Lieferantenkonto`). Die Programmdateien können dort ebenfalls liegen oder auf jedem PC einzeln.

* Einrichten: auf dem PC mit den bisherigen Daten *Einstellungen → Datenbank / Mehrbenutzer → Daten in einen gemeinsamen Ordner übertragen …* (Ordner muss leer sein, lokale Daten bleiben als Kopie). Auf den anderen PCs: *Verbindung ändern → Mehrbenutzer – gemeinsamer Ordner*. Beim ersten Start den Administrator anlegen; er legt die Kollegen an (Rollen wie im Server-Betrieb).
* Alle Benutzer arbeiten gleichzeitig; Buchungen werden nacheinander verarbeitet (nie zwei Zahlungen auf dieselbe Rechnung, nie doppelte Rechnungsnummern – auch bei gleichzeitigem Klick), Änderungen der Kollegen erscheinen nach wenigen Sekunden, in den Einstellungen sehen Sie, wer gerade verbunden ist.
* Sicherheitsnetz: Die Datenbank wird bei jedem Start geprüft und **täglich automatisch** in `backups\auto` im gemeinsamen Ordner kopiert (die letzten 14 Tage); eine beschädigte Datenbank wird gemeldet statt benutzt. Eine Sicherung zurückspielen geht nur, wenn kein anderer Benutzer verbunden ist.
* **Einschränkungen (bitte lesen):** SQLite ist für Netzlaufwerke nicht gebaut. Es funktioniert zuverlässig nur mit normalen **Windows-Netzwerkfreigaben (SMB)** in einem stabilen Kabel-/WLAN-Netz. **Nicht** verwenden: OneDrive/Dropbox/Google Drive-Ordner (die App lehnt sie ab), NFS, Freigaben über VPN/langsame Leitungen. Bricht die Verbindung während einer Buchung ab, kann die Datenbank im schlimmsten Fall beschädigt werden – dann die letzte Tagessicherung zurückholen. Ab etwa 5 gleichzeitigen Benutzern oder bei Zweifeln den Server-Betrieb (PostgreSQL) wählen.

**Das Programm selbst im gemeinsamen Ordner ablegen:** Entpacken Sie das Paket in einen Unterordner der Freigabe, z. B. `\\PCNAME\Lieferantenkonto\Programm\SupplierApp`, und die Daten bleiben in einem anderen Unterordner (z. B. `\\PCNAME\Lieferantenkonto\Daten`). Auf jedem PC genügt dann eine Verknüpfung auf `SupplierApp.exe` in diesem Ordner. Einmalig, nachdem der Datenordner eingerichtet ist: *Einstellungen → Datenbank / Mehrbenutzer → Ordner für alle PCs hinterlegen* – das legt `connection.json` neben das Programm; jeder PC, der es von dort startet, verwendet automatisch den gemeinsamen Datenordner und fragt nur noch nach der Anmeldung (die Einstellung eines PCs selbst hat Vorrang). Hinweise: Der Start vom Netzlaufwerk ist etwas langsamer; Windows fragt beim ersten Start je PC ggf. nach („Trotzdem ausführen“); zum **Aktualisieren** muss das Programm auf allen PCs geschlossen sein (laufende Programmdateien sind gesperrt), dann den Programmordner ersetzen.

### Mehrbenutzer-Betrieb mit Server (mehrere Personen gleichzeitig)

Die Daten liegen dann **nicht** in einer Datei auf einem PC oder Netzlaufwerk (SQLite ist dafür nicht geeignet), sondern auf einem **PostgreSQL-Server** im Firmennetz. Jeder Benutzer startet die App auf seinem eigenen PC und meldet sich mit eigenem Namen und Passwort an. Änderungen von Kollegen erscheinen nach wenigen Sekunden automatisch; gleichzeitige Buchungen werden sicher nacheinander verarbeitet (keine doppelten Zahlungen, keine doppelten Rechnungsnummern).

**Einmalig auf dem Server-PC (IT):**
1. PostgreSQL 16 oder neuer installieren (kostenlos, postgresql.org) und das Passwort des Administrators `postgres` merken.
2. `scripts/setup_server.sql` öffnen, das Passwort ändern und ausführen: `psql -U postgres -f setup_server.sql` (legt Benutzer und Datenbank `supplierapp` an).
3. Netzwerk freigeben: in `postgresql.conf` `listen_addresses = '*'` (oder die Server-Adresse), in `pg_hba.conf` eine Zeile `hostssl supplierapp supplierapp 192.168.1.0/24 scram-sha-256` (Adressbereich des Firmennetzes anpassen), Port 5432 nur im internen Netz in der Firewall öffnen. Verschlüsselung (`ssl = on` mit Zertifikat) wird empfohlen.

**Auf jedem PC:** Einstellungen → *Datenbank / Mehrbenutzer* → **Verbindung ändern …** → „Mehrbenutzer“ wählen, Server, Datenbank (`supplierapp`), Benutzer und Passwort eintragen, *Verbindung testen*, speichern, App neu starten. Beim allerersten Start legen Sie den Administrator an; dieser legt unter *Einstellungen → Benutzer* die Kollegen an. Rollen: **Administrator** (alles, Benutzer, Server), **Bearbeiter** (importieren, buchen, Berichte), **Lesen** (nur ansehen und drucken; die Datenbank verweigert jede Änderung).

**Bestehende Daten übernehmen:** Auf dem PC mit den bisherigen Daten Einstellungen → *Daten auf einen Server übertragen …* (der Server muss leer sein; die lokalen Daten bleiben als Kopie erhalten). Belege und Dokumentdateien werden mit übertragen.

**Gut zu wissen**
* Dokumentdateien liegen in der Datenbank, jeder PC hält nur einen lokalen Zwischenspeicher.
* Das Datenbank-Passwort wird auf dem jeweiligen PC in `connection.json` gespeichert (Option „Passwort speichern“); die Benutzerpasswörter werden nur als Hash abgelegt. Persönliche Einstellungen (Design, gewählte Gesellschaft/Hotel) bleiben auf dem eigenen PC.
* Sicherung: *Einstellungen → Sicherung* erstellt eine ZIP-Datei mit allen Tabellen und Dokumenten (Wiederherstellen ersetzt die Server-Daten, nur Administratoren). Zusätzlich empfiehlt sich eine nächtliche Sicherung des Servers mit `pg_dump -Fc -U supplierapp supplierapp > supplierapp.dump`.
* Alle PCs müssen dieselbe Programmversion verwenden; ein PC mit neuerer Version aktualisiert die Datenbank beim Start, ältere Versionen melden dann, dass sie aktualisiert werden müssen.
* Die Volltextsuche im Server-Modus findet Wortanfänge ohne Rücksicht auf Groß-/Kleinschreibung und Umlaute (ü = u), arbeitet aber auf dem Wortstamm-freien „simple“-Wörterbuch.
* Ausgelegt für kleine Teams (bis ca. 20 gleichzeitige Benutzer); Buchungen werden aus Sicherheitsgründen serverweit nacheinander ausgeführt.

### PIN-Sperre (optional)

*Einstellungen → Sicherheit*: PIN mit 4–8 Ziffern (scrypt-Hash mit Salt), nach 5 Fehlversuchen steigende Wartezeit, automatische
Sperre nach Leerlauf. Ändern/Deaktivieren verlangt die aktuelle PIN.
**PIN vergessen?** Anwendung schließen, in der Eingabeaufforderung im Programmordner
`SupplierAppConsole.exe --reset-pin` ausführen und die Bestätigung eingeben. Die PIN ist eine Bildschirmsperre – die Daten selbst sind
nicht verschlüsselt.

### Sicherung und Wiederherstellung

*Einstellungen → Sicherung*: erzeugt eine ZIP-Datei mit Datenbank und allen Dokumenten (mit Prüfsummen). Die Wiederherstellung prüft die
Datei, sichert vorher den aktuellen Stand und ersetzt dann die Daten.

### Problemlösung

| Problem | Lösung |
|---|---|
| Keine Texterkennung bei Scans | *Einstellungen → Texterkennung → Prüfen*. Das ausgelieferte Paket enthält Tesseract (Ordner `tesseract`). Ohne ihn werden nur PDFs mit Textebene gelesen. |
| „Datenbank gesperrt“ | Zweite Instanz schließen; die Datenbank wird von nur einer Anwendung genutzt. |
| Speicherplatz knapp | Beim Import erscheint eine Meldung; Dokumente werden nicht kopiert und nichts wird gebucht. |
| Beschädigte PDF/Bilder | Werden mit einer Meldung abgelehnt, die Anwendung läuft weiter. |
| Fehlerdetails | `%APPDATA%\SupplierApp\logs\supplier_app.log` |

---

## Für Entwickler

```bash
python -m venv .venv && . .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m supplier_app                                 # GUI starten
python -m supplier_app --selfcheck                     # Datenbank, Migrationen, alle Screens offscreen (Exit-Code 0)
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
* `database/` – SQLite-Abstraktion (Foreign Keys, WAL, FTS5), nummerierte Migrationen mit automatischer Sicherung und Rollback.
* `ocr/` – PDF-Textebene, Tesseract (`deu+eng`, gebündelt → Einstellungen → PATH), OpenCV-Vorverarbeitung.
* `ai/` – regelbasiert (kein LLM): `DocumentClassifier`, `FieldExtractor`, `ReferenceExtractor`, `SenderMatcher`, `LinkMatcher` hinter Interfaces.
* `reports/` – Berichte und CSV/Excel/PDF-Export, Dashboard-Export (PNG/PDF).
* `i18n/de.json` – alle UI-Texte.

Dokumentation: `docs/DECISIONS.md` (Annahmen), `docs/VERIFICATION.md` (Nachweise), `TASK.md` (Arbeitsstand).

### Paket bauen (Windows)

`scripts/build_exe.ps1` baut mit PyInstaller (`packaging/SupplierApp.spec`), kopiert `tesseract.exe`, DLLs und `deu`/`eng`-Daten nach
`dist\SupplierApp\tesseract` und erzeugt `dist\SupplierApp-windows-x64.zip`. GitHub Actions (`.github/workflows/ci.yml`) führt Tests,
Selbstcheck, Screenshots, Build und Selbstcheck der gebauten EXE aus; `release.yml` hängt das ZIP bei Tags `vX.Y.Z` an ein Release.
