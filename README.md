# Lieferantenkonto & Mahnungs-Tracker

Offline-Desktopanwendung für Windows: ein **Lieferantenkonto (offene Posten)** mit allen Rechnungen, Mahnungen
(Zahlungserinnerung, 1./2./3. Mahnung, Inkasso, Mahnbescheid), Gebühren, Zinsen und Zahlungen – jederzeit mit
korrektem offenem Saldo, vollständigem Verlauf und Abweichungswarnungen. Keine Cloud, keine Registrierung,
keine Zugangsdaten.

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
