"""Bank statements: import, duplicate protection, recognition, booking, corrections."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from supplier_app.errors import AccountRequiredError, DuplicateError, LedgerError, ValidationError
from supplier_app.models.entities import BankAccount, Party, RecurringAmount, RecurringInvoice
from supplier_app.models.enums import BankTxStatus, InvoiceStatus, RecurrencePeriod
from supplier_app.services.bank_service import BankService

FIX = Path(__file__).parent / "fixtures" / "bank"
OWN = "DE89370400440532013000"


@pytest.fixture()
def world(svc):
    """Mueller (unknown IBAN, one open invoice), the landlord with a recurring rent, and one more supplier."""
    mueller = svc.suppliers.create(Party(name="Müller Bürobedarf GmbH", aliases=["Mueller Buero"]))
    inv = svc.invoices.create_invoice(mueller.id, "RE-2024/001", date(2024, 2, 20), gross_cents=119000)
    landlord = svc.suppliers.create(Party(name="Hausverwaltung Berger"))
    rec = svc.recurring.create(RecurringInvoice(landlord.id, "Miete", RecurrencePeriod.MONTHLY, date(2024, 3, 7),
                                                day_of_month=7, amounts=[RecurringAmount(date(2024, 3, 7), 450000)]))
    svc.recurring.generate_due(date(2024, 3, 8))
    other = svc.suppliers.create(Party(name="Stadtwerke Beispielstadt", ibans=["DE44500105175407324931"]))
    return {"svc": svc, "mueller": mueller, "invoice": inv, "landlord": landlord, "rec": rec, "other": other}


def test_import_recognises_supplier_invoice_and_rent(world) -> None:
    svc = world["svc"]
    res = svc.bank.import_file(FIX / "sparkasse.csv")
    assert (res.created, res.duplicates, res.account.iban) == (3, 0, OWN) and res.account_created
    by_amount = {t.amount_cents: t for t in svc.bank.transactions()}
    pay = by_amount[-119000]
    assert pay.status == BankTxStatus.MATCHED and pay.supplier_id == world["mueller"].id
    assert pay.invoice_ids == [world["invoice"].id] and pay.confidence >= 0.85
    assert any("RE-2024/001" in r for r in pay.reasons)
    rent = by_amount[-450000]
    assert rent.status == BankTxStatus.MATCHED and rent.supplier_id == world["landlord"].id
    assert len(rent.invoice_ids) == 1 and any("wiederkehrend" in r or "Betrag" in r for r in rent.reasons)
    incoming = by_amount[25000]
    assert incoming.status == BankTxStatus.IGNORED and incoming.supplier_id is None


def test_booking_pays_invoice_learns_iban_and_can_be_reversed(world) -> None:
    svc = world["svc"]
    svc.bank.import_file(FIX / "sparkasse.csv")
    tx = next(t for t in svc.bank.transactions() if t.amount_cents == -119000)
    payment = svc.bank.book(tx.id)
    assert svc.invoices.get(world["invoice"].id).status == InvoiceStatus.PAID
    stored = svc.bank.get(tx.id)
    assert stored.status == BankTxStatus.BOOKED and stored.payment_id == payment.id
    party = svc.suppliers.get(world["mueller"].id)
    assert "DE02120300000000202051" in party.ibans and party.aliases == ["Mueller Buero"]  # the printed name is close enough
    with pytest.raises(LedgerError):
        svc.bank.assign(tx.id, None)
    svc.payments.reverse_payment(payment.id)
    again = svc.bank.get(tx.id)
    assert again.status == BankTxStatus.NEW and again.payment_id is None
    assert svc.invoices.get(world["invoice"].id).status == InvoiceStatus.OPEN


def test_next_statement_is_recognised_by_the_learned_iban(world, tmp_path) -> None:
    svc = world["svc"]
    svc.bank.import_file(FIX / "sparkasse.csv")
    svc.bank.book(next(t for t in svc.bank.transactions() if t.amount_cents == -119000).id)
    svc.invoices.create_invoice(world["mueller"].id, "RE-2024/009", date(2024, 3, 20), gross_cents=5000)
    nxt = tmp_path / "april.csv"
    nxt.write_text('"Auftragskonto";"Buchungstag";"Verwendungszweck";"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"Betrag"\n'
                   f'"{OWN}";"02.04.2024";"Sammelzahlung";"Mueller B. GmbH";"DE02120300000000202051";"-50,00"\n', encoding="utf-8")
    res = svc.bank.import_file(nxt)
    tx = svc.bank.transactions(account_id=res.account.id)[0]
    assert tx.supplier_id == world["mueller"].id and tx.status == BankTxStatus.MATCHED
    assert any("IBAN" in r for r in tx.reasons)


def test_duplicates_and_overlapping_statements(world, tmp_path) -> None:
    svc = world["svc"]
    svc.bank.import_file(FIX / "sparkasse.csv")
    with pytest.raises(DuplicateError):
        svc.bank.import_file(FIX / "sparkasse.csv")  # same file
    text = (FIX / "sparkasse.csv").read_text(encoding="utf-8")
    extra = text.rstrip("\n") + '\n"DE89370400440532013000";"08.03.2024";"08.03.2024";"ONLINE-UEBERWEISUNG";"Neu";"";"";"";"";"";"";"Jemand";"";"";"-5,00";"EUR";""\n'
    overlap = tmp_path / "overlap.csv"
    overlap.write_text(extra, encoding="utf-8")
    res = svc.bank.import_file(overlap)
    assert (res.created, res.duplicates) == (1, 3)
    assert len(svc.bank.transactions()) == 4


def test_two_identical_payments_on_one_day_are_both_kept(world, tmp_path) -> None:
    line = f'"{OWN}";"05.03.2024";"Parkgebuehr";"Parkhaus";"";"-3,50"\n'
    path = tmp_path / "same.csv"
    path.write_text('"Auftragskonto";"Buchungstag";"Verwendungszweck";"Beguenstigter/Zahlungspflichtiger";"Kontonummer/IBAN";"Betrag"\n'
                    + line * 2, encoding="utf-8")
    assert world["svc"].bank.import_file(path).created == 2


def test_change_supplier_and_invoices_then_book_later(world) -> None:
    svc = world["svc"]
    svc.bank.import_file(FIX / "sparkasse.csv")
    tx = next(t for t in svc.bank.transactions() if t.amount_cents == -119000)
    other_inv = svc.invoices.create_invoice(world["other"].id, "SW-77", date(2024, 3, 1), gross_cents=119000)
    assert svc.bank.propose(tx.id, world["other"].id) == [other_inv.id]
    svc.bank.assign(tx.id, world["other"].id, [other_inv.id])
    changed = svc.bank.get(tx.id)
    assert changed.supplier_id == world["other"].id and changed.status == BankTxStatus.MATCHED
    svc.bank.ignore(tx.id, "später")
    assert svc.bank.get(tx.id).status == BankTxStatus.IGNORED
    svc.bank.reopen(tx.id)
    svc.bank.assign(tx.id, world["other"].id, [other_inv.id])
    svc.bank.book(tx.id)
    assert svc.invoices.get(other_inv.id).status == InvoiceStatus.PAID
    assert svc.invoices.get(world["invoice"].id).status == InvoiceStatus.OPEN


def test_book_sure_books_only_certain_matches(world) -> None:
    svc = world["svc"]
    svc.bank.import_file(FIX / "sparkasse.csv")
    report = svc.bank.book_sure()
    assert len(report.booked) == 2 and not report.failed
    assert svc.bank.counts().get("booked") == 2


def test_possible_duplicate_payment_is_flagged(world) -> None:
    svc = world["svc"]
    svc.payments.record_payment(world["mueller"].id, date(2024, 3, 5), 119000, [world["invoice"].id])
    svc.bank.import_file(FIX / "sparkasse.csv")
    tx = next(t for t in svc.bank.transactions() if t.amount_cents == -119000)
    assert tx.status == BankTxStatus.NEW and "schon gebucht" in tx.note
    with pytest.raises(DuplicateError):
        svc.bank.book(tx.id)


def test_account_choice_and_transfer_between_own_accounts(world, tmp_path) -> None:
    svc = world["svc"]
    path = tmp_path / "noiban.csv"
    path.write_text("Buchungstag;Verwendungszweck;Name;IBAN;Betrag\n05.03.2024;Umbuchung;Eigenes Tagesgeld;DE44500105175407324931;-100,00\n",
                    encoding="utf-8")
    with pytest.raises(AccountRequiredError):
        svc.bank.import_file(path)
    savings = svc.bank.add_account(BankAccount("Tagesgeld", "DE44500105175407324931"))
    main = svc.bank.add_account(BankAccount("Hauptkonto", OWN))
    res = svc.bank.import_file(path, main.id)
    tx = svc.bank.transactions(account_id=res.account.id)[0]
    assert tx.status == BankTxStatus.IGNORED and "Tagesgeld" in tx.note and savings.id
    with pytest.raises(ValidationError):
        svc.bank.add_account(BankAccount("Falsch", "DE00123"))


def test_camt_and_mt940_statements_are_matched_like_csv(world) -> None:
    svc = world["svc"]
    assert svc.bank.import_file(FIX / "statement.camt.xml").created == 2
    first = next(t for t in svc.bank.transactions() if t.amount_cents == -119000)
    assert first.supplier_id == world["mueller"].id and first.status == BankTxStatus.MATCHED
    res = svc.bank.import_file(FIX / "statement.sta")  # account only known by bank code -> choose
    assert res.duplicates == 1 and res.created == 1  # the payment is the same line, the refund text differs in the fixture


def test_fingerprints_are_stable(world) -> None:
    from supplier_app.bank.model import ParsedTransaction
    t = ParsedTransaction(date(2024, 1, 1), -100, purpose="x")
    assert BankService.fingerprints("A", [t, t]) == BankService.fingerprints("A", [t, t])
    assert len(set(BankService.fingerprints("A", [t, t]))) == 2
    assert BankService.fingerprints("A", [t]) != BankService.fingerprints("B", [t])
