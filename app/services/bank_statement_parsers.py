from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Sequence

# Element (type) and ParseError (malformed-XML exception) are not parsers — the
# XXE vector is XML *parsing*, which uses defusedxml above. Type/exception-only
# import, so the use-defused-xml rule is suppressed on this line.
from xml.etree.ElementTree import Element, ParseError  # nosemgrep

import defusedxml.ElementTree as DefusedET

from app.services.csv_ingestion_service import _parse_amount, _parse_date

_SUPPORTED_OFX_BANKS = {"bradesco", "itau", "bb", "caixa"}
_OFX_1_STMTTRN_RE = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL | re.IGNORECASE)
_OFX_1_FIELD_RE = re.compile(r"<(?P<tag>[A-Z0-9_]+)>(?P<value>[^\r\n<]+)")


@dataclass(frozen=True)
class ParsedEntry:
    external_id: str
    date: date
    description: str
    amount: Decimal
    transaction_type: str
    bank_name: str


def parse_ofx(content: str, bank_name: str) -> list[ParsedEntry]:
    normalized_bank = bank_name.strip().lower()
    if normalized_bank not in _SUPPORTED_OFX_BANKS:
        raise ValueError(f"Unsupported OFX bank: {bank_name!r}")

    stripped = content.lstrip()
    if stripped.startswith(("<?xml", "<OFX>")):
        return _parse_ofx_xml(content, normalized_bank)
    return _parse_ofx_sgml(content, normalized_bank)


def parse_nubank_csv(content: str) -> list[ParsedEntry]:
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames is None:
        raise ValueError("Nubank CSV is empty or missing header")

    header_map = {field.strip().lower(): field for field in reader.fieldnames}
    required = {"date", "title", "amount"}
    missing = sorted(required - set(header_map))
    if missing:
        raise ValueError("Nubank CSV missing required columns: " + ", ".join(missing))

    entries: list[ParsedEntry] = []
    for row in reader:
        date_raw = _read_csv_value(row, header_map["date"])
        title_raw = _read_csv_value(row, header_map["title"])
        amount_raw = _read_csv_value(row, header_map["amount"])
        if not date_raw or not title_raw or not amount_raw:
            raise ValueError("Nubank CSV row missing date, title or amount")

        parsed_date = _parse_date(date_raw)
        parsed_amount = _parse_amount(amount_raw)
        description = _normalize_description(title_raw)
        entries.append(
            ParsedEntry(
                external_id=_build_csv_external_id(
                    parsed_date=parsed_date,
                    description=description,
                    amount=parsed_amount,
                ),
                date=parsed_date,
                description=description,
                amount=parsed_amount,
                transaction_type=_resolve_transaction_type(parsed_amount),
                bank_name="nubank",
            )
        )

    if not entries:
        raise ValueError("Nubank CSV has no transaction rows")
    return entries


def _parse_ofx_xml(content: str, bank_name: str) -> list[ParsedEntry]:
    try:
        root = DefusedET.fromstring(content)
    except ParseError as exc:
        raise ValueError("Invalid OFX XML content") from exc

    statement_nodes = list(root.iterfind(".//STMTTRN"))
    if not statement_nodes:
        statement_nodes = [
            node for node in root.iter() if _local_name(node.tag) == "STMTTRN"
        ]
    if not statement_nodes:
        raise ValueError("OFX content missing STMTTRN blocks")
    return _build_ofx_entries(statement_nodes, bank_name=bank_name)


def _parse_ofx_sgml(content: str, bank_name: str) -> list[ParsedEntry]:
    matches = _OFX_1_STMTTRN_RE.findall(content)
    if not matches:
        raise ValueError("OFX content missing STMTTRN blocks")

    statement_nodes: list[dict[str, str]] = []
    for raw_block in matches:
        fields = {
            match.group("tag").upper(): match.group("value").strip()
            for match in _OFX_1_FIELD_RE.finditer(raw_block)
        }
        statement_nodes.append(fields)

    return _build_ofx_entries(statement_nodes, bank_name=bank_name)


def _build_ofx_entries(
    statement_nodes: Sequence[Element | dict[str, str]],
    *,
    bank_name: str,
) -> list[ParsedEntry]:
    entries: list[ParsedEntry] = []
    for node in statement_nodes:
        fit_id = _extract_ofx_value(node, "FITID")
        posted_at = _extract_ofx_value(node, "DTPOSTED")
        amount_raw = _extract_ofx_value(node, "TRNAMT")
        description_raw = _extract_ofx_value(node, "MEMO") or _extract_ofx_value(
            node, "NAME"
        )

        if not fit_id or not posted_at or not amount_raw or not description_raw:
            raise ValueError(
                "OFX transaction missing FITID, DTPOSTED, TRNAMT or MEMO/NAME"
            )

        amount = _parse_ofx_amount(amount_raw)
        entries.append(
            ParsedEntry(
                external_id=fit_id,
                date=_parse_ofx_date(posted_at),
                description=_normalize_description(description_raw),
                amount=amount,
                transaction_type=_resolve_transaction_type(amount),
                bank_name=bank_name,
            )
        )

    if not entries:
        raise ValueError("OFX content has no transaction rows")
    return entries


def _extract_ofx_value(
    node: Element | dict[str, str],
    field_name: str,
) -> str | None:
    if isinstance(node, dict):
        value = node.get(field_name)
        return value.strip() if value else None

    for child in node:
        if _local_name(child.tag) != field_name:
            continue
        if child.text is None:
            return None
        return child.text.strip()
    return None


def _parse_ofx_date(raw_value: str) -> date:
    digits = "".join(char for char in raw_value if char.isdigit())
    if len(digits) < 8:
        raise ValueError(f"Invalid OFX date: {raw_value!r}")
    return datetime.strptime(digits[:8], "%Y%m%d").date()


def _parse_ofx_amount(raw_value: str) -> Decimal:
    try:
        return Decimal(raw_value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"Invalid OFX amount: {raw_value!r}") from exc


def _resolve_transaction_type(amount: Decimal) -> str:
    return "income" if amount >= Decimal("0") else "expense"


def _build_csv_external_id(
    *,
    parsed_date: date,
    description: str,
    amount: Decimal,
) -> str:
    payload = f"{parsed_date.isoformat()}|{description}|{amount}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _normalize_description(raw_value: str) -> str:
    normalized = " ".join(raw_value.strip().split())
    if not normalized:
        raise ValueError("Transaction description cannot be empty")
    return normalized


def _read_csv_value(row: dict[str, str | None], column_name: str) -> str | None:
    value = row.get(column_name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1].upper()


__all__ = ["ParsedEntry", "parse_nubank_csv", "parse_ofx"]
