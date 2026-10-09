"""'Demo-Daten laden': a deterministic, realistic data set that fills every dashboard widget."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from supplier_app.models.entities import Party
from supplier_app.models.enums import DocumentType, DunningLevel, PartyRole, ReferenceType, ReviewStatus
from supplier_app.services.dunning_service import NoticeDraft
from supplier_app.services.ledger import NoticeClaim
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents

if TYPE_CHECKING:
    from supplier_app.services.container import Services


@dataclass
class DemoSummary:
    suppliers: int
    invoices: int
    notices: int
    payments: int
    documents: int


class DemoDataService:
    """Creates demo suppliers, invoices, payments, notices and documents relative to ``today``."""

    def __init__(self, svc: Services) -> None:
        self.svc = svc

    def has_data(self) -> bool:
        return bool(self.svc.repos.parties.list()) or self.svc.repos.ledger.count() > 0

    # -- helpers -----------------------------------------------------------------------
    def _letter_doc(self, title: str, sender: str, day: date, lines: list[str], tmp: Path, name: str, level: int = 0):
        text = "\n".join([sender, "Beispiel Handels GmbH · Hauptstraße 12 · 10115 Berlin", title, f"Datum: {format_date(day)}",
                          *lines])
        path = tmp / f"{name}.txt"
        path.write_text(text, encoding="utf-8")
        doc, _created = self.svc.documents.store_file(path)
        doc.ocr_text, doc.text_source, doc.confidence = text, "plain", 0.95
        doc.doc_type = {1: DocumentType.PAYMENT_REMINDER, 2: DocumentType.FIRST_DUNNING, 3: DocumentType.SECOND_DUNNING,
                        4: DocumentType.FINAL_DUNNING, 5: DocumentType.COLLECTION_LETTER,
                        6: DocumentType.COURT_ORDER}.get(level, DocumentType.OTHER)
        self.svc.repos.documents.update(doc)
        return doc

    def load(self, today: date | None = None) -> DemoSummary:
        svc = self.svc
        t = today or date.today()

        def ago(n: int) -> date:
            return t - timedelta(days=n)

        def supplier(name: str, **kw) -> Party:
            return svc.suppliers.create(Party(name=name, role=PartyRole.SUPPLIER, **kw))

        def agency(name: str, rep: Party) -> Party:
            return svc.suppliers.create(Party(name=name, role=PartyRole.COLLECTION_AGENCY, represents_supplier_id=rep.id))

        mueller = supplier("Müller Bürobedarf GmbH", aliases=["Mueller Buero"], ibans=["DE89370400440532013000"],
                           vat_id="DE123456789", payment_terms="30 Tage netto")
        nordwind = supplier("Nordwind Logistik AG", ibans=["DE75512108001245126199"], vat_id="DE811234567")
        schmidt_it = supplier("Schmidt IT-Service GmbH & Co. KG", aliases=["Schmidt IT"])
        baeckerei = supplier("Bäckerei Hoffmann e.K.")
        alpha = supplier("Alpha Werbetechnik UG")
        gruenwald = supplier("Grünwald Maschinenbau GmbH")
        ink_schmidt = agency("Inkasso Schmidt & Partner GmbH", mueller)
        ink_nord = agency("Creditreform Nord Inkasso GmbH", nordwind)
        n_invoices = n_notices = n_payments = 0
        tmp = Path(tempfile.mkdtemp(prefix="supplierapp-demo-"))

        def invoice(sup: Party, number: str, days_ago: int, gross: int, terms: int = 30) -> int:
            nonlocal n_invoices
            n_invoices += 1
            inv = svc.invoices.create_invoice(sup.id, number, ago(days_ago), gross_cents=gross,
                                              due_date=ago(days_ago) + timedelta(days=terms))
            return inv.id

        def pay(sup: Party, days_ago: int, amount: int, invoice_ids: list[int], ref: str = ""):
            nonlocal n_payments
            n_payments += 1
            return svc.payments.record_payment(sup.id, ago(days_ago), amount, invoice_ids, bank_reference=ref)

        def notice(sender: Party, sup: Party, inv_id: int, days_ago: int, level: DunningLevel, principal: int,
                   *, fees=0, interest=0, flat=0, other=0, deadline_in: int | None = None, paid=0, refs=None,
                   doc_title: str = "") -> None:
            nonlocal n_notices
            n_notices += 1
            total = principal + fees + interest + flat + other
            doc = self._letter_doc(
                doc_title or "Mahnung", sender.name, ago(days_ago),
                [f"Hauptforderung: {format_cents(principal)}", f"Gesamtforderung: {format_cents(total)}",
                 *[f"{lbl}: {v}" for lbl, v in (refs or [])]], tmp, f"brief-{inv_id}-{days_ago}", int(level))
            doc.review_status = ReviewStatus.ACCEPTED
            svc.repos.documents.update(doc)
            svc.dunning.book_notice(NoticeDraft(
                sender_party_id=sender.id, supplier_id=sup.id, notice_date=ago(days_ago), level=level,
                claims=[NoticeClaim(inv_id, principal, fees, interest, flat, other, total)],
                new_deadline=(t + timedelta(days=deadline_in)) if deadline_in is not None else None,
                total_claimed_cents=total, credited_cents=paid, document_id=doc.id,
                references=[(ReferenceType.FILE_NUMBER if "Aktenzeichen" in k else ReferenceType.PROCESSING_NUMBER, v)
                            for k, v in (refs or [])]))

        # --- Müller: dunning ladder with partial payment and a collection agency
        m1 = invoice(mueller, "MB-2024-0187", 400, 240000)
        pay(mueller, 372, 240000, [m1], "MB-2024-0187")
        m2 = invoice(mueller, "RE-2025-001", 150, 100000)
        notice(mueller, mueller, m2, 90, DunningLevel.FIRST, 100000, fees=500, deadline_in=-60,
               refs=[("Bearbeitungsnummer", "4711/A")], doc_title="1. Mahnung")
        notice(ink_schmidt, mueller, m2, 60, DunningLevel.SECOND, 100000, fees=1500, deadline_in=-40,
               refs=[("Aktenzeichen", "INK-2025-77881")], doc_title="2. Mahnung")
        pay(mueller, 45, 40000, [m2], "RE-2025-001 Teilzahlung")
        notice(ink_schmidt, mueller, m2, 20, DunningLevel.COLLECTION, 60000, fees=1500, interest=2740, flat=4000,
               other=12050, deadline_in=3, paid=40000, refs=[("Aktenzeichen", "INK-2025-90001")],
               doc_title="Inkassoschreiben")
        invoice(mueller, "RE-2025-014", 40, 178500)
        invoice(mueller, "RE-2025-019", 5, 56000)
        invoice(mueller, "RE-2025-021", 2, 33000, terms=60)

        # --- Nordwind: full ladder up to court order
        n1 = invoice(nordwind, "NL-88231", 200, 1250000)
        notice(nordwind, nordwind, n1, 150, DunningLevel.REMINDER, 1250000, deadline_in=-120,
               doc_title="Zahlungserinnerung")
        notice(nordwind, nordwind, n1, 130, DunningLevel.FIRST, 1250000, fees=500, doc_title="1. Mahnung")
        notice(nordwind, nordwind, n1, 100, DunningLevel.FINAL, 1250000, fees=1000, interest=15200, doc_title="Letzte Mahnung")
        notice(ink_nord, nordwind, n1, 70, DunningLevel.COLLECTION, 1250000, fees=1000, interest=31500, flat=4000,
               other=12050, refs=[("Aktenzeichen", "CN-2025-4471")], doc_title="Inkassoschreiben")
        notice(ink_nord, nordwind, n1, 30, DunningLevel.COURT_ORDER, 1250000, fees=1000, interest=52000, flat=4000,
               other=15250, refs=[("Aktenzeichen", "24-7770011-0-1")], doc_title="Mahnbescheid")
        n2 = invoice(nordwind, "NL-88790", 80, 320000)
        pay(nordwind, 50, 100000, [n2], "NL-88790 Rate 1")
        pay(nordwind, 20, 100000, [n2], "NL-88790 Rate 2")
        notice(nordwind, nordwind, n2, 40, DunningLevel.REMINDER, 220000, deadline_in=6, doc_title="Zahlungserinnerung")
        invoice(nordwind, "NL-89102", 12, 78000)
        invoice(nordwind, "NL-89200", 1, 91000, terms=85)

        # --- Schmidt IT: payment ignored by a dunning letter (discrepancy) + possible duplicate invoices
        s1 = invoice(schmidt_it, "SIT-1093", 300, 800000)
        pay(schmidt_it, 270, 500000, [s1])
        pay(schmidt_it, 255, 300000, [s1])
        s2 = invoice(schmidt_it, "SIT-1188", 100, 476000)
        pay(schmidt_it, 70, 200000, [s2], "SIT-1188")
        notice(schmidt_it, schmidt_it, s2, 60, DunningLevel.FIRST, 476000, fees=500, deadline_in=2, doc_title="1. Mahnung")
        invoice(schmidt_it, "SIT-1203", 20, 95000)
        invoice(schmidt_it, "SIT-1203-A", 15, 95000)

        # --- Bäckerei: monthly invoices, credit note
        for i, (days, gross) in enumerate([(170, 24100), (140, 25800), (110, 23900), (80, 25500), (50, 24700), (25, 26100)]):
            inv_id = invoice(baeckerei, f"BH-{2025}-{i + 1:03d}", days, gross)
            if i < 4:
                pay(baeckerei, days - 28, gross, [inv_id], f"BH-{2025}-{i + 1:03d}")
        b2 = invoice(baeckerei, "BH-2025-010", 28, 60000)
        svc.invoices.credit_note(b2, 10000, ago(20), "Retoure beschädigte Ware")

        # --- Alpha: overpayment (credit on account), disputed invoice
        a1 = invoice(alpha, "AW-5521", 60, 210000)
        pay(alpha, 30, 250000, [a1], "AW-5521")
        a2 = invoice(alpha, "AW-5598", 30, 120000)
        svc.invoices.set_disputed(a2, True)
        case = svc.cases.open_manual(a2)
        svc.cases.add_note(case.id, "Leistung nicht vollständig erbracht – Klärung mit Lieferant")

        # --- Grünwald: paid invoice and a last reminder
        g1 = invoice(gruenwald, "GM-0071", 250, 1580000)
        pay(gruenwald, 222, 1580000, [g1], "GM-0071")
        g2 = invoice(gruenwald, "GM-0144", 90, 630000)
        notice(gruenwald, gruenwald, g2, 20, DunningLevel.FINAL, 630000, fees=1000, deadline_in=5,
               refs=[("Bearbeitungsnummer", "GM-B-9921")], doc_title="Letzte Mahnung")

        # --- documents waiting for review (go through the real recognition pipeline)
        docs = 0
        pending = [
            ("2-mahnung-gruenwald", "Grünwald Maschinenbau GmbH\n2. Mahnung\nDatum: {d}\nBearbeitungsnummer: GM-B-9921\n"
             "Ihre Rechnung Nr. GM-0144\nHauptforderung: 6.300,00 €\nMahngebühr: 10,00 €\nMahngebühr: 10,00 €\n"
             "Gesamtforderung: 6.320,00 €\nZahlen Sie bis spätestens {dl}."),
            ("zahlung-nordwind", "Zahlungsbestätigung\nAusführungsdatum: {d}\nEmpfänger: Nordwind Logistik AG\n"
             "Betrag: 500,00 EUR\nVerwendungszweck: NL-88790 Rate 3"),
            ("unleserlich", "Rechnung\n??? 12,\n#### Betrag unleserlich"),
        ]
        for name, body in pending:
            path = tmp / f"{name}.txt"
            path.write_text(body.format(d=format_date(ago(2)), dl=format_date(t + timedelta(days=9))), encoding="utf-8")
            if svc.ingest.import_file(path).document:
                docs += 1
        return DemoSummary(8, n_invoices, n_notices, n_payments, docs + n_notices)
