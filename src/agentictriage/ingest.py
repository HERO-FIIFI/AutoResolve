from __future__ import annotations

import csv
import io
from collections.abc import Iterator

from pydantic import BaseModel, ValidationError

from .models import Ticket

# ponytail: a flat row cap keeps one upload from queueing unbounded work.
# Raise it, or stream straight to the queue, when someone actually needs more.
MAX_ROWS = 5_000

REQUIRED_COLUMNS = ("id", "subject", "body")
OPTIONAL_COLUMNS = ("region", "regulated")

_TRUTHY = frozenset({"true", "yes", "y", "1"})
_FALSEY = frozenset({"false", "no", "n", "0", ""})
_XLSX_MAGIC = b"PK\x03\x04"


class RowError(BaseModel):
    """A single row that could not be turned into a Ticket."""

    row: int
    error: str


class ParsedSheet(BaseModel):
    tickets: list[Ticket]
    errors: list[RowError]


class SheetFormatError(ValueError):
    """The file as a whole is unusable - wrong format, or missing headers."""


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def _rows_from_csv(data: bytes) -> Iterator[list[str]]:
    # utf-8-sig strips the BOM Excel writes on "CSV UTF-8" export.
    text = data.decode("utf-8-sig", errors="replace")
    for row in csv.reader(io.StringIO(text)):
        yield [_cell(cell) for cell in row]


def _rows_from_xlsx(data: bytes) -> Iterator[list[str]]:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises assorted types on malformed input
        raise SheetFormatError("file is not a readable .xlsx workbook") from exc
    try:
        worksheet = workbook.worksheets[0]
        for row in worksheet.iter_rows(values_only=True):
            yield [_cell(cell) for cell in row]
    finally:
        workbook.close()


def _is_xlsx(data: bytes, filename: str) -> bool:
    # Trust the magic bytes over the filename; a mislabelled .csv is common.
    return data[:4] == _XLSX_MAGIC or filename.lower().endswith((".xlsx", ".xlsm"))


def _parse_regulated(raw: str) -> bool:
    lowered = raw.lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSEY:
        return False
    # `regulated` drives compliance routing, so an unrecognised value is an
    # error rather than a silent False.
    raise ValueError(f"regulated must be true/false, got {raw!r}")


def _header_index(header: list[str]) -> dict[str, int]:
    index: dict[str, int] = {}
    for position, name in enumerate(header):
        key = name.strip().lower()
        if key and key not in index:
            index[key] = position
    missing = [column for column in REQUIRED_COLUMNS if column not in index]
    if missing:
        raise SheetFormatError(f"missing required column(s): {', '.join(missing)}")
    return index


def _ticket(row: list[str], index: dict[str, int], tenant_id: str) -> Ticket:
    def value(column: str) -> str:
        position = index.get(column, -1)
        return row[position] if 0 <= position < len(row) else ""

    fields: dict[str, object] = {
        "id": value("id"),
        "tenant_id": tenant_id,
        "subject": value("subject"),
        "body": value("body"),
        "regulated": _parse_regulated(value("regulated")),
    }
    if region := value("region"):
        fields["region"] = region
    return Ticket.model_validate(fields)


def parse_tickets(data: bytes, filename: str, *, tenant_id: str) -> ParsedSheet:
    """Turn an uploaded CSV or .xlsx sheet into Tickets, row errors and all.

    tenant_id comes from the caller's token, never the file - the API rejects
    any ticket whose tenant does not match the principal.
    """
    if not data:
        raise SheetFormatError("file is empty")

    rows = _rows_from_xlsx(data) if _is_xlsx(data, filename) else _rows_from_csv(data)

    index: dict[str, int] | None = None
    tickets: list[Ticket] = []
    errors: list[RowError] = []

    for number, row in enumerate(rows, start=1):
        if not any(cell for cell in row):
            continue  # trailing blank rows are normal in spreadsheets
        if index is None:
            index = _header_index(row)
            continue
        if len(tickets) + len(errors) >= MAX_ROWS:
            raise SheetFormatError(f"file exceeds the {MAX_ROWS} row limit")
        try:
            tickets.append(_ticket(row, index, tenant_id))
        except (ValidationError, ValueError) as exc:
            errors.append(RowError(row=number, error=_first_message(exc)))

    if index is None:
        raise SheetFormatError("file has no header row")
    return ParsedSheet(tickets=tickets, errors=errors)


def _first_message(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        problems = exc.errors()
        if problems:
            location = ".".join(str(part) for part in problems[0]["loc"]) or "row"
            return f"{location}: {problems[0]['msg']}"
    return str(exc)
