"""Report builders. Every number comes from the ledger services / repositories (never recomputed ad hoc)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from supplier_app.i18n import level_label, tr
from supplier_app.models.enums import InvoiceStatus, LedgerEntryType
from supplier_app.services.ledger import AGING_BUCKETS, aging_bucket
from supplier_app.util.dates import format_date
from supplier_app.util.money import format_cents

from .models import ReportTable

if TYPE_CHECKING:
    from supplier_app.services.container import Services

REPORT_KINDS = ("statement", "open_items", "dunning", "payments")


class ReportService:
    def __init__(self, svc: Services) -> None:
        self.svc = svc

    def _name(self, supplier_id: int) -> str:
        p = self.svc.repos.parties.get(supplier_id)
        return p.name if p else "?"

    @staticmethod
    def _period(date_from: date | None, date_to: date | None) -> str:
        if date_from and date_to:
            return f"{format_date(date_from)} – {format_date(date_to)}"
        if date_to:
            return f"bis {format_date(date_to)}"
        return "gesamter Zeitraum"

    def build(self, kind: str, *, supplier_id: int | None = None, date_from: date | None = None,
              date_to: date | None = None, as_of: date | None = None) -> ReportTable:
        if kind == "statement":
            if supplier_id is None:
                raise ValueError("Für das Kontoblatt wird ein Lieferant benötigt.")
            return self.supplier_statement(supplier_id, date_from, date_to)
        if kind == "open_items":
            return self.open_items(as_of or date.today(), supplier_id)
        if kind == "dunning":
            return self.dunning_overview(date_from, date_to, supplier_id)
        if kind == "payments":
            return self.payments(date_from, date_to, supplier_id)
        raise ValueError(f"Unbekannter Bericht: {kind}")

    # -- Kontoblatt ------------------------------------------------------------------------
    def supplier_statement(self, supplier_id: int, date_from: date | None, date_to: date | None) -> ReportTable:
        st = self.svc.ledger.supplier_statement(supplier_id, date_from, date_to)
        cols = ["Datum", "Rechnung", "Art", "Text", "Soll", "Haben", "Saldo"]
        rows: list[list[str]] = []
        raw: list[list] = []
        if date_from:
            rows.append([format_date(date_from), "", "Übertrag", "Saldovortrag", "", "", format_cents(st.opening_cents)])
            raw.append([date_from, "", "Übertrag", "Saldovortrag", None, None, st.opening_cents])
        debit = credit = 0
        for r in st.rows:
            e = r.entry
            d_amt = e.amount_cents if e.amount_cents > 0 else None
            c_amt = -e.amount_cents if e.amount_cents < 0 else None
            debit += d_amt or 0
            credit += c_amt or 0
            label = tr(f"entry.{e.entry_type.value}")
            if e.entry_type == LedgerEntryType.REVERSAL:
                label = f"{label} ({tr('entry.' + e.category_type.value)})"
            rows.append([format_date(e.entry_date), r.invoice_number, label, e.comment,
                         format_cents(d_amt) if d_amt else "", format_cents(c_amt) if c_amt else "",
                         format_cents(r.running_cents)])
            raw.append([e.entry_date, r.invoice_number, label, e.comment, d_amt, c_amt, r.running_cents])
        return ReportTable(
            title=f"Kontoblatt {self._name(supplier_id)}", subtitle=self._period(date_from, date_to), columns=cols,
            rows=rows, raw_rows=raw, money_columns={4, 5, 6}, totals=[None, None, None, "Summe / Schlusssaldo", debit,
                                                                        credit, st.closing_cents])

    # -- Offene Posten -----------------------------------------------------------------------
    def open_items(self, as_of: date, supplier_id: int | None) -> ReportTable:
        states = [s for s in self.svc.ledger.invoice_states(as_of, supplier_id)
                  if s.balance.balance_cents > 0 and s.invoice.status != InvoiceStatus.CANCELLED]
        states.sort(key=lambda s: (self._name(s.invoice.supplier_id).lower(), s.invoice.due_date or date.max))
        cols = ["Lieferant", "Rechnung", "Rechnungsdatum", "Fällig", "Tage überfällig", "Fälligkeit", "Rechnungsbetrag",
                "Gebühren/Zinsen", "Bezahlt/Gutschrift", "Offen"]
        rows: list[list[str]] = []
        raw: list[list] = []
        for s in states:
            inv, b = s.invoice, s.balance
            overdue = max(0, (as_of - inv.due_date).days) if inv.due_date else 0
            bucket = aging_bucket(inv.due_date, as_of)
            settled = b.paid_cents + b.credits_cents + b.write_offs_cents
            vals = [self._name(inv.supplier_id), inv.invoice_number, inv.invoice_date, inv.due_date, overdue,
                    tr(f"aging.{bucket}"), b.invoiced_cents, b.charges_cents, settled, b.balance_cents]
            raw.append(vals)
            rows.append([vals[0], vals[1], format_date(inv.invoice_date), format_date(inv.due_date), str(overdue),
                         vals[5], format_cents(b.invoiced_cents), format_cents(b.charges_cents),
                         format_cents(settled), format_cents(b.balance_cents)])
        totals = [None] * 6 + [sum(r[6] for r in raw), sum(r[7] for r in raw), sum(r[8] for r in raw),
                               sum(r[9] for r in raw)]
        aging = self.svc.ledger.aging(as_of, supplier_id)
        aging_rows = [[tr(f"aging.{b}"), format_cents(aging[b])] for b in AGING_BUCKETS]
        aging_table = ReportTable("Fälligkeitsstruktur", f"Stichtag {format_date(as_of)}", ["Fälligkeit", "Offen"],
                                  aging_rows, [[tr(f"aging.{b}"), aging[b]] for b in AGING_BUCKETS], {1},
                                  [None, sum(aging.values())])
        name = self._name(supplier_id) if supplier_id else "alle Lieferanten"
        return ReportTable(f"Offene Posten – {name}", f"Stichtag {format_date(as_of)}", cols, rows, raw,
                           {6, 7, 8, 9}, totals, extra=[aging_table])

    # -- Mahnübersicht --------------------------------------------------------------------------
    def dunning_overview(self, date_from: date | None, date_to: date | None, supplier_id: int | None) -> ReportTable:
        cols = ["Datum", "Lieferant", "Absender", "Stufe", "Rechnung(en)", "Gefordert", "Konto (erwartet)", "Differenz",
                "Zinsen gefordert", "Zinsen berechnet", "Pauschale gefordert", "Pauschale berechnet", "Hinweis"]
        rows: list[list[str]] = []
        raw: list[list] = []
        for n in self.svc.repos.notices.list(supplier_id=supplier_id):
            if (date_from and n.notice_date < date_from) or (date_to and n.notice_date > date_to):
                continue
            assert n.id is not None
            rec = self.svc.ledger.reconcile_notice(n.id)
            comparison = self.svc.dunning.compare_with_calculation(n.id)
            interest_claimed = sum(c.interest_cents for c in n.claims)
            interest_calc = sum(r.calculated_cents for r in comparison if r.label == "Verzugszinsen")
            flat_claimed = sum(c.flat_fee_cents for c in n.claims)
            flat_calc = sum(r.calculated_cents for r in comparison if r.label == "Verzugspauschale")
            sender = self.svc.repos.parties.get(n.sender_party_id)
            numbers = ", ".join(
                self.svc.repos.invoices.get(c.invoice_id).invoice_number  # type: ignore[union-attr]
                 for c in n.claims)
            note = "; ".join(i.message for i in rec.issues) or "OK"
            vals = [n.notice_date, self._name(n.supplier_id), sender.name if sender else "?", level_label(int(n.level)),
                    numbers, rec.claimed_total_cents, rec.expected_total_cents, rec.difference_cents,
                    interest_claimed, interest_calc, flat_claimed, flat_calc, note]
            raw.append(vals)
            rows.append([format_date(n.notice_date), vals[1], vals[2], vals[3], numbers,
                         format_cents(vals[5]), format_cents(vals[6]), format_cents(vals[7], plus=True),
                         format_cents(interest_claimed), format_cents(interest_calc), format_cents(flat_claimed),
                         format_cents(flat_calc), note])
        totals = [None] * 5 + [sum(r[5] for r in raw), sum(r[6] for r in raw), sum(r[7] for r in raw),
                               sum(r[8] for r in raw), sum(r[9] for r in raw), sum(r[10] for r in raw),
                               sum(r[11] for r in raw), None]
        return ReportTable("Mahnübersicht: gefordert vs. berechnet", self._period(date_from, date_to), cols, rows, raw,
                           {5, 6, 7, 8, 9, 10, 11}, totals)

    # -- Zahlungen -----------------------------------------------------------------------------------
    def payments(self, date_from: date | None, date_to: date | None, supplier_id: int | None) -> ReportTable:
        cols = ["Datum", "Lieferant", "Betrag", "Verwendungszweck", "Zugeordnete Rechnungen", "Nicht zugeordnet", "Status"]
        rows: list[list[str]] = []
        raw: list[list] = []
        for p in self.svc.repos.payments.list(supplier_id=supplier_id, date_from=date_from, date_to=date_to):
            entries = self.svc.repos.ledger.list(payment_id=p.id)
            reversed_ids = {e.reverses_entry_id for e in entries if e.reverses_entry_id}
            active = [e for e in entries if e.entry_type == LedgerEntryType.PAYMENT and e.id not in reversed_ids]
            by_invoice = [e for e in active if e.invoice_id]
            unapplied = -sum(e.amount_cents for e in active if not e.invoice_id)
            numbers = ", ".join(
                self.svc.repos.invoices.get(e.invoice_id).invoice_number  # type: ignore[arg-type, union-attr]
                for e in by_invoice)
            status = "storniert" if not active else ("Guthaben" if unapplied else "gebucht")
            vals = [p.payment_date, self._name(p.supplier_id), p.amount_cents if active else 0,
                    p.bank_reference, numbers, unapplied, status]
            raw.append(vals)
            rows.append([format_date(p.payment_date), vals[1], format_cents(vals[2]), p.bank_reference, numbers,
                         format_cents(unapplied), status])
        totals = [None, None, sum(r[2] for r in raw), None, None, sum(r[5] for r in raw), None]
        return ReportTable("Zahlungen", self._period(date_from, date_to), cols, rows, raw, {2, 5}, totals)
