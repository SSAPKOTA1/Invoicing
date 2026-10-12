"""Readers for bank statement files: CSV (many German banks), CAMT.053 (XML), MT940 and - best effort - PDF text."""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import date
from pathlib import Path

from supplier_app.bank.model import ParsedStatement, ParsedTransaction
from supplier_app.errors import DocumentError
from supplier_app.util.normalize import normalize_iban, valid_iban

MAX_BYTES = 50 * 1024 * 1024
BANK_SUFFIXES = {".csv", ".xml", ".sta", ".mt940", ".940", ".swi", ".camt", ".txt", ".pdf"}
_IBAN_RX = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{2,4}){3,8}")
_DATE_RX = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})|(\d{4})-(\d{2})-(\d{2})")


# -- helpers -----------------------------------------------------------------------------------------------
def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_cents(text: str) -> int | None:
    """``-1.234,56`` / ``1234.56`` / ``1.234,56-`` / ``1.234,56 S`` -> cents (negative = out)."""
    t = text.strip().replace("€", "").replace("EUR", "").replace(" ", "").replace(" ", "")
    if not t:
        return None
    sign = 1
    if t.endswith(("-", "S", "s")):
        sign, t = -1, t[:-1]
    elif t.endswith(("+", "H", "h")):
        t = t[:-1]
    if t.startswith("-"):
        sign, t = -sign, t[1:]
    elif t.startswith("+"):
        t = t[1:]
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", t):
        return None
    whole, _, frac = t.partition(".")
    return sign * (int(whole) * 100 + int((frac + "00")[:2]))


def parse_day(text: str) -> date | None:
    m = _DATE_RX.search(text or "")
    if not m:
        return None
    try:
        if m.group(1):
            year = int(m.group(3))
            year += 2000 if year < 100 else 0
            return date(year, int(m.group(2)), int(m.group(1)))
        return date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
    except ValueError:
        return None


def find_iban(text: str) -> str:
    """The first valid IBAN in a text (spaces allowed; trailing digits of the next word are cut off by the checksum)."""
    for m in _IBAN_RX.finditer(text.upper()):
        norm = normalize_iban(m.group(0))
        for length in range(min(len(norm), 34), 14, -1):
            if valid_iban(norm[:length]):
                return norm[:length]
    return ""


def _ascii(value: str) -> str:
    return (value.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
            .replace("﻿", "").strip())


# -- CSV ------------------------------------------------------------------------------------------------------
_HEADERS: dict[str, tuple[str, ...]] = {
    "booking": ("buchungstag", "buchungsdatum", "buchung", "datum", "booking date", "date", "bokfoeringsdag"),
    "value": ("valuta", "valutadatum", "wertstellung", "wert", "value date", "wertstellungsdatum"),
    "amount": ("betrag", "betrag (eur)", "betrag in eur", "betrag eur", "umsatz", "amount", "umsatz in eur", "betrag (€)", "betrag in €"),
    "debit": ("soll", "belastung", "ausgang"),
    "credit": ("haben", "gutschrift", "eingang"),
    "name": ("beguenstigter/zahlungspflichtiger", "auftraggeber/empfaenger", "name zahlungsbeteiligter", "empfaenger",
             "auftraggeber", "zahlungsempfaenger", "beguenstigter", "name", "beguenstigter / zahlungspflichtiger",
             "auftraggeber / beguenstigter", "zahlungspflichtiger", "empfaenger/auftraggeber", "partner name", "gegenkonto name"),
    "iban": ("kontonummer/iban", "iban", "iban zahlungsbeteiligter", "iban/kontonummer", "empfaenger iban",
             "gegenkonto", "iban gegenkonto", "kontonummer", "partner iban", "iban/konto"),
    "purpose": ("verwendungszweck", "zweck", "beschreibung", "mitteilung", "buchungstext", "verwendungszweck/mitteilung",
                "details", "text"),
    "text": ("buchungstext", "buchungsart", "umsatzart", "vorgang", "umsatztext"),
    "reference": ("kundenreferenz (end-to-end)", "end-to-end-referenz", "kundenreferenz", "mandatsreferenz", "referenz"),
    "own": ("auftragskonto", "eigene iban", "konto"),
    "currency": ("waehrung", "währung", "currency"),
    "indicator": ("soll/haben", "s/h", "buchungstyp"),
}


def _map_header(cells: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, raw in enumerate(cells):
        cell = _ascii(raw)
        for key, names in _HEADERS.items():
            if cell in names and key not in mapping:
                # "buchungstext" is the purpose when nothing better exists, else the booking text
                mapping[key] = idx
    if "text" in mapping and mapping.get("purpose") == mapping["text"]:
        better = [i for i, c in enumerate(cells) if _ascii(c) in ("verwendungszweck", "zweck", "beschreibung", "mitteilung")]
        if better:
            mapping["purpose"] = better[0]
    return mapping


def _sniff_delimiter(sample: str) -> str:
    counts = {d: sample.count(d) for d in (";", "\t", ",", "|")}
    return max(counts, key=lambda d: counts[d]) if max(counts.values()) else ";"


def parse_csv(text: str) -> ParsedStatement:
    delimiter = _sniff_delimiter("\n".join(text.splitlines()[:30]))
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    out = ParsedStatement("csv")
    header_idx, mapping = -1, {}
    for i, row in enumerate(rows[:60]):
        m = _map_header(row)
        if "booking" in m and ("amount" in m or "debit" in m or "credit" in m):
            header_idx, mapping = i, m
            break
    if header_idx < 0:
        raise DocumentError("Die CSV-Datei hat keine erkennbaren Spalten für Datum und Betrag.")
    for row in rows[:header_idx]:  # preamble ("IBAN;DE..", "Konto: ...")
        joined = " ".join(row)
        iban = find_iban(joined)
        if iban and not out.account_iban:
            out.account_iban = iban
    skipped = 0
    for row in rows[header_idx + 1:]:
        if not any(c.strip() for c in row):
            continue

        def cell(key: str, row: list[str] = row) -> str:
            idx = mapping.get(key)
            return row[idx].strip() if idx is not None and idx < len(row) else ""

        booking = parse_day(cell("booking")) or parse_day(cell("value"))
        amount = parse_cents(cell("amount")) if "amount" in mapping else None
        if amount is None and ("debit" in mapping or "credit" in mapping):
            debit, credit = parse_cents(cell("debit")), parse_cents(cell("credit"))
            amount = (credit or 0) - abs(debit or 0) if (debit or credit) else None
        if amount is not None and cell("indicator").upper() in ("S", "SOLL", "D", "DEBIT") and amount > 0:
            amount = -amount
        if booking is None or amount is None or amount == 0:
            skipped += 1
            continue
        own = cell("own")
        if own and not out.account_iban:
            out.account_iban = find_iban(own)
        iban = find_iban(cell("iban"))
        out.transactions.append(ParsedTransaction(
            booking_date=booking, amount_cents=amount, value_date=parse_day(cell("value")),
            currency=cell("currency") or "EUR", counterparty_name=cell("name"), counterparty_iban=iban,
            purpose=" ".join(cell("purpose").split()), booking_text=cell("text") if mapping.get("text") != mapping.get("purpose") else "",
            reference=cell("reference")))
    if skipped:
        out.warnings.append(f"{skipped} Zeilen ohne Datum oder Betrag wurden übersprungen.")
    return out


# -- CAMT.053 ---------------------------------------------------------------------------------------------------
def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(node: ET.Element, *path: str) -> ET.Element | None:
    cur: ET.Element | None = node
    for name in path:
        if cur is None:
            return None
        cur = next((c for c in cur if _local(c.tag) == name), None)
    return cur


def _text(node: ET.Element | None, *path: str) -> str:
    found = _find(node, *path) if node is not None else None
    return (found.text or "").strip() if found is not None and found.text else ""


def _iter(node: ET.Element, name: str):
    return (e for e in node.iter() if _local(e.tag) == name)


def parse_camt053(raw: bytes) -> ParsedStatement:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise DocumentError("Die XML-Datei ist kein gültiger Kontoauszug (CAMT).") from exc
    out = ParsedStatement("camt053")
    statements = list(_iter(root, "Stmt")) or list(_iter(root, "Rpt"))
    if not statements:
        raise DocumentError("Die XML-Datei enthält keinen Kontoauszug (CAMT.053).")
    for stmt in statements:
        iban = _text(stmt, "Acct", "Id", "IBAN")
        if iban and not out.account_iban:
            out.account_iban = normalize_iban(iban)
        out.bic = out.bic or _text(stmt, "Acct", "Svcr", "FinInstnId", "BIC") or _text(stmt, "Acct", "Svcr", "FinInstnId", "BICFI")
        for bal in (e for e in stmt if _local(e.tag) == "Bal"):
            code = _text(bal, "Tp", "CdOrPrtry", "Cd")
            cents = parse_cents(_text(bal, "Amt"))
            if cents is None:
                continue
            if _text(bal, "CdtDbtInd") == "DBIT":
                cents = -cents
            if code in ("OPBD", "PRCD") and out.opening_cents is None:
                out.opening_cents = cents
            elif code in ("CLBD", "CLAV"):
                out.closing_cents = cents
        for entry in (e for e in stmt if _local(e.tag) == "Ntry"):
            amount = parse_cents(_text(entry, "Amt").replace(",", "."))
            booking = parse_day(_text(entry, "BookgDt", "Dt") or _text(entry, "BookgDt", "DtTm")) or parse_day(
                _text(entry, "ValDt", "Dt"))
            if amount is None or booking is None or amount == 0:
                continue
            outgoing = _text(entry, "CdtDbtInd") == "DBIT"
            if outgoing:
                amount = -amount
            currency = _find(entry, "Amt").attrib.get("Ccy", "EUR") if _find(entry, "Amt") is not None else "EUR"
            details = [d for d in _iter(entry, "TxDtls")] or [entry]
            for det in details:
                party_tag, acct_tag = ("Cdtr", "CdtrAcct") if outgoing else ("Dbtr", "DbtrAcct")
                name = _text(det, "RltdPties", party_tag, "Nm") or _text(det, "RltdPties", party_tag, "Pty", "Nm")
                cp_iban = _text(det, "RltdPties", acct_tag, "Id", "IBAN")
                ustrd = " ".join(" ".join((u.text or "").split()) for u in _iter(det, "Ustrd") if u.text)
                ref = _text(det, "RmtInf", "Strd", "CdtrRefInf", "Ref")
                purpose = " ".join(x for x in (ustrd, ref) if x) or _text(entry, "AddtlNtryInf")
                part = next(_iter(det, "Amt"), None) if len(details) > 1 else None
                part_cents = parse_cents(part.text.replace(",", ".")) if part is not None and part.text else None
                out.transactions.append(ParsedTransaction(
                    booking_date=booking, amount_cents=(-abs(part_cents) if outgoing else abs(part_cents)) if part_cents else amount,
                    value_date=parse_day(_text(entry, "ValDt", "Dt")), currency=currency, counterparty_name=name,
                    counterparty_iban=normalize_iban(cp_iban), purpose=purpose,
                    booking_text=_text(entry, "BkTxCd", "Prtry", "Cd") or _text(entry, "AddtlNtryInf"),
                    reference=_text(det, "Refs", "EndToEndId") if _text(det, "Refs", "EndToEndId") != "NOTPROVIDED" else ""))
    return out


# -- MT940 --------------------------------------------------------------------------------------------------------
_TAG_RX = re.compile(r"^:(\d{2}[A-Z]?):", re.M)
_61_RX = re.compile(r"^(\d{6})(\d{4})?(R?[CD])[A-Z]?(\d+,\d*)([A-Z])(\w{3})?(.*)$", re.S)


def _mt_balance(value: str) -> int | None:
    m = re.match(r"([CD])(\d{6})([A-Z]{3})(\d+,\d*)", value.strip())
    if not m:
        return None
    cents = parse_cents(m.group(4))
    return None if cents is None else (-cents if m.group(1) == "D" else cents)


def _mt_info(info: str) -> tuple[str, str, str, str, str]:
    """name, iban, purpose, booking text, reference from a :86: field (structured ``?20`` or SEPA ``SVWZ+`` style)."""
    flat = info.replace("\r", "").replace("\n", "")
    if "?" in flat and re.search(r"\?\d{2}", flat):
        fields: dict[str, str] = {}
        parts = re.split(r"\?(\d{2})", flat)
        for i in range(1, len(parts) - 1, 2):
            fields[parts[i]] = fields.get(parts[i], "") + parts[i + 1]
        purpose = _join_fields([fields.get(f"{n}", "") for n in range(20, 30)])
        name = _join_fields([fields.get("32", ""), fields.get("33", "")])
        iban = find_iban(fields.get("31", "")) or find_iban(purpose)
        tags = _sepa_tags(purpose)
        return name.strip(), iban, tags.get("SVWZ", purpose).strip(), fields.get("00", "").strip(), tags.get("EREF", "")
    tags = _sepa_tags(flat)
    if tags:
        return (tags.get("ABWA", "") or tags.get("ANAM", "")).strip(), find_iban(tags.get("IBAN", "")) or find_iban(flat), \
            tags.get("SVWZ", flat).strip(), "", tags.get("EREF", "")
    return "", find_iban(flat), flat.strip(), "", ""


def _join_fields(parts: list[str]) -> str:
    """Subfields hold at most 27 characters: a full field continues the word, a shorter one ended it."""
    out, previous = "", ""
    for part in parts:
        if not part:
            continue
        out += part if not out or len(previous) >= 27 else " " + part
        previous = part
    return out


def _sepa_tags(text: str) -> dict[str, str]:
    found = list(re.finditer(r"(EREF|KREF|MREF|CRED|DEBT|SVWZ|ABWA|ABWE|IBAN|BIC|ANAM|PURP|COAM|OAMT)\+", text))
    out: dict[str, str] = {}
    for i, m in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        out.setdefault(m.group(1), text[m.end():end].strip())
    return out


def parse_mt940(text: str) -> ParsedStatement:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    pieces = _TAG_RX.split(text)
    out = ParsedStatement("mt940")
    pending: ParsedTransaction | None = None
    for i in range(1, len(pieces) - 1, 2):
        tag, value = pieces[i], pieces[i + 1].strip("\n")
        if tag == "25":
            out.account_iban = out.account_iban or find_iban(value)
            out.account_label = out.account_label or value.strip()
        elif tag in ("60F", "60M"):
            out.opening_cents = out.opening_cents if out.opening_cents is not None else _mt_balance(value)
        elif tag in ("62F", "62M"):
            out.closing_cents = _mt_balance(value)
        elif tag == "61":
            m = _61_RX.match(value.replace("\n", "\n").strip())
            if not m:
                out.warnings.append(f"Zeile nicht lesbar: {value[:40]}")
                pending = None
                continue
            yymmdd, mmdd, mark, amount, _typ, _rest, tail = m.groups()
            cents = parse_cents(amount) or 0
            year = 2000 + int(yymmdd[:2])
            try:
                value_date = date(year, int(yymmdd[2:4]), int(yymmdd[4:6]))
                booking = value_date
                if mmdd:
                    booking = date(year, int(mmdd[:2]), int(mmdd[2:]))
                    if booking > value_date and (booking - value_date).days > 180:
                        booking = date(year - 1, int(mmdd[:2]), int(mmdd[2:]))
            except ValueError:
                out.warnings.append(f"Datum nicht lesbar: {value[:20]}")
                pending = None
                continue
            if mark.endswith("D"):
                cents = -cents
            if mark.startswith("R"):
                cents = -cents  # reversal
            ref = tail.split("\n")[0].split("//")[0].strip()
            pending = ParsedTransaction(booking_date=booking, amount_cents=cents, value_date=value_date,
                                        reference=ref if ref and ref != "NONREF" else "")
            if cents:
                out.transactions.append(pending)
        elif tag == "86" and pending is not None:
            name, iban, purpose, btext, eref = _mt_info(value)
            pending.counterparty_name, pending.counterparty_iban = name, iban
            pending.purpose, pending.booking_text = " ".join(purpose.split()), btext
            pending.reference = eref or pending.reference
            pending = None
    if not out.transactions and not out.warnings:
        raise DocumentError("Die Datei enthält keine Buchungen (MT940).")
    return out


# -- PDF (text based, best effort) -------------------------------------------------------------------------
_PDF_LINE = re.compile(
    r"^\s*(?P<d>\d{2}\.\d{2}\.(?:\d{4}|\d{2})?)\s+(?:(?P<v>\d{2}\.\d{2}\.(?:\d{4}|\d{2})?)\s+)?(?P<rest>.+?)\s+"
    r"(?P<amt>[+-]?\d{1,3}(?:\.\d{3})*,\d{2}\s?[+\-SH]?)\s*$")


def parse_pdf_text(text: str) -> ParsedStatement:
    """Statements printed as PDF: one booking per line with date ... amount; following lines continue the text."""
    out = ParsedStatement("pdf")
    out.account_iban = find_iban(text)
    year = None
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        year = int(m.group(1))
    current: ParsedTransaction | None = None
    for line in text.splitlines():
        hit = _PDF_LINE.match(line)
        if hit:
            day = parse_day(hit.group("d") if len(hit.group("d")) > 6 else f"{hit.group('d')}{year or date.today().year}")
            cents = parse_cents(hit.group("amt"))
            if day is None or not cents:
                current = None
                continue
            current = ParsedTransaction(booking_date=day, amount_cents=cents, purpose=" ".join(hit.group("rest").split()),
                                        value_date=parse_day(hit.group("v") or ""))
            out.transactions.append(current)
        elif current is not None and line.strip() and not re.match(r"^\s*(Seite|Kontoauszug|IBAN|BIC|Alter|Neuer)", line, re.I):
            current.purpose = f"{current.purpose} {' '.join(line.split())}".strip()
        elif not line.strip():
            current = None
    for tx in out.transactions:  # first IBAN in the text of a line is the counterparty
        tx.counterparty_iban = find_iban(tx.purpose)
    if not out.transactions:
        raise DocumentError("Im PDF wurden keine Buchungszeilen erkannt. Bitte besser CSV, CAMT oder MT940 exportieren.")
    out.warnings.append("PDF-Kontoauszug: bitte die erkannten Buchungen sorgfältig prüfen.")
    return out


# -- entry point --------------------------------------------------------------------------------------------------
def looks_like_bank_file(path: Path) -> bool:
    """Cheap check by name/content (used to route files dropped on the documents page)."""
    suffix = path.suffix.lower()
    if suffix in (".sta", ".mt940", ".940", ".swi", ".camt"):
        return True
    try:
        head = path.read_bytes()[:4096]
    except OSError:
        return False
    text = decode(head)
    if suffix == ".xml":
        return "camt." in text or "BkToCstmrStmt" in text
    if suffix in (".csv", ".txt"):
        if ":20:" in text and ":61:" in text or ":60F:" in text:
            return True
        return suffix == ".csv" and any("booking" in _map_header(r) for r in csv.reader(io.StringIO(text), delimiter=_sniff_delimiter(text)))
    return False


def parse_statement_file(path: Path, pdf_text: Callable[[Path], str] | None = None) -> ParsedStatement:
    path = Path(path)
    if not path.is_file():
        raise DocumentError(f"Die Datei '{path.name}' wurde nicht gefunden.")
    if path.stat().st_size > MAX_BYTES:
        raise DocumentError(f"Die Datei '{path.name}' ist zu groß.")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        if pdf_text is None:
            raise DocumentError("PDF-Kontoauszüge können hier nicht gelesen werden.")
        return parse_pdf_text(pdf_text(path))
    raw = path.read_bytes()
    text = decode(raw)
    stripped = text.lstrip()
    if stripped.startswith("<") or suffix in (".xml", ".camt"):
        return parse_camt053(raw)
    if (":20:" in text and (":61:" in text or ":60F:" in text)) or suffix in (".sta", ".mt940", ".940", ".swi"):
        return parse_mt940(text)
    return parse_csv(text)
