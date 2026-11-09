"""PDF extraction interface for financial reports (master plan M2).

This module has NO PDF dependency. It defines the contract that any PDF reader must meet, so the library
choice
(pdfplumber, pypdf, or none) can be approved later without changing the ingestion, mapping or
reconciliation code.
Owner approval of PDF libraries is pending (decision U3); until then `ExtractionUnavailable` is raised and the
caller records the document as `manual_review` rather than guessing.

Contract
--------
A reader is a callable `read(path) -> DocumentText` that returns, per page, the text lines and (optionally)
tables. Every line keeps its 1-based page number. Nothing is inferred across pages: a value is only ever
linked to
the page it was printed on.

Flow
----
1. `document_metadata(path)` records size, SHA-256 and page count (hashing needs no PDF library).
2. The reader yields pages; `detect_scanned` marks pages with no text layer as `ocr_required`, never guessed.
3. `locate_statements` finds the statement headers (balance sheet, income statement, cash flow, equity) and
   their page ranges, including repeated headers on continuation pages.
4. `to_statement_lines` converts a statement's page lines into line records with page references, using the
   existing `parse_statement_text` rules (bracketed negatives, dashes as not reported, note references).
   Lines that do not parse are returned as `unparsed` for review, never coerced.
5. The result is a RAW extraction. It is never promoted directly: it goes through `financials.import_report`
   (mapping, reconciliation, promotion gate) and then manual review.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from engines.financials import parse_statement_text

HEADERS = {
    "BS": ("statement of financial position", "balance sheet"),
    "IS": ("statement of profit or loss", "income statement", "profit and loss account"),
    "CF": ("statement of cash flows", "cash flow statement"),
    "EQ": ("statement of changes in equity",),
}
# Running headers and footers that repeat across pages are ignored when they match on several pages.
_PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,3}(\s*(of|/)\s*\d{1,3})?\s*$", re.IGNORECASE)
_COMPANY_LINE = re.compile(r"limited|ltd\.?|annual report|consolidated|standalone|unconsolidated",
                           re.IGNORECASE)


class ExtractionUnavailable(RuntimeError):
    """No approved PDF reader is installed. Callers must record manual review, not guess."""


@dataclass
class Page:
    number: int  # 1-based, as printed in the PDF's page order
    lines: list[str]
    has_text: bool
    tables: list[list[list[str]]] = field(default_factory=list)  # optional, reader-specific
    column: str | None = None  # "L" or "R" when a side-by-side page was split into statement columns
    layout_flag: str | None = None  # "uncertain" when the layout could not be established: manual review
    repairs: list[dict] = field(default_factory=list)  # touching-glyph joins, each with its original text


@dataclass
class DocumentText:
    pages: list[Page]


@dataclass
class DocumentMeta:
    path: str
    sha256: str
    size_bytes: int
    page_count: int
    scanned_pages: list[int]


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def document_metadata(path: Path | str, doc: DocumentText) -> DocumentMeta:
    p = Path(path)
    return DocumentMeta(path=p.name, sha256=sha256_file(p), size_bytes=p.stat().st_size,
                        page_count=len(doc.pages),
                        scanned_pages=[pg.number for pg in doc.pages if not pg.has_text])


def strip_running_headers(doc: DocumentText, *, min_pages: int = 3) -> DocumentText:
    """Remove lines that repeat across many pages (company name banners, page numbers). A line is removed only
    when it appears at the top or bottom of at least `min_pages` pages, or is a bare page number. Statement
    values are never removed: a number that repeats as a figure would need to be identical on every page
    and sit
    at a header position to be dropped."""
    edge_counts: dict[str, int] = {}
    for pg in doc.pages:
        for ln in (pg.lines[:2] + pg.lines[-2:] if pg.lines else []):
            edge_counts[ln.strip()] = edge_counts.get(ln.strip(), 0) + 1
    repeated = {t for t, n in edge_counts.items() if n >= min_pages and t and _COMPANY_LINE.search(t)}
    out = []
    for pg in doc.pages:
        keep = [ln for ln in pg.lines
                if ln.strip() not in repeated and not _PAGE_NUMBER.match(ln)]
        out.append(Page(pg.number, keep, pg.has_text, pg.tables))
    return DocumentText(out)


def locate_statements(doc: DocumentText) -> dict[str, list[int]]:
    """Pages where each primary statement appears, including continuation pages that carry the statement's
    heading again. A statement with no heading found is absent from the result: it is never assumed."""
    found: dict[str, list[int]] = {}
    for pg in doc.pages:
        text = " ".join(pg.lines).lower()
        for code, phrases in HEADERS.items():
            if any(ph in text for ph in phrases):
                found.setdefault(code, []).append(pg.number)
    return found


def to_statement_lines(doc: DocumentText, statement: str, pages: list[int], *, columns: list[str]) -> dict:
    """Parse the given pages of one statement into line records. Each record keeps its page number."""
    lines, unparsed = [], []
    for pg in doc.pages:
        if pg.number not in pages:
            continue
        if not pg.has_text:
            unparsed.append({"page": pg.number, "line": None, "reason": "no text layer: OCR required"})
            continue
        if pg.layout_flag == "uncertain":
            unparsed.append({"page": pg.number, "line": None, "reason": (
                "layout uncertain: side-by-side boundary not established, manual review")})
            continue
        parsed = parse_statement_text("\n".join(pg.lines), statement=statement, columns=columns,
                                      page=pg.number)
        tag = {"column": pg.column} if pg.column else {}
        lines.extend({**ln, **tag} for ln in parsed["lines"])
        unparsed.extend({**u, "page": pg.number, **tag} for u in parsed["unparsed"])
    return {"lines": lines, "unparsed": unparsed}


def reader_available() -> bool:
    """True when the approved reader (pdfplumber, owner decision U3) is installed."""
    from engines import pdf_reader

    return pdf_reader.available()


def extract(path: Path | str, reader: Callable[[Path], DocumentText] | None = None) -> DocumentText:
    """Run the injected reader, or the approved pdfplumber reader when none is given. If no reader is
    available, raise ExtractionUnavailable: never fall back to guessing."""
    if reader is None:
        if not reader_available():
            raise ExtractionUnavailable("no PDF reader is installed; record manual review instead")
        from engines import pdf_reader

        reader = pdf_reader.read
    return reader(Path(path))
