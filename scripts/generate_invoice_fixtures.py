"""Generate invoice PDFs with different table layouts (text layer) to test recognition on real PDF text extraction.

Only invented companies. Run:  python scripts/generate_invoice_fixtures.py [output_dir]
Writes ``<name>.pdf`` and ``expected.json`` (what the recognition must find).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

W, H = A4


def _info_block(c: canvas.Canvas, rows: list[tuple[str, str]], x_label: float = 350, x_value: float = 460, top: float = 120) -> None:
    y = H - top
    for lab, val in rows:
        c.drawString(x_label, y, lab)
        c.drawString(x_value, y, val)
        y -= 14


def _totals(c: canvas.Canvas, rows: list[tuple[str, str]], y: float, x_label: float = 350, x_value: float = 545) -> None:
    for lab, val in rows:
        c.drawString(x_label, y, lab)
        c.drawRightString(x_value, y, val)
        y -= 14


def _items(c: canvas.Canvas, header: list[str], rows: list[list[str]], y: float) -> float:
    xs = [50, 90, 400, 470, 545][: len(header)]
    for i, text in enumerate(header):
        (c.drawString if i < 2 else c.drawRightString)(xs[i], y, text)
    y -= 16
    for row in rows:
        for i, text in enumerate(row):
            (c.drawString if i < 2 else c.drawRightString)(xs[i], y, text)
        y -= 14
    return y


def build(path: Path, kind: str) -> dict:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 10)
    if kind == "info_block_totals_right":
        c.setFont("Helvetica-Bold", 20)
        c.drawString(50, H - 80, "RECHNUNG")
        c.setFont("Helvetica", 10)
        c.drawString(50, H - 60, "Elektro Meier e.K. · Hauptstr. 4 · 50667 Köln")
        _info_block(c, [("Rechnungsnummer", "RE-2024-881"), ("Rechnungsdatum", "15.03.2024"), ("Kundennummer", "K-7"),
                        ("Zahlungsziel", "14 Tage")])
        y = _items(c, ["Pos", "Bezeichnung", "Menge", "Einzelpreis", "Gesamt"],
                   [["1", "Installationsarbeiten", "8", "80,00 €", "640,00 €"]], H - 250)
        _totals(c, [("Netto", "640,00 €"), ("zzgl. 19 % MwSt.", "121,60 €"), ("Gesamtbetrag (brutto)", "761,60 €")], y - 40)
        exp = dict(doc_type="invoice", number="RE-2024-881", date="2024-03-15", due="2024-03-29", net=64000, vat=12160, gross=76160)
    elif kind == "beleg_horizontal_totals":
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, H - 80, "Beleg")
        c.setFont("Helvetica", 10)
        c.drawString(50, H - 60, "Gärtnerei Grün OHG · Feldweg 2 · 80331 München")
        _info_block(c, [("Beleg-Nr.", "2024-0815"), ("Datum", "15.03.2024"), ("Fällig am", "29.03.2024")], 50, 140, 110)
        y = _items(c, ["Pos", "Beschreibung", "Menge", "Preis", "Betrag"],
                   [["1", "Pflanzen", "10", "20,00 €", "200,00 €"]], H - 230)
        yy = y - 30
        for x, text in ((300, "Netto"), (400, "MwSt 19 %"), (500, "Brutto")):
            c.drawString(x, yy, text)
        for x, text in ((300, "200,00"), (400, "38,00"), (500, "238,00")):
            c.drawString(x, yy - 14, text)
        exp = dict(doc_type="invoice", number="2024-0815", date="2024-03-15", due="2024-03-29", net=20000, vat=3800, gross=23800)
    elif kind == "facture_fr":
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, H - 80, "FACTURE")
        c.setFont("Helvetica", 10)
        c.drawString(50, H - 60, "Maison Dupont SARL · 12 rue de la Paix · 75002 Paris")
        _info_block(c, [("Facture n°", "FA-2024-0042"), ("Date de facture", "15/03/2024"), ("Date d'échéance", "14/04/2024")])
        y = _items(c, ["Pos", "Désignation", "Qté", "PU HT", "Total HT"],
                   [["1", "Prestation", "1", "1 000,00 €", "1 000,00 €"]], H - 250)
        _totals(c, [("Total HT", "1 000,00 €"), ("TVA 20 %", "200,00 €"), ("Total TTC", "1 200,00 €")], y - 40)
        exp = dict(doc_type="invoice", number="FA-2024-0042", date="2024-03-15", due="2024-04-14", net=100000, vat=20000, gross=120000)
    elif kind == "summe_total_only_gross":
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, H - 80, "Rechnung Nr. 55-1021")
        c.setFont("Helvetica", 10)
        c.drawString(50, H - 60, "Bürobedarf Nord GmbH · Hafenstr. 1 · 20457 Hamburg")
        c.drawString(350, H - 100, "Datum: 02.04.2024")
        y = _items(c, ["Pos", "Artikel", "Menge", "Einzelpreis", "Summe"],
                   [["1", "Papier A4", "10", "4,00", "40,00"], ["2", "Toner schwarz", "2", "30,00", "60,00"]], H - 250)
        _totals(c, [("Summe netto", "100,00"), ("19 % USt", "19,00"), ("Summe", "119,00")], y - 40)
        c.drawString(50, 80, "Zahlbar bis 02.05.2024 · IBAN DE89 3704 0044 0532 0130 00")
        exp = dict(doc_type="invoice", number="55-1021", date="2024-04-02", due="2024-05-02", net=10000, vat=1900, gross=11900)
    elif kind == "amounts_left_of_labels":
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, H - 80, "INVOICE")
        c.setFont("Helvetica", 10)
        c.drawString(50, H - 60, "Acme Office Supplies Ltd. · 12 Baker Street · London")
        _info_block(c, [("Invoice No.", "INV-2024-17"), ("Invoice date", "12.03.2024"), ("Due date", "11.04.2024")])
        y = _items(c, ["Pos", "Description", "Qty", "Unit price", "Amount"],
                   [["1", "Consulting", "10", "100.00", "1,000.00"]], H - 250)
        _totals(c, [("Subtotal", "1,000.00"), ("VAT 19%", "190.00"), ("Total amount due", "1,190.00 EUR")], y - 40)
        exp = dict(doc_type="invoice", number="INV-2024-17", date="2024-03-12", due="2024-04-11", net=100000, vat=19000, gross=119000)
    else:
        raise ValueError(kind)
    c.save()
    return exp


KINDS = ["info_block_totals_right", "beleg_horizontal_totals", "facture_fr", "summe_total_only_gross", "amounts_left_of_labels"]

if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tests/fixtures/invoices_pdf")
    out.mkdir(parents=True, exist_ok=True)
    expected = {k: build(out / f"{k}.pdf", k) for k in KINDS}
    (out / "expected.json").write_text(json.dumps(expected, indent=1), encoding="utf-8")
    print(f"wrote {len(KINDS)} PDFs to {out}")
