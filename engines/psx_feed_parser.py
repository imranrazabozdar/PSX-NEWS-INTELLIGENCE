"""
psx_feed_parser.py
==================

In-memory unpacker and parser for the Pakistan Stock Exchange (PSX) public
dissemination feed.

PSX distributes two PKZip-compressed, latin-1 encoded text archives:

  * ``listed_cmp.lst``          -> master directory of listed companies.
  * ``announceWithSymbol.lis``  -> rolling corporate-disclosure announcements.

The byte layout is described by PSX as "fixed-width / delimited", which in
practice means the records are delimited but the delimiter and column order
have drifted across the legacy system's history. The parser therefore:

  * detects the delimiter per-record (pipe, tab, or runs of whitespace);
  * maps tokens positionally via named, easy-to-retune column constants;
  * validates and coerces each record through a frozen dataclass (``__post_init__``);
  * logs and SKIPS any corrupted row instead of aborting the batch.

Standard library only. Pydantic was requested but is not admitted by the independence
guard (see the ADR-0001 review record), so the models are validated frozen dataclasses.

NOTE ON FIELD OFFSETS: the COLUMN index constants below encode the layout we
expect. If PSX hands you a sample with a different order, retune the constants
in one place -- the parsing logic itself does not change.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date as _Date
from datetime import datetime
from datetime import time as _Time

logger = logging.getLogger("psx.parser")

# --------------------------------------------------------------------------- #
# Archive handling
# --------------------------------------------------------------------------- #

LATIN1 = "latin-1"


def unpack_member(data: bytes, member_suffix: str | None = None) -> str:
    """Open a PKZip archive held entirely in memory and return one member's text.

    Parameters
    ----------
    data:
        Raw bytes of the ``.zip`` archive (e.g. an HTTP response body).
    member_suffix:
        Case-insensitive filename suffix to select (``".lis"`` / ``".lst"``).
        When ``None`` the first regular file in the archive is used.

    Returns
    -------
    The decoded (latin-1) text of the selected member.
    """
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        if not names:
            raise ValueError("archive contains no files")

        if member_suffix is not None:
            match = [n for n in names if n.lower().endswith(member_suffix.lower())]
            if not match:
                raise ValueError(f"no member ending with {member_suffix!r}; have {names!r}")
            target = match[0]
        else:
            target = names[0]

        raw = zf.read(target)
    return raw.decode(LATIN1)


# --------------------------------------------------------------------------- #
# Record tokenisation
# --------------------------------------------------------------------------- #

_WHITESPACE_RUN = re.compile(r"\s{2,}")


def split_record(line: str) -> list[str]:
    """Tokenise one feed line, auto-detecting the delimiter.

    Order of preference: pipe -> tab -> runs of 2+ spaces. Tokens are stripped
    and empty edge tokens are preserved positionally so column indices stay
    stable.
    """
    if "|" in line:
        parts = line.split("|")
    elif "\t" in line:
        parts = line.split("\t")
    else:
        parts = _WHITESPACE_RUN.split(line.strip())
    return [p.strip() for p in parts]


# --------------------------------------------------------------------------- #
# Date / time / doc-id coercion
# --------------------------------------------------------------------------- #

_DATE_FORMATS = ("%Y-%m-%d", "%d-%b-%Y", "%d%b%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d")
_TIME_FORMATS = ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p")

# Matches the canonical statutory PDF URL and bare numeric ids.
_DOC_URL_RE = re.compile(r"/document/(\d+)\.pdf", re.IGNORECASE)
_DOC_NUM_RE = re.compile(r"\b(\d{3,})\b")


def coerce_date(value: str) -> _Date:
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {value!r}")


def coerce_time(value: str) -> _Time | None:
    value = value.strip()
    if not value:
        return None
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(value.upper(), fmt).time()
        except ValueError:
            continue
    raise ValueError(f"unparseable time: {value!r}")


def extract_doc_id(*candidates: str) -> int | None:
    """Pull the numeric document id from any of the supplied tokens.

    Prefers an explicit ``/document/<id>.pdf`` URL, then a bare numeric token.
    Returns ``None`` when nothing id-like is present (common for pure-text
    notices that carry no attachment).
    """
    for token in candidates:
        if not token:
            continue
        m = _DOC_URL_RE.search(token)
        if m:
            return int(m.group(1))
    for token in candidates:
        if token and token.isdigit():
            return int(token)
    for token in candidates:
        if not token:
            continue
        m = _DOC_NUM_RE.search(token)
        if m:
            return int(m.group(1))
    return None


# Ordered title-keyword -> canonical category. First match wins. The live
# announceWithSymbol.lis carries no category column, so we derive it.
_CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("financial results", "Financial Results"),
    ("financial statement", "Financial Results"),
    ("board meeting", "Board Meeting"),
    ("material information", "Material Information"),
    ("dividend", "Dividend"),
    ("annual report", "Annual Report"),
    ("agm", "AGM"),
    ("general meeting", "General Meeting"),
    ("credit rating", "Credit Rating"),
)


def derive_category(title: str) -> str | None:
    """Map a disclosure title to a coarse category via keyword match.

    Returns ``None`` when nothing recognisable is present, leaving downstream
    routing to treat it as a generic notice.
    """
    haystack = (title or "").lower()
    for keyword, canonical in _CATEGORY_KEYWORDS:
        if keyword in haystack:
            return canonical
    return None


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #


def _clean_symbol(value: str) -> str:
    value = (value or "").strip().upper()
    if not value:
        raise ValueError("empty symbol")
    return value


@dataclass(frozen=True)
class CompanyMaster:
    """One row of ``listed_cmp.lst``.

    Layout: ``|SYMBOL|COMPANY_NAME|SECTOR_CODE|SECTOR_NAME|...`` (leading pipe
    produces an empty token[0]).
    """

    symbol: str
    name: str
    sector_code: str | None = None
    sector: str | None = None  # sector NAME

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _clean_symbol(self.symbol))


@dataclass(frozen=True)
class StatutoryAnnouncement:
    """One row of ``announceWithSymbol.lis``.

    Layout: ``SYMBOL|COMPANY_NAME|DATE|TIME|TITLE|`` (trailing pipe). The feed
    carries no doc_id and no explicit category: ``doc_id`` stays ``None`` and
    ``category`` is derived from the title.
    """

    date: _Date
    time: _Time | None
    symbol: str
    company_name: str | None
    category: str | None
    title: str = ""
    doc_id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _clean_symbol(self.symbol))
        if self.doc_id is not None and (not isinstance(self.doc_id, int) or self.doc_id < 1):
            raise ValueError(f"doc_id must be a positive integer, got {self.doc_id!r}")


# --------------------------------------------------------------------------- #
# Column layouts  (retune here if PSX ships a different order)
# --------------------------------------------------------------------------- #


class AnnouncementColumns:
    # SYMBOL|COMPANY_NAME|DATE|TIME|TITLE|  (trailing pipe)
    SYMBOL = 0
    COMPANY_NAME = 1
    DATE = 2
    TIME = 3
    TITLE = 4
    MIN_TOKENS = 4  # symbol, company_name, date, time are the hard minimum


class CompanyColumns:
    # |SYMBOL|COMPANY_NAME|SECTOR_CODE|SECTOR_NAME|...  (leading pipe -> empty [0])
    SYMBOL = 1
    NAME = 2
    SECTOR_CODE = 3
    SECTOR = 4
    MIN_TOKENS = 3  # empty-lead + symbol + name


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #


def _iter_lines(text: str) -> Iterator[str]:
    for line in text.splitlines():
        if line.strip():
            yield line


def _get(tokens: Sequence[str], idx: int, default: str = "") -> str:
    return tokens[idx] if 0 <= idx < len(tokens) else default


def parse_announcements(text: str) -> list[StatutoryAnnouncement]:
    """Parse ``announceWithSymbol.lis`` text into validated announcements.

    Corrupted rows are logged at WARNING and skipped; the batch always
    completes.
    """
    C = AnnouncementColumns
    out: list[StatutoryAnnouncement] = []
    for lineno, line in enumerate(_iter_lines(text), start=1):
        tokens = split_record(line)
        if len(tokens) < C.MIN_TOKENS:
            logger.warning("announce L%d: too few columns (%d): %r", lineno, len(tokens), line[:120])
            continue
        try:
            title = _get(tokens, C.TITLE)
            record = StatutoryAnnouncement(
                date=coerce_date(_get(tokens, C.DATE)),
                time=coerce_time(_get(tokens, C.TIME)),
                symbol=_get(tokens, C.SYMBOL),
                company_name=_get(tokens, C.COMPANY_NAME) or None,
                category=derive_category(title),
                title=title,
                doc_id=None,  # feed carries no attachment id
            )
        except Exception as exc:  # noqa: BLE001 - defensive per-row isolation
            logger.warning("announce L%d: skipped (%s): %r", lineno, exc, line[:120])
            continue
        out.append(record)
    logger.info("parsed %d announcements", len(out))
    return out


def parse_company_master(text: str) -> list[CompanyMaster]:
    """Parse ``listed_cmp.lst`` text into validated company rows.

    Corrupted rows are logged at WARNING and skipped.
    """
    C = CompanyColumns
    out: list[CompanyMaster] = []
    for lineno, line in enumerate(_iter_lines(text), start=1):
        tokens = split_record(line)
        if len(tokens) < C.MIN_TOKENS:
            logger.warning("master L%d: too few columns (%d): %r", lineno, len(tokens), line[:120])
            continue
        try:
            record = CompanyMaster(
                symbol=_get(tokens, C.SYMBOL),
                name=_get(tokens, C.NAME),
                sector_code=_get(tokens, C.SECTOR_CODE) or None,
                sector=_get(tokens, C.SECTOR) or None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("master L%d: skipped (%s): %r", lineno, exc, line[:120])
            continue
        out.append(record)
    logger.info("parsed %d companies", len(out))
    return out


# --------------------------------------------------------------------------- #
# Convenience: bytes -> models in one call
# --------------------------------------------------------------------------- #


def load_announcements(archive_bytes: bytes) -> list[StatutoryAnnouncement]:
    return parse_announcements(unpack_member(archive_bytes, ".lis"))


def load_company_master(archive_bytes: bytes) -> list[CompanyMaster]:
    return parse_company_master(unpack_member(archive_bytes, ".lst"))


def index_by_symbol(companies: Iterable[CompanyMaster]) -> dict[str, CompanyMaster]:
    return {c.symbol: c for c in companies}
