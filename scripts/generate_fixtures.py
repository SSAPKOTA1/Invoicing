"""Generate synthetic German test documents (PDF with text layer + scanned-style PNG/JPG + texts).

Only invented companies and data. Run:  python scripts/generate_fixtures.py [output_dir]
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz  # PyMuPDF
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

DEBTOR = ["Beispiel Handels GmbH", "Hauptstraße 12", "10115 Berlin"]


@dataclass
class Doc:
    name: str
    sender: list[str]
    lines: list[str]
    footer: list[str] = field(default_factory=list)


MUELLER = ["Müller Bürobedarf GmbH", "Industrieweg 5 · 80331 München", "Tel. 089 1234567 · info@mueller-buero.example"]
MUELLER_FOOT = [
    "Müller Bürobedarf GmbH · Geschäftsführer: Hans Müller · Amtsgericht München HRB 123456",
    "USt-IdNr. DE123456789 · Bankverbindung: IBAN DE89 3704 0044 0532 0130 00 · BIC COBADEFFXXX",
]
INKASSO = ["Inkasso Schmidt & Partner GmbH", "Postfach 10 20 30 · 50667 Köln", "Tel. 0221 998877 · service@inkasso-schmidt.example"]
INKASSO_FOOT = ["Inkasso Schmidt & Partner GmbH · Sitz Köln · USt-IdNr. DE987654321",
                "Bankverbindung: IBAN DE02 1203 0000 0000 2020 51 · BIC BYLADEM1001"]

DOCS: list[Doc] = [
    Doc("invoice_RE-2024-001", MUELLER, [
        "Rechnung", "",
        "Rechnungsnummer: RE-2024/001", "Rechnungsdatum: 10.01.2024", "Kundennummer: K-4711",
        "Bestellnummer: B-2023-889", "Leistungsdatum: Januar 2024", "",
        "Pos.  Beschreibung                         Menge   Einzelpreis      Gesamt",
        "1     Büromöbel Set Classic                   1      840,34 €      840,34 €", "",
        "Nettobetrag:                 840,34 €", "zzgl. 19 % MwSt.:           159,66 €",
        "Rechnungsbetrag:           1.000,00 €", "",
        "Zahlbar bis 09.02.2024 ohne Abzug.",
        "Bitte geben Sie bei der Überweisung die Rechnungsnummer an."], MUELLER_FOOT),
    Doc("dunning1_mueller", MUELLER, [
        "1. Mahnung", "",
        "Datum: 01.03.2024", "Bearbeitungsnummer: 4711/A", "Kundennummer: K-4711", "",
        "Sehr geehrte Damen und Herren,",
        "für unsere Rechnung Nr. RE-2024/001 vom 10.01.2024 konnten wir bis heute keinen",
        "Zahlungseingang feststellen. Wir bitten Sie, den offenen Betrag zu begleichen.", "",
        "Offene Hauptforderung:     1.000,00 €", "Mahngebühr:                    5,00 €",
        "Gesamtforderung:           1.005,00 €", "",
        "Bitte zahlen Sie bis spätestens 15.03.2024."], MUELLER_FOOT),
    Doc("dunning2_inkasso", INKASSO, [
        "2. Mahnung", "",
        "Datum: 20.03.2024", "Aktenzeichen: INK-2024-77881", "Forderungsnummer: F-99120",
        "Auftraggeber: Müller Bürobedarf GmbH", "",
        "Betreff: Ihre Rechnung Nr. RE-2024/001 vom 10.01.2024", "",
        "Im Auftrag unseres Mandanten fordern wir Sie erneut zur Zahlung auf.", "",
        "Hauptforderung:                  1.000,00 €", "Mahngebühr 1. Mahnung:             5,00 €",
        "Mahngebühr 2. Mahnung:            10,00 €", "Gesamtforderung:                1.015,00 €", "",
        "Zahlbar bis 03.04.2024 auf das Konto IBAN DE02 1203 0000 0000 2020 51."], INKASSO_FOOT),
    Doc("payment_confirmation", ["Beispiel Handels GmbH", "Zahlungsbeleg Online-Banking", ""], [
        "Zahlungsbestätigung", "",
        "Ausführungsdatum: 01.04.2024", "Empfänger: Müller Bürobedarf GmbH",
        "IBAN Empfänger: DE89 3704 0044 0532 0130 00", "Betrag: 400,00 EUR",
        "Verwendungszweck: RE-2024/001 Teilzahlung", "", "Die Überweisung wurde ausgeführt."], []),
    Doc("collection_letter", INKASSO, [
        "Inkassoschreiben", "",
        "Datum: 15.05.2024", "Aktenzeichen: INK-2024-90001", "Mandatsnummer: M-5521",
        "Gläubiger: Müller Bürobedarf GmbH", "",
        "Betreff: Forderungsaufstellung zur Rechnung RE-2024/001", "",
        "Wir vertreten die Interessen der Firma Müller Bürobedarf GmbH. Die Forderung wurde an uns",
        "zum Einzug übergeben. Es ergibt sich folgende Forderungsaufstellung:", "",
        "Hauptforderung:                  1.000,00 €", "Mahnkosten:                        15,00 €",
        "Verzugszinsen:                    27,40 €", "Verzugspauschale:                 40,00 €",
        "Inkassokosten:                   120,50 €", "Gesamtforderung:                1.202,90 €", "",
        "abzüglich Zahlung vom 01.04.2024:   400,00 €", "Noch zu zahlen:                  802,90 €", "",
        "Zahlen Sie bitte bis zum 29.05.2024."], INKASSO_FOOT),
    Doc("court_order", ["Amtsgericht Wedding", "Zentrales Mahngericht", "Berlin"], [
        "Mahnbescheid", "",
        "Datum: 02.07.2024", "Aktenzeichen: 24-1234567-0-1", "Antragsteller: Müller Bürobedarf GmbH", "",
        "Hauptforderung: 1.000,00 € Rechnung RE-2024/001 vom 10.01.2024",
        "Gerichtskosten:   32,00 €", "Gesamtbetrag: 1.032,00 €", "",
        "Gegen diesen Mahnbescheid können Sie innerhalb von zwei Wochen Widerspruch einlegen."], []),
    Doc("credit_note", MUELLER, [
        "Gutschrift", "", "Gutschriftsnummer: GS-2024/003", "Datum: 05.02.2024",
        "Bezug: Rechnung RE-2024/001 vom 10.01.2024", "", "Nettobetrag: 84,03 €", "zzgl. 19 % MwSt.: 15,97 €",
        "Gutschriftsbetrag: 100,00 €", "Der Betrag wird mit Ihrer nächsten Rechnung verrechnet."], MUELLER_FOOT),
    Doc("delivery_note", MUELLER, [
        "Lieferschein", "", "Lieferscheinnummer: LS-2024/778", "Datum: 08.01.2024", "Bestellnummer: B-2023-889", "",
        "1 x Büromöbel Set Classic", "Die Ware wurde vollständig geliefert."], MUELLER_FOOT),
]

TEXTS = {
    "invoice_en.txt": """Acme Office Supplies Ltd.
12 Baker Street, London

Invoice
Invoice No. INV-2024-17
Invoice date: 12.03.2024
Due date: 11.04.2024
Customer number: C-5521
Net amount: 1,000.00
VAT 19%: 190.00
Total amount due: 1,190.00 EUR
IBAN DE75 5121 0800 1245 1261 99
""",
    "reminder_en.txt": """Acme Office Supplies Ltd.
Payment reminder
Date: 20.04.2024
Reference: REM-77
Our invoice INV-2024-17 dated 12.03.2024 is still unpaid.
Outstanding amount: 1,190.00 EUR
Reminder fee: 5.00 EUR
Total: 1,195.00 EUR
Please pay by 04.05.2024.
""",
    "empty.txt": "   \n",
}


def draw_pdf(doc: Doc, path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    y = h - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(60, y, doc.sender[0])
    c.setFont("Helvetica", 9)
    for line in doc.sender[1:]:
        y -= 13
        c.drawString(60, y, line)
    y -= 38
    c.setFont("Helvetica", 8)
    c.drawString(60, y, f"{doc.sender[0]} · {doc.sender[1] if len(doc.sender) > 1 else ''}")
    c.setFont("Helvetica", 11)
    for line in DEBTOR:
        y -= 15
        c.drawString(60, y, line)
    y -= 40
    for i, line in enumerate(doc.lines):
        c.setFont("Helvetica-Bold" if i == 0 else "Courier" if "  " in line else "Helvetica", 14 if i == 0 else 10.5)
        c.drawString(60, y, line)
        y -= 20 if i == 0 else 15
    c.setFont("Helvetica", 7.5)
    fy = 60
    for line in reversed(doc.footer):
        c.drawString(60, fy, line)
        fy += 11
    c.showPage()
    c.save()


def scan_like(pdf: Path, out: Path, seed: int, angle: float = 1.3, fmt: str = "PNG") -> None:
    """Render page 1 and degrade it like a cheap scan: rotation, noise, blur, uneven brightness."""
    rng = random.Random(seed)
    with fitz.open(pdf) as d:
        pix = d[0].get_pixmap(dpi=200)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
    img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(0.7))
    px = img.load()
    w, hgt = img.size
    for _ in range(w * hgt // 40):
        x, y = rng.randrange(w), rng.randrange(hgt)
        v = px[x, y] + rng.randint(-60, 40)
        px[x, y] = max(0, min(255, v))
    for x in range(w):  # vertical brightness ramp
        shade = int(25 * x / w)
        for y in range(0, hgt, 1):
            px[x, y] = max(0, px[x, y] - shade)
    img.save(out, fmt)


def generate(out_dir: Path) -> None:
    pdf_dir, scan_dir, txt_dir = out_dir / "pdf", out_dir / "scans", out_dir / "texts"
    for d in (pdf_dir, scan_dir, txt_dir):
        d.mkdir(parents=True, exist_ok=True)
    for doc in DOCS:
        draw_pdf(doc, pdf_dir / f"{doc.name}.pdf")
        with fitz.open(pdf_dir / f"{doc.name}.pdf") as d:
            (txt_dir / f"{doc.name}.txt").write_text(d[0].get_text(), encoding="utf-8")
    scan_like(pdf_dir / "invoice_RE-2024-001.pdf", scan_dir / "invoice_RE-2024-001_scan.png", 1, 1.3)
    scan_like(pdf_dir / "dunning2_inkasso.pdf", scan_dir / "dunning2_inkasso_scan.png", 2, -0.9)
    scan_like(pdf_dir / "payment_confirmation.pdf", scan_dir / "payment_confirmation_scan.jpg", 3, 0.6, "JPEG")
    for name, content in TEXTS.items():
        (txt_dir / name).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "tests" / "fixtures"
    generate(target)
    print(f"fixtures written to {target}")
