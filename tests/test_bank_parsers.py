"""Bank statement parsers: CSV, CAMT.053, MT940, PDF text."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from supplier_app.bank.parsers import (
    looks_like_bank_file,
    parse_camt053,
    parse_cents,
    parse_csv,
    parse_mt940,
    parse_pdf_text,
    parse_statement_file,
)
from supplier_app.errors import DocumentError

FIX = Path(__file__).parent / "fixtures" / "bank"


@pytest.mark.parametrize("text, cents", [
    ("-1.190,00", -119000), ("1.234,56", 123456), ("1234.56", 123456), ("1.234,56-", -123456), ("1.234,56 S", -123456),
    ("1.234,56 H", 123456), ("+12,5", 1250), ("0,05", 5), ("1,234.56", 123456), ("1.234.567", 123456700), ("", None), ("abc", None),
])
def test_parse_cents(text, cents) -> None:
    assert parse_cents(text) == cents


def test_sparkasse_csv() -> None:
    st = parse_statement_file(FIX / "sparkasse.csv")
    assert st.format == "csv" and st.account_iban == "DE89370400440532013000"
    assert [t.amount_cents for t in st.transactions] == [-119000, 25000, -450000]
    first = st.transactions[0]
    assert first.booking_date == date(2024, 3, 5) and first.counterparty_name.startswith("Mueller")
    assert first.counterparty_iban == "DE02120300000000202051" and "RE-2024/001" in first.purpose
    assert (st.date_from, st.date_to) == (date(2024, 3, 5), date(2024, 3, 7))


def test_csv_with_preamble_debit_credit_columns_and_cp1252(tmp_path) -> None:
    text = ("Umsatzanzeige;Datum:;01.03.2024\nIBAN;DE89 3704 0044 0532 0130 00\n\n"
            "Buchungstag;Wertstellung;Auftraggeber / Beguenstigter;Verwendungszweck;Soll;Haben\n"
            "01.03.2024;01.03.2024;Stadtwerke Köln;Strom Abschlag 4711;85,00;\n"
            "02.03.2024;02.03.2024;Gast Müller;Anzahlung;;120,00\n")
    path = tmp_path / "export.csv"
    path.write_bytes(text.encode("cp1252"))
    st = parse_statement_file(path)
    assert st.account_iban == "DE89370400440532013000"
    assert [(t.amount_cents, t.counterparty_name) for t in st.transactions] == [(-8500, "Stadtwerke Köln"), (12000, "Gast Müller")]
    assert looks_like_bank_file(path)


def test_csv_without_columns_is_rejected() -> None:
    with pytest.raises(DocumentError):
        parse_csv("a;b;c\n1;2;3\n")


def test_camt053() -> None:
    st = parse_statement_file(FIX / "statement.camt.xml")
    assert st.format == "camt053" and st.account_iban == "DE89370400440532013000"
    assert (st.opening_cents, st.closing_cents) == (1000000, 881000)
    out, inc = st.transactions
    assert out.amount_cents == -119000 and out.counterparty_name == "Müller Bürobedarf GmbH"
    assert out.counterparty_iban == "DE02120300000000202051" and out.purpose == "Rechnung RE-2024/001 Kundennummer 4711"
    assert out.reference == "" and inc.amount_cents == 25000 and inc.counterparty_name == "Gast Meier"
    with pytest.raises(DocumentError):
        parse_camt053(b"<a><b/></a>")
    with pytest.raises(DocumentError):
        parse_camt053(b"not xml")


def test_mt940_structured_info() -> None:
    st = parse_statement_file(FIX / "statement.sta")
    assert st.format == "mt940" and st.account_label == "37040044/0532013000"
    assert (st.opening_cents, st.closing_cents) == (1000000, 906000)
    out, inc = st.transactions
    assert out.amount_cents == -119000 and out.booking_date == date(2024, 3, 5)
    assert out.counterparty_name == "Mueller Buerobedarf GmbH" and out.counterparty_iban == "DE02120300000000202051"
    assert "RE-2024/001" in out.purpose and "4711" in out.purpose and out.booking_text == "ONLINE-UEBERWEISUNG"
    assert inc.amount_cents == 25000 and inc.counterparty_name == "Gast Meier"


def test_mt940_sepa_tags_without_structure() -> None:
    text = (":20:X\n:25:DE89370400440532013000\n:60F:C240301EUR100,00\n:61:2403050305D12,50NMSCNONREF\n"
            ":86:EREF+E2E1 SVWZ+Rechnung 77 IBAN+DE02120300000000202051 ABWA+Foo GmbH\n:62F:C240305EUR87,50\n")
    st = parse_mt940(text)
    tx = st.transactions[0]
    assert st.account_iban == "DE89370400440532013000" and tx.amount_cents == -1250
    assert tx.counterparty_iban == "DE02120300000000202051" and tx.reference == "E2E1"
    with pytest.raises(DocumentError):
        parse_mt940("nothing here")


def test_pdf_text_lines() -> None:
    text = ("Kontoauszug 2024  IBAN DE89 3704 0044 0532 0130 00\n"
            "05.03. 05.03. Überweisung Müller Bürobedarf Rechnung RE-2024/001 1.190,00 S\n"
            "     DE02120300000000202051\n"
            "06.03.2024 Gutschrift Meier 250,00 H\n")
    st = parse_pdf_text(text)
    assert st.account_iban == "DE89370400440532013000" and st.warnings
    assert [t.amount_cents for t in st.transactions] == [-119000, 25000]
    assert st.transactions[0].counterparty_iban == "DE02120300000000202051" and st.transactions[0].booking_date == date(2024, 3, 5)
    with pytest.raises(DocumentError):
        parse_pdf_text("kein Auszug")
