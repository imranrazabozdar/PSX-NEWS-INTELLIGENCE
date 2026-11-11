"""Parsers for offline PSX export files: the listed-company directory and the announcements feed.

Both exports were supplied as ZIP archives (despite a `.Z` extension). They are read in memory with
`zipfile` (gzip and plain text are accepted too), decoded as latin-1, and parsed line by line. Nothing here
touches the network or the database.

Layouts (detected from the supplied files, see docs/PSX_EXPORT_FORMATS.md):

listed_cmp.lst: 8 pipe-separated fields per row, one company per row.
    [0] empty   [1] symbol   [2] company name   [3] sector code   [4] sector name
    [5] an unlabelled number (kept as `numeric_field`, not interpreted)   [6] empty   [7] empty

announceWithSymbol.lis: 5 or 6 pipe-separated fields per row, one announcement per row.
    [0] symbol   [1] company name   [2] date (DDMonYYYY)   [3] time (HH:MM:SS)   [4] title / subject
    [5] (optional) a numeric document ID. The supplied export carries no document ID: the field is empty on
        every row, so `doc_id` is None unless a future export provides one. No link is ever invented.

Malformed rows are logged and skipped; the batch continues. Comment lines (starting with '#') and blank
lines are skipped without a log entry.
"""

from __future__ import annotations

import gzip
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import BinaryIO

log = logging.getLogger(__name__)
ENCODING = "latin-1"
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.&\-]{0,14}$")
_DIGITS = re.compile(r"^\d+$")
_DATE = re.compile(r"^\d{2}[A-Za-z]{3}\d{4}$")


@dataclass(frozen=True)
class ListedCompany:
    """One row of the listed-company directory. Validated on construction; a bad value raises ValueError."""

    symbol: str
    company_name: str
    sector_code: str
    sector: str
    line_no: int
    numeric_field: int | None = None  # the unlabelled numeric column, not interpreted
    status_flags: tuple[str, ...] = field(default=())  # this export carries no status flags

    def __post_init__(self) -> None:
        _check_symbol(self.symbol)


@dataclass(frozen=True)
class Announcement:
    """One announcement row. `doc_id` is set only when the export carries a numeric document ID."""

    symbol: str
    company_name: str
    announced_on: date
    announced_time: time | None
    title: str | None
    line_no: int
    doc_id: int | None = None

    def __post_init__(self) -> None:
        _check_symbol(self.symbol)


def _check_symbol(symbol: str) -> None:
    if not _SYMBOL.match(symbol):
        raise ValueError(f"symbol {symbol!r} is not an upper-case PSX ticker")


# ------------------------------------------------------------------ reading the export


def _is_file(text: str) -> bool:
    """True only for an existing file path. Long text or NUL bytes are not paths."""
    try:
        return Path(text).is_file()
    except (OSError, ValueError):
        return False


def read_text(source: str | Path | bytes | BinaryIO) -> str:
    """The export as text. ZIP (first member) and gzip are unpacked in memory; anything else is taken as plain
    text. Always decoded as latin-1. A str is a file path when that file exists, else it is the text."""
    if isinstance(source, Path) or (isinstance(source, str) and _is_file(source)):
        data = Path(source).read_bytes()
    elif isinstance(source, str):
        return source  # already text (not a path); no ZIP or gzip to unpack
    elif isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    else:
        data = source.read()
    if data[:2] == b"PK" and data[2:4] in (
        b"\x03\x04",
        b"\x05\x06",
    ):  # a ZIP (an empty one has no local header)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            members = [i for i in z.infolist() if not i.is_dir()]
            if not members:
                raise ValueError("the ZIP archive has no file in it")
            data = z.read(members[0].filename)
    elif data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data.decode(ENCODING)


def _content_lines(text: str):
    for n, raw in enumerate(text.splitlines(), start=1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        yield n, raw


# ------------------------------------------------------------------ parsers


def parse_listed_companies(source: str | Path | bytes | BinaryIO) -> list[ListedCompany]:
    """Validated records of the listed-company directory. Malformed rows are logged and skipped."""
    records, _ = parse_listed_companies_report(source)
    return records


def parse_listed_companies_report(source) -> tuple[list[ListedCompany], list[tuple[int, str]]]:
    records: list[ListedCompany] = []
    skipped: list[tuple[int, str]] = []
    for n, raw in _content_lines(read_text(source)):
        f = raw.split("|")
        try:
            if len(f) != 8:
                raise ValueError(f"expected 8 fields, found {len(f)}")
            symbol, name, code, sector = (x.strip() for x in f[1:5])
            if not name or not code or not sector:
                raise ValueError("company name, sector code or sector is empty")
            num = f[5].strip()
            if num and not _DIGITS.match(num):
                raise ValueError("numeric field is not a whole number")
            records.append(
                ListedCompany(
                    symbol=symbol,
                    company_name=name,
                    sector_code=code,
                    sector=sector,
                    numeric_field=int(num) if num else None,
                    line_no=n,
                )
            )
        except ValueError as exc:
            skipped.append((n, str(exc)))
            log.warning("listed_cmp line %d skipped: %s", n, exc)
    return records, skipped


def parse_announcements(source: str | Path | bytes | BinaryIO) -> list[Announcement]:
    """Validated announcement rows. Malformed rows are logged and skipped."""
    records, _ = parse_announcements_report(source)
    return records


def parse_announcements_report(source) -> tuple[list[Announcement], list[tuple[int, str]]]:
    records: list[Announcement] = []
    skipped: list[tuple[int, str]] = []
    for n, raw in _content_lines(read_text(source)):
        f = raw.split("|")
        if f and not f[-1].strip():
            f = f[:-1]  # every record ends with a pipe; the empty field after it is the terminator
        try:
            if len(f) not in (4, 5, 6):
                raise ValueError(f"expected 4 to 6 fields after the terminator, found {len(f)}")
            symbol = f[0].strip()
            name = f[1].strip()
            d = f[2].strip()
            t = f[3].strip()
            title = (f[4].strip() or None) if len(f) >= 5 else None
            if not _DATE.match(d):
                raise ValueError(f"date {d!r} is not DDMonYYYY")
            announced_on = datetime.strptime(d, "%d%b%Y").date()
            announced_time = datetime.strptime(t, "%H:%M:%S").time() if t else None
            doc = f[5].strip() if len(f) == 6 else ""
            if doc and not _DIGITS.match(doc):
                raise ValueError(f"document ID field {doc!r} is not numeric")
            doc_id = int(doc) if doc else None
            records.append(
                Announcement(
                    symbol=symbol,
                    company_name=name,
                    announced_on=announced_on,
                    announced_time=announced_time,
                    title=title,
                    doc_id=doc_id,
                    line_no=n,
                )
            )
        except ValueError as exc:
            skipped.append((n, str(exc)))
            log.warning("announceWithSymbol line %d skipped: %s", n, exc)
    return records, skipped
