"""English versions of the German messages that the program code produces itself (errors, warnings, labels, booking texts).

The key is the German text exactly as the code writes it; ``{name}`` marks a variable part. :func:`supplier_app.i18n.tx`
looks the text up (and matches texts with variable parts) when the language is not German. Booking texts are stored in
German in the database and are translated only when they are displayed.
"""

from __future__ import annotations

EN: dict[str, str] = {
    # -- command line ----------------------------------------------------------------------------------------
    "Das Passwort von '{username}' wurde geändert.": "The password of '{username}' was changed.",
    "Nur im Mehrbenutzer-Betrieb verfügbar (im Einzelplatz-Modus gibt es keine Benutzer).":
        "Only available in multi-user operation (there are no users in single-PC mode).",
    "Benutzer '{username}' nicht gefunden.": "User '{username}' not found.",
    "Die Passwörter stimmen nicht überein.": "The passwords do not match.",
    # -- backup / restore ------------------------------------------------------------------------------------
    "Das Leeren der Datenbank ist nur für den Server-Modus vorgesehen.": "Clearing the database is only intended for server mode.",
    "Die Ziel-Datenbank enthält bereits Daten und wird nicht überschrieben.": "The target database already contains data and is not overwritten.",
    "Diese Sicherung stammt aus dem Einzelplatz-Modus und kann nicht in den Server eingespielt werden.":
        "This backup comes from single-PC mode and cannot be restored to the server.",
    "Diese Sicherung stammt aus dem Server-Modus und kann nicht in den Einzelplatz-Modus eingespielt werden.":
        "This backup comes from server mode and cannot be restored in single-PC mode.",
    "Die Sicherung stammt von einer neueren Programmversion.": "The backup comes from a newer program version.",
    "Die Sicherung konnte nicht erstellt werden: {exc}": "The backup could not be created: {exc}",
    "Tabelle '{table}' fehlt in der Sicherung.": "Table '{table}' is missing in the backup.",
    "Tabelle '{table}' ist unvollständig (Zeilenzahl stimmt nicht).": "Table '{table}' is incomplete (row count does not match).",
    "Die Wiederherstellung ist fehlgeschlagen: {exc}. Sicherung des alten Stands: {safety}":
        "The restore failed: {exc}. Backup of the previous state: {safety}",
    "Die Datei ist keine lesbare Sicherung: {exc}": "The file is not a readable backup: {exc}",
    "Die Wiederherstellung ist nicht möglich, solange andere Benutzer angemeldet sind: {names}. Bitte alle anderen bitten, das Programm zu schließen.":
        "The restore is not possible while other users are signed in: {names}. Please ask everyone else to close the program.",
    "Die Datei ist keine gültige Sicherung (Manifest oder Datenbank fehlt).": "The file is not a valid backup (manifest or database missing).",
    "Die Sicherung ist beschädigt (Eintrag '{bad}').": "The backup is damaged (entry '{bad}').",
    "Die Sicherung enthält unzulässige Pfade.": "The backup contains invalid paths.",
    "Die Datenbank in der Sicherung ist verändert oder beschädigt (Prüfsumme).": "The database in the backup is modified or damaged (checksum).",
    "Die Datenbank in der Sicherung ist beschädigt.": "The database in the backup is damaged.",
    "Dokument '{name}' fehlt in der Sicherung.": "Document '{name}' is missing in the backup.",
    "Dokument '{name}' ist beschädigt (Prüfsumme).": "Document '{name}' is damaged (checksum).",
    "Die Übertragung ist nur aus dem Einzelplatz-Modus möglich.": "The transfer is only possible from single-PC mode.",
    "Im gemeinsamen Ordner liegt bereits eine Datenbank. Zum Schutz wird nichts überschrieben.":
        "The shared folder already contains a database. Nothing is overwritten for safety.",
    "Der Server enthält bereits Daten. Zum Schutz wird nichts überschrieben.": "The server already contains data. Nothing is overwritten for safety.",
    "Die gemeinsame Datenbank ist beschädigt.": "The shared database is damaged.",
    "Bitte alle Benutzer abmelden und aus dem Ordner '{x}' die letzte Tagessicherung zurückholen.":
        "Please sign out all users and restore the latest daily backup from the folder '{x}'.",
    "Daten wurden von {who} aktualisiert.": "Data was updated by {who}.",
    # -- database --------------------------------------------------------------------------------------------
    "Die Datenbank ist nicht geöffnet.": "The database is not open.",
    "Ihre Benutzerrolle erlaubt nur Lesen. Änderungen sind nicht möglich.": "Your user role allows reading only. Changes are not possible.",
    "Die Datenbank ist gerade durch einen anderen Benutzer belegt.": "The database is currently in use by another user.",
    "Die Datenbank kann nicht geschrieben werden (Speicherplatz voll oder schreibgeschützt).":
        "The database cannot be written to (disk full or write-protected).",
    "Die Datenbank konnte nicht geöffnet werden.": "The database could not be opened.",
    "Bitte versuchen Sie es in wenigen Sekunden erneut.": "Please try again in a few seconds.",
    "Prüfen Sie, ob die Datei von einem anderen Programm gesperrt ist.": "Check whether the file is locked by another program.",
    "Die Datenbank hat Schema-Version {version}, diese Anwendung kennt nur {latest}. Bitte aktualisieren Sie die Anwendung.":
        "The database has schema version {version}, this application only knows {latest}. Please update the application.",
    "Die Datenbank-Aktualisierung (Version {version}) ist fehlgeschlagen. Der vorherige Stand ist unverändert.":
        "The database update (version {version}) failed. The previous state is unchanged.",
    "Die Datenbank-Aktualisierung (Version {version}) ist fehlgeschlagen. Der vorherige Stand wurde wiederhergestellt.":
        "The database update (version {version}) failed. The previous state was restored.",
    "Die Verbindung zum Datenbank-Server wurde unterbrochen.": "The connection to the database server was interrupted.",
    "Der PostgreSQL-Treiber (psycopg) ist nicht installiert.": "The PostgreSQL driver (psycopg) is not installed.",
    "Prüfen Sie Netzwerk und Server; die Anwendung verbindet sich beim nächsten Vorgang neu.":
        "Check the network and the server; the application reconnects with the next operation.",
    "Die Verbindung zum Datenbank-Server ist fehlgeschlagen.": "The connection to the database server failed.",
    "Die Verbindung zum Datenbank-Server wurde während einer Buchung unterbrochen.":
        "The connection to the database server was interrupted during a booking.",
    # -- documents / OCR -------------------------------------------------------------------------------------
    "Dateityp '{suffix}' wird nicht unterstützt.": "File type '{suffix}' is not supported.",
    "Es wurde kein Text erkannt. Bitte Dokument manuell erfassen.": "No text was recognised. Please enter the document manually.",
    "Nur die ersten {pages} Seiten wurden gelesen.": "Only the first {pages} pages were read.",
    "Die Datei '{name}' ist beschädigt oder nicht lesbar.": "The file '{name}' is damaged or unreadable.",
    "Die PDF-Datei '{name}' ist beschädigt und kann nicht geöffnet werden.": "The PDF file '{name}' is damaged and cannot be opened.",
    "Die PDF-Datei '{name}' ist passwortgeschützt.": "The PDF file '{name}' is password-protected.",
    "Das Dokument hat {pages} Seiten; nur {limit} wurden gelesen.": "The document has {pages} pages; only {limit} were read.",
    "Das Bild '{name}' ist zu groß.": "The image '{name}' is too large.",
    "Das Bild '{name}' ist beschädigt und kann nicht geöffnet werden.": "The image '{name}' is damaged and cannot be opened.",
    "Nur die ersten {pages} gescannten Seiten wurden per OCR gelesen.": "Only the first {pages} scanned pages were read by OCR.",
    "Gescannte Seite(n) ohne Text: Tesseract fehlt, keine OCR möglich.": "Scanned page(s) without text: Tesseract is missing, OCR is not possible.",
    "Die Texterkennung hat zu lange gedauert und wurde abgebrochen.": "Text recognition took too long and was cancelled.",
    "Die Texterkennung ist fehlgeschlagen: {exc}": "Text recognition failed: {exc}",
    "Tesseract wurde nicht gefunden. In der ausgelieferten Windows-Version ist Tesseract enthalten (Ordner 'tesseract' neben SupplierApp.exe). Bei einer Entwicklungsinstallation installieren Sie Tesseract (z. B. von https://github.com/UB-Mannheim/tesseract/wiki) inklusive der Sprachdaten 'deu' und 'eng' oder tragen den Pfad unter Einstellungen > Tesseract ein.":
        "Tesseract was not found. The delivered Windows version includes Tesseract (folder 'tesseract' next to SupplierApp.exe). For a development installation, install Tesseract (e.g. from https://github.com/UB-Mannheim/tesseract/wiki) including the language data 'deu' and 'eng', or enter the path under Settings > Tesseract.",
    "Die Datei '{name}' wurde nicht gefunden.": "The file '{name}' was not found.",
    "Dateityp '{suffix}' wird nicht unterstützt (PDF, PNG, JPG, TIFF, TXT).": "File type '{suffix}' is not supported (PDF, PNG, JPG, TIFF, TXT).",
    "Die Datei '{name}' ist leer.": "The file '{name}' is empty.",
    "Die Datei '{name}' ist zu groß (maximal 500 MB).": "The file '{name}' is too large (maximum 500 MB).",
    "Die Datei '{name}' kann nicht gelesen werden: {exc}": "The file '{name}' cannot be read: {exc}",
    "Die Datei konnte nicht kopiert werden (Speicherplatz?): {exc}": "The file could not be copied (disk space?): {exc}",
    "Dokument nicht gefunden.": "Document not found.",
    "'{name}' wurde bereits importiert.": "'{name}' has already been imported.",
    "Dokument ohne ID.": "Document without ID.",
    "Ungültige Suchanfrage.": "Invalid search query.",
    "Dieses Dokument wurde bereits importiert (gleicher Hash).": "This document has already been imported (same hash).",
    "PNG konnte nicht geschrieben werden: {path}": "PNG could not be written: {path}",
    "PDF konnte nicht geschrieben werden: {path}": "PDF could not be written: {path}",
    "Der Drucker konnte nicht geöffnet werden.": "The printer could not be opened.",
    "Seite {x} von {pages}": "Page {x} of {pages}",
    # -- repositories ----------------------------------------------------------------------------------------
    "Für diese Rechnung existiert bereits ein Vorgang.": "A case already exists for this invoice.",
    "Rechnung ohne ID.": "Invoice without ID.",
    "Rechnung '{invoice_number}' existiert für diesen Lieferanten bereits oder ist ungültig.":
        "Invoice '{invoice_number}' already exists for this supplier or is invalid.",
    "Rechnungsnummer ist bereits vergeben oder ungültig.": "The invoice number is already taken or invalid.",
    "Das Hotel gehört nicht zu dieser Gesellschaft.": "The hotel does not belong to this company.",
    "Buchung verletzt eine Ledger-Regel: {exc}": "The booking violates a ledger rule: {exc}",
    "Kategorie '{name}' existiert bereits oder ist leer.": "Category '{name}' already exists or is empty.",
    "Dieses Schreiben wurde bereits erfasst.": "This letter has already been recorded.",
    "Die Gesellschaft hat Hotels, Rechnungen oder Dokumente und kann nicht gelöscht werden.":
        "The company has hotels, invoices or documents and cannot be deleted.",
    "Hotel ohne ID.": "Hotel without ID.",
    "Dem Hotel sind Rechnungen oder Dokumente zugeordnet; es kann nicht gelöscht werden.":
        "Invoices or documents are assigned to the hotel; it cannot be deleted.",
    "Die Gesellschaft '{name}' existiert bereits oder ist leer.": "The company '{name}' already exists or is empty.",
    "Das Hotel '{name}' existiert in dieser Gesellschaft bereits oder ist ungültig.": "The hotel '{name}' already exists in this company or is invalid.",
    "Das Hotel '{name}' existiert in dieser Gesellschaft bereits oder ist leer.": "The hotel '{name}' already exists in this company or is empty.",
    "Partei ohne ID kann nicht aktualisiert werden.": "A party without ID cannot be updated.",
    "Die Partei hat Buchungen und kann nicht gelöscht werden.": "The party has bookings and cannot be deleted.",
    "Der Datensatz '{name}' ist ungültig oder doppelt.": "The record '{name}' is invalid or a duplicate.",
    "Der Benutzername '{username}' ist bereits vergeben oder ungültig.": "The user name '{username}' is already taken or invalid.",
    # -- services: not found ---------------------------------------------------------------------------------
    "Vorgang nicht gefunden.": "Case not found.",
    "Rechnung nicht gefunden.": "Invoice not found.",
    "Absender nicht gefunden.": "Sender not found.",
    "Schreiben nicht gefunden.": "Letter not found.",
    "Buchung nicht gefunden.": "Booking not found.",
    "Gesellschaft nicht gefunden.": "Company not found.",
    "Hotel nicht gefunden.": "Hotel not found.",
    "Lieferant nicht gefunden.": "Supplier not found.",
    "Zahlung nicht gefunden.": "Payment not found.",
    "Partei nicht gefunden.": "Party not found.",
    "Benutzer nicht gefunden.": "User not found.",
    # -- services: invoices ----------------------------------------------------------------------------------
    "Bitte Brutto- oder Nettobetrag angeben.": "Please enter the gross or net amount.",
    "Netto ({a}) + MwSt ({b}) ergibt nicht Brutto ({c}).": "Net ({a}) + VAT ({b}) does not equal gross ({c}).",
    "Bitte einen gültigen Lieferanten wählen.": "Please choose a valid supplier.",
    "Bitte eine Rechnungsnummer angeben.": "Please enter an invoice number.",
    "Der Rechnungsbetrag muss größer als 0 sein.": "The invoice amount must be greater than 0.",
    "Das Fälligkeitsdatum liegt vor dem Rechnungsdatum.": "The due date is before the invoice date.",
    "Rechnung {invoice_number}": "Invoice {invoice_number}",
    "Fälligkeit geändert: {old} → {new}": "Due date changed: {old} → {new}",
    "Der Gutschriftsbetrag muss größer als 0 sein.": "The credit note amount must be greater than 0.",
    "Gutschrift": "Credit note",
    "Gutschrift {invoice_number}": "Credit note {invoice_number}",
    "Der Ausbuchungsbetrag muss zwischen 0 und dem offenen Betrag liegen.": "The write-off amount must be between 0 and the open amount.",
    "Der Korrekturbetrag darf nicht 0 sein.": "The adjustment amount must not be 0.",
    "Bitte eine Begründung für die Korrektur angeben.": "Please give a reason for the adjustment.",
    "Eine stornierte Rechnung kann nicht strittig sein.": "A cancelled invoice cannot be disputed.",
    "Die Rechnung hat Zahlungen. Bitte zuerst die Zahlungen stornieren.": "The invoice has payments. Please reverse the payments first.",
    "Rechnung storniert": "Invoice cancelled",
    "Rechnungsnummer und Rechnungsdatum sind Pflichtfelder.": "Invoice number and invoice date are required.",
    # -- services: payments ----------------------------------------------------------------------------------
    "Die Rechnung gehört nicht zu diesem Lieferanten.": "The invoice does not belong to this supplier.",
    "Rechnung {invoice_number} ist storniert.": "Invoice {invoice_number} is cancelled.",
    "Der Zahlungsbetrag muss größer als 0 sein.": "The payment amount must be greater than 0.",
    "Zahlung {bank_reference}": "Payment {bank_reference}",
    "Guthaben (keiner Rechnung zugeordnet)": "Credit (not assigned to an invoice)",
    "Diese Zahlung wurde bereits storniert.": "This payment has already been reversed.",
    "Zahlung storniert": "Payment reversed",
    "Für diese Zahlung gibt es kein nicht zugeordnetes Guthaben.": "There is no unallocated credit for this payment.",
    "Für die manuelle Zuordnung fehlen die Beträge.": "The amounts for the manual allocation are missing.",
    "Zugeordnete Beträge dürfen nicht negativ sein.": "Allocated amounts must not be negative.",
    "Rechnung {invoice_id} gehört nicht zu dieser Zahlung.": "Invoice {invoice_id} does not belong to this payment.",
    "Zuordnung von {a} übersteigt den offenen Betrag ({b}) der Rechnung.": "Allocation of {a} exceeds the open amount ({b}) of the invoice.",
    "Die zugeordneten Beträge übersteigen den Zahlungsbetrag.": "The allocated amounts exceed the payment amount.",
    # -- services: ledger ------------------------------------------------------------------------------------
    "Stornos werden über reverse_entry gebucht.": "Reversals are booked via reverse_entry.",
    "Eine Stornobuchung kann nicht erneut storniert werden.": "A reversal entry cannot be reversed again.",
    "Diese Buchung wurde bereits storniert.": "This booking has already been reversed.",
    "Zahlungen werden über 'Zahlung stornieren' rückgängig gemacht.": "Payments are undone with 'Reverse payment'.",
    "Storno zu Buchung {id}": "Reversal of booking {id}",
    "Es ist kein Basiszinssatz hinterlegt (Einstellungen > Zinssätze).": "No base interest rate is defined (Settings > Interest rates).",
    # -- services: dunning -----------------------------------------------------------------------------------
    "Das Inkassobüro '{name}' ist keinem Lieferanten zugeordnet. Bitte im Stammdatensatz 'vertritt Lieferant' setzen.":
        "The collection agency '{name}' is not assigned to a supplier. Please set 'represents supplier' in the master record.",
    "Das Schreiben verweist auf keine Rechnung.": "The letter does not refer to any invoice.",
    "Eine Rechnung kommt im Schreiben mehrfach vor.": "An invoice appears more than once in the letter.",
    "Die Rechnung gehört nicht zum Lieferanten des Schreibens.": "The invoice does not belong to the supplier of the letter.",
    "Dieses Schreiben wurde bereits erfasst (gleicher Absender, Datum, Stufe und Beträge).":
        "This letter has already been recorded (same sender, date, level and amounts).",
    "{label}: Rechnung {invoice_number} – {value} im Schreiben um {diff} niedriger als bereits gebucht (keine Buchung erzeugt).":
        "{label}: Invoice {invoice_number} – {value} in the letter is {diff} lower than already booked (no booking created).",
    "{label} von {sender} vom {date}: fordert {amount}": "{label} from {sender} dated {date}: claims {amount}",
    "Frist geändert: {old} → {new}": "Deadline changed: {old} → {new}",
    "Summe der Einzelposten ({a}) weicht vom genannten Gesamtbetrag ({b}) ab.": "Sum of the single items ({a}) differs from the stated total ({b}).",
    "Mahnung fordert {a}, Konto zeigt {b}, Differenz {c}: Gebühr doppelt? Zahlung nicht berücksichtigt?":
        "Reminder claims {a}, account shows {b}, difference {c}: fee charged twice? Payment not taken into account?",
    "{a} über {b}": "{a} for {b}",
    "Zahlung vom {parts} wird im Schreiben nicht (vollständig) berücksichtigt (Gutschrift laut Schreiben: {credit}).":
        "Payment of {parts} is not (fully) taken into account in the letter (credit per letter: {credit}).",
    "Mahnung fordert weniger als das Konto zeigt: {a} statt {b}, Differenz {c}. Gebühren/Zinsen nicht gebucht oder Zahlung berücksichtigt?":
        "Reminder claims less than the account shows: {a} instead of {b}, difference {c}. Fees/interest not booked or payment taken into account?",
    # -- services: ingest ------------------------------------------------------------------------------------
    "Kein Fälligkeitsdatum erkannt – Vorschlag: Rechnungsdatum + {days} Tage. Bitte prüfen oder ändern.":
        "No due date recognised – proposal: invoice date + {days} days. Please check or change.",
    "Bitte einen Lieferanten wählen oder einen neuen Namen angeben.": "Please choose a supplier or enter a new name.",
    "Für eine Gutschrift werden Rechnung, Betrag und Datum benötigt.": "A credit note needs an invoice, an amount and a date.",
    "Für ein Schreiben werden Stufe, Datum und mindestens eine Rechnung benötigt.": "A letter needs a level, a date and at least one invoice.",
    "Der Lieferant des Schreibens ist unbekannt.": "The supplier of the letter is unknown.",
    "Bitte den Absender wählen oder einen neuen Namen angeben.": "Please choose the sender or enter a new name.",
    "Für eine Zahlung werden Lieferant, Betrag und Datum benötigt.": "A payment needs a supplier, an amount and a date.",
    # -- services: master data / organisation / users --------------------------------------------------------
    "Bitte einen Namen für die Gesellschaft angeben.": "Please enter a name for the company.",
    "Bitte einen Namen für das Hotel angeben.": "Please enter a name for the hotel.",
    "Das Hotel gehört nicht zur gewählten Gesellschaft.": "The hotel does not belong to the selected company.",
    "Hotel": "Hotel",
    "Gesellschaft": "Company",
    "Bitte einen Namen angeben.": "Please enter a name.",
    "Die IBAN '{iban}' ist ungültig (Prüfsumme).": "The IBAN '{iban}' is invalid (checksum).",
    "Die USt-IdNr. '{vat_id}' hat ein ungültiges Format.": "The VAT ID '{vat_id}' has an invalid format.",
    "Nur ein Inkassobüro kann einen Lieferanten vertreten.": "Only a collection agency can represent a supplier.",
    "Der vertretene Lieferant existiert nicht.": "The represented supplier does not exist.",
    "Das Passwort muss mindestens {n} Zeichen lang sein.": "The password must be at least {n} characters long.",
    "Nur Administratoren dürfen Benutzer verwalten.": "Only administrators may manage users.",
    "Der Benutzername muss mindestens 2 Zeichen haben und darf keine Leerzeichen enthalten.":
        "The user name must have at least 2 characters and must not contain spaces.",
    "Es muss mindestens ein aktiver Administrator vorhanden bleiben.": "At least one active administrator must remain.",
    "Sie können sich nicht selbst löschen.": "You cannot delete yourself.",
    "Das aktuelle Passwort ist falsch.": "The current password is wrong.",
    "Benutzername oder Passwort ist falsch.": "User name or password is wrong.",
    "Zu viele Fehlversuche. Bitte warten Sie {left} Sekunden.": "Too many failed attempts. Please wait {left} seconds.",
    "Dieser Benutzer ist gesperrt. Bitte wenden Sie sich an einen Administrator.": "This user is locked. Please contact an administrator.",
    "Die PIN muss aus 4 bis 8 Ziffern bestehen.": "The PIN must consist of 4 to 8 digits.",
    "Die aktuelle PIN ist falsch.": "The current PIN is wrong.",
    "Vorgang {cid}": "Case {cid}",
    "Büro": "Office",
    "Unbekannte Sprache.": "Unknown language.",
    "Unbekanntes Design.": "Unknown theme.",
    "Material": "Material",
    "Dienstleistung": "Services",
    "Software": "Software",
    "Sonstiges": "Other",
    # -- connection settings ---------------------------------------------------------------------------------
    "Bitte den Namen oder die Adresse des Datenbank-Servers angeben.": "Please enter the name or address of the database server.",
    "Der Port muss zwischen 1 und 65535 liegen.": "The port must be between 1 and 65535.",
    "Bitte Datenbankname und Benutzer des Servers angeben.": "Please enter the database name and user of the server.",
    "Datenbank-Server": "Database server",
    "Das Programm läuft nicht aus einem Programmordner (nur im installierten Paket möglich).":
        "The program is not running from a program folder (only possible in the installed package).",
    "Für Server-Verbindungen bitte das Datenbank-Passwort nicht neben dem Programm ablegen.":
        "For server connections, please do not store the database password next to the program.",
    "In den Programmordner kann nicht geschrieben werden: {exc}": "The program folder cannot be written to: {exc}",
    "Bitte den gemeinsamen Ordner (Netzlaufwerk) angeben.": "Please enter the shared folder (network drive).",
    "Dieser Ordner wird von einem Cloud-Dienst (OneDrive, Dropbox …) synchronisiert. Dort wird die Datenbank beschädigt. Bitte einen normalen Ordner auf einem Netzlaufwerk oder Server-PC wählen.":
        "This folder is synchronised by a cloud service (OneDrive, Dropbox …). The database would be damaged there. Please choose a normal folder on a network drive or server PC.",
    "Der Ordner '{text}' ist nicht erreichbar. Prüfen Sie Netzwerk und Laufwerksverbindung.":
        "The folder '{text}' is not reachable. Check the network and drive connection.",
    "In den Ordner '{text}' kann nicht geschrieben werden: {exc}": "The folder '{text}' cannot be written to: {exc}",
    "Ungültiges Datum: '{text}'": "Invalid date: '{text}'",
    "Ungültiger Betrag: '{text}'": "Invalid amount: '{text}'",
    # -- dashboard -------------------------------------------------------------------------------------------
    "Frist {a} · {b}": "Deadline {a} · {b}",
    "Schreiben {nid}: Differenz {a}": "Letter {nid}: difference {a}",
    "Zahlung vom {a} nicht zugeordnet": "Payment of {a} not allocated",
    "{a} – {invoice_number}: Überzahlung": "{a} – {invoice_number}: overpayment",
    "gleicher Betrag {a} innerhalb von 14 Tagen": "same amount {a} within 14 days",
    "Dokument importiert": "Document imported",
    "Dokument übernommen": "Document accepted",
    "Dokument geprüft": "Document reviewed",
    "Rechnung angelegt": "Invoice created",
    "Mahnung gebucht": "Reminder booked",
    "Zahlung erfasst": "Payment recorded",
    "Buchung storniert": "Booking reversed",
    "Vorgang eröffnet": "Case opened",
    "Vorgangsstatus geändert": "Case status changed",
    "Guthaben (Zahlung)": "Credit (payment)",
    "Lieferant": "Supplier",
    "Rechnung": "Invoice",
    "Stufe": "Level",
    "Vorgang": "Case",
    "Dokument": "Document",
    "Fällig": "Due",
    "Betrag": "Amount",
    "Saldo": "Balance",
    "keine Daten": "no data",
    "{invoice_number} · fällig {a} · offen {b}": "{invoice_number} · due {a} · open {b}",
    # -- reports ---------------------------------------------------------------------------------------------
    "Haben": "Credit",
    "Soll": "Debit",
    "Tage überfällig": "Days overdue",
    "Fälligkeit": "Due date",
    "Gebühren/Zinsen": "Fees/interest",
    "Bezahlt/Gutschrift": "Paid/credit note",
    "Hotel / Gesellschaft": "Hotel / company",
    "Fälligkeitsstruktur": "Aging structure",
    "Rechnung(en)": "Invoice(s)",
    "Konto (erwartet)": "Account (expected)",
    "Zinsen gefordert": "Interest claimed",
    "Zinsen berechnet": "Interest calculated",
    "Mahnübersicht: gefordert vs. berechnet": "Dunning overview: claimed vs. calculated",
    "Nicht zugeordnet": "Not allocated",
    "Für das Kontoblatt wird ein Lieferant benötigt.": "A supplier is required for the account statement.",
    "Übertrag": "Carried forward",
    "Summe / Schlusssaldo": "Total / closing balance",
    "Übersicht": "Overview",
    "Summe": "Total",
    # -- booking descriptions stored in German ---------------------------------------------------------------
    "Zahlung": "Payment",
    "Mahngebühr": "Dunning fee",
    "Verzugszinsen": "Late-payment interest",
    "Verzugspauschale": "Late-payment flat fee",
    "Inkassokosten": "Collection costs",
    "Korrektur": "Adjustment",
    "Ausbuchung": "Write-off",
    "Storno": "Reversal",
}

EN.update({
    "{a}: Guthaben {b}": "{a}: credit {b}",
    "{n} % Sicherheit": "{n} % confidence",
    "Stammdaten angelegt": "Master data created",
    "Guthaben zugeordnet": "Credit allocated",
    "Rechnungen": "Invoices",
    "Zahlungen": "Payments",
    "Datum": "Date",
    "Art": "Type",
    "Text": "Text",
    "Status": "Status",
    "Offen": "Open",
    "Guthaben": "Credit",
    "Differenz": "Difference",
    "Hinweis": "Note",
    "Sicherheit": "Confidence",
    "Typ": "Type",
    "Rechnungsdatum": "Invoice date",
    "Rechnungsbetrag": "Invoice amount",
    "Saldovortrag": "Balance brought forward",
    "Kontoblatt {name}": "Account statement {name}",
    "bis {date}": "until {date}",
    "gesamter Zeitraum": "entire period",
})

EN.update({
    "Offene Posten – {name}": "Open items – {name}",
    "alle Lieferanten": "all suppliers",
    "Stichtag {date}": "As of {date}",
    "Absender": "Sender",
    "Gefordert": "Claimed",
    "Pauschale gefordert": "Flat fee claimed",
    "Pauschale berechnet": "Flat fee calculated",
    "Zugeordnete Rechnungen": "Allocated invoices",
    "Verwendungszweck": "Payment reference",
    "storniert": "reversed",
    "gebucht": "booked",
    "Zahlungen": "Payments",
})

EN.update({
    "Datenbankfehler: {exc}": "Database error: {exc}",
    "Unbekannte Buchungsart.": "Unknown booking type.",
    "Beispieldaten sind im Mehrbenutzer-Betrieb nicht verfügbar (gemeinsame Firmendaten).":
        "Demo data is not available in multi-user operation (shared company data).",
    "Unbekannter Betriebsmodus.": "Unknown operating mode.",
})

EN.update({
    "Alle Gesellschaften": "All companies",
    "{name} (alle Hotels)": "{name} (all hotels)",
})

EN.update({
    "Netto": "Net",
    "MwSt": "VAT",
    "Brutto": "Gross",
    "Die MwSt ({a}) passt nicht zu {rate} % von {b}.": "The VAT ({a}) does not match {rate} % of {b}.",
    "{names} wurde aus den übrigen Beträgen berechnet und nicht im Dokument gelesen – bitte prüfen.":
        "{names} was calculated from the other amounts and not read from the document – please check.",
    "Kein Rechnungs-/Gutschriftsbetrag erkannt.": "No invoice/credit note amount recognised.",
    "Keine Rechnungsnummer erkannt.": "No invoice number recognised.",
    "Gesamtforderung {a} weicht von der Summe der Einzelposten {b} ab (Differenz {c}).":
        "Total claim {a} differs from the sum of the single items {b} (difference {c}).",
    "Gesamtforderung − Zahlung ({a}) ergibt nicht den Restbetrag {b}.": "Total claim − payment ({a}) does not equal the remaining amount {b}.",
    "Keine Gesamtforderung erkannt.": "No total claim recognised.",
    "Kein Zahlungsbetrag erkannt.": "No payment amount recognised.",
    "Das Dokumentdatum liegt in der Zukunft.": "The document date is in the future.",
    "Das Dokumentdatum ist unplausibel alt.": "The document date is implausibly old.",
    "Die Fälligkeit liegt vor dem Rechnungsdatum.": "The due date is before the invoice date.",
    "Die Zahlungsfrist liegt vor dem Schreibendatum.": "The payment deadline is before the date of the letter.",
    "Kein Datum erkannt.": "No date recognised.",
    "IBAN '{raw}' hat eine ungültige Prüfsumme (OCR-Fehler?).": "IBAN '{raw}' has an invalid checksum (OCR error?).",
    "USt-IdNr. '{raw}' hat ein ungültiges Format.": "VAT ID '{raw}' has an invalid format.",
    "Rechnung {invoice_number} ist bereits erfasst.": "Invoice {invoice_number} has already been recorded.",
    "Keine passende Rechnung gefunden. Bitte manuell zuordnen.": "No matching invoice found. Please allocate manually.",
})

EN.update({
    "IBAN": "IBAN",
    "USt-IdNr.": "VAT ID",
    "Steuernummer": "tax number",
    "E-Mail-Adresse": "e-mail address",
    "E-Mail-/Web-Domain": "e-mail / web domain",
    "Name ({where}, {pct} %)": "name ({where}, {pct} %)",
    "Absenderzeile": "sender line",
    "Briefkopf": "letterhead",
    "Fußzeile": "footer",
    "Text": "text",
    "Name im Text": "name in the text",
    "mehrdeutig": "ambiguous",
    "vom Inkassobüro vertretener Lieferant": "supplier represented by the collection agency",
    "Zahlungsempfänger: {reasons}": "payee: {reasons}",
    "Rechnungsnummer {invoice_number} im Dokument": "invoice number {invoice_number} in the document",
    "Rechnungsnummer {invoice_number} (abweichende Schreibweise)": "invoice number {invoice_number} (different spelling)",
    "bekannte Referenz {ref}": "known reference {ref}",
    "Betrag {amount} entspricht der Rechnung": "amount {amount} matches the invoice",
    "Rechnungsdatum stimmt überein": "invoice date matches",
    "gleicher Lieferant": "same supplier",
    "anderer Lieferant": "different supplier",
    "Zahlung entspricht dem offenen Betrag": "payment equals the open amount",
})

EN.update({
    "Dem Schreiben ist keine Rechnung zugeordnet.": "No invoice is assigned to the letter.",
    "Der Gutschrift ist keine Rechnung zugeordnet.": "No invoice is assigned to the credit note.",
    "Der Zahlung ist keine Rechnung zugeordnet.": "No invoice is assigned to the payment.",
    "Dieses Dokument wurde bereits übernommen.": "This document has already been accepted.",
    "Bitte den Lieferanten des Dokuments wählen oder einen neuen Namen angeben.": "Please choose the supplier of the document or enter a new name.",
    "Dokument ohne Rechnung abgelegt": "Document filed without invoice",
    "Zuordnung der Rechnung": "Invoice assigned",
})

EN.update({
    "Eine stornierte Rechnung kann nicht umgebucht werden.": "A cancelled invoice cannot be rebooked.",
    "Die Rechnung hat bereits Zahlungen oder weitere Buchungen. Bitte zuerst diese stornieren, dann kann der Lieferant geändert werden.":
        "The invoice already has payments or further postings. Please reverse them first, then the supplier can be changed.",
    "Zur Rechnung gibt es Mahnungen oder Schreiben. Der Lieferant kann nicht mehr geändert werden.":
        "There are reminders or letters for this invoice. The supplier can no longer be changed.",
    "Der Lieferant '{name}' hat bereits eine Rechnung mit der Nummer '{number}'.":
        "The supplier '{name}' already has an invoice with the number '{number}'.",
    "Lieferant geändert: {old} → {new}": "Supplier changed: {old} → {new}",
    "Das Inkassobüro '{name}' vertritt einen anderen Lieferanten als den des Schreibens. Bitte im Stammdatensatz 'vertritt Lieferant' prüfen.":
        "The collection agency '{name}' represents a different supplier than the one of the letter. Please check 'represents supplier' in its master data.",
    "Das Schreiben gehört zum Lieferanten '{name}'. Als Absender kommen dieser Lieferant oder ein von ihm beauftragtes Inkassobüro in Frage.":
        "The letter belongs to the supplier '{name}'. Its sender can be this supplier or a collection agency it has appointed.",
})
