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
_COMPANY_LINE = re.compile(
    r"limited|ltd\.?|annual report|consolidated|standalone|unconsolidated", re.IGNORECASE
)


class ExtractionUnavailable(RuntimeError):
    """No approved PDF reader is installed. Callers must record manual review, not guess."""


@dataclass
class Page:
    number: int  # 1-based, as printed in the PDF's page order
    lines: list[str]
    has_text: bool
    tables: list[list[list[str]]] = field(default_factory=list)  # optional, reader-specific
    # Provenance: which engine produced `lines`. "pdfplumber", "pdftotext_layout",
    # "pdfplumber_unverified" (not cross-checked: pdftotext unavailable or empty for the page), or
    # "no_text" (neither engine found text).
    extraction_method: str = "pdfplumber"
    agreement: dict | None = None  # cross-check metrics when both engines were run on the page


@dataclass
class DocumentText:
    pages: list[Page]
    warnings: list[str] = field(default_factory=list)

    def method_counts(self) -> dict[str, int]:
        """Pages per extraction method, for the run's provenance record."""
        counts: dict[str, int] = {}
        for pg in self.pages:
            counts[pg.extraction_method] = counts.get(pg.extraction_method, 0) + 1
        return dict(sorted(counts.items()))


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
    return DocumentMeta(
        path=p.name,
        sha256=sha256_file(p),
        size_bytes=p.stat().st_size,
        page_count=len(doc.pages),
        scanned_pages=[pg.number for pg in doc.pages if not pg.has_text],
    )


def strip_running_headers(doc: DocumentText, *, min_pages: int = 3) -> DocumentText:
    """Remove lines that repeat across many pages (company name banners, page numbers). A line is removed only
    when it appears at the top or bottom of at least `min_pages` pages, or is a bare page number. Statement
    values are never removed: a number that repeats as a figure would need to be identical on every page
    and sit
    at a header position to be dropped."""
    edge_counts: dict[str, int] = {}
    for pg in doc.pages:
        for ln in pg.lines[:2] + pg.lines[-2:] if pg.lines else []:
            edge_counts[ln.strip()] = edge_counts.get(ln.strip(), 0) + 1
    repeated = {t for t, n in edge_counts.items() if n >= min_pages and t and _COMPANY_LINE.search(t)}
    out = []
    for pg in doc.pages:
        keep = [ln for ln in pg.lines if ln.strip() not in repeated and not _PAGE_NUMBER.match(ln)]
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
    """Parse the given pages of one statement into line records. Each record keeps its page number and the
    extraction method of its page."""
    lines, unparsed = [], []
    for pg in doc.pages:
        if pg.number not in pages:
            continue
        if not pg.has_text:
            unparsed.append({"page": pg.number, "line": None, "reason": "no text layer: OCR required"})
            continue
        parsed = parse_statement_text(
            "\n".join(pg.lines), statement=statement, columns=columns, page=pg.number
        )
        lines.extend({**ln, "extraction_engine": pg.extraction_method} for ln in parsed["lines"])
        unparsed.extend(
            {**u, "page": pg.number, "extraction_engine": pg.extraction_method} for u in parsed["unparsed"]
        )
    return {"lines": lines, "unparsed": unparsed}


# ------------------------------------------------------------------ engine cross-check (per page)
# Thresholds: the share of the layout engine's words (and numbers) that the pdfplumber text also contains.
# Interleaved glyphs ("NFOoTErS") and reversed glyphs ("STNEMETATS", "5202") drop these shares sharply, so a
# page below either threshold is re-read with pdftotext -layout.
MIN_WORD_AGREEMENT = 0.92
MIN_NUMBER_AGREEMENT = 0.95
_WORD = re.compile(r"[A-Za-z]{3,}")
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")


def _tokens(lines: list[str]) -> tuple[list[str], list[str]]:
    text = " ".join(lines)
    words = [w.casefold() for w in _WORD.findall(text)]
    numbers = [n.replace(",", "") for n in _NUMBER.findall(text)]
    return words, numbers


def _share(reference: list[str], candidate: list[str]) -> float | None:
    """Share of reference tokens (as a multiset) that appear in the candidate. None when there are none."""
    if not reference:
        return None
    pool: dict[str, int] = {}
    for t in candidate:
        pool[t] = pool.get(t, 0) + 1
    hit = 0
    for t in reference:
        if pool.get(t, 0) > 0:
            pool[t] -= 1
            hit += 1
    return hit / len(reference)


def page_agreement(plumber_lines: list[str], layout_lines: list[str]) -> dict:
    """How far the pdfplumber text agrees with the pdftotext -layout text on the same page. The layout text is
    the reference: it is the engine that keeps glyph order on these reports."""
    lw, ln = _tokens(layout_lines)
    pw, pn = _tokens(plumber_lines)
    return {
        "word_agreement": _share(lw, pw),
        "number_agreement": _share(ln, pn),
        "layout_words": len(lw),
        "layout_numbers": len(ln),
    }


def choose_page_text(plumber_lines: list[str], layout_lines: list[str] | None) -> tuple[list[str], str, dict]:
    """Pick the text for one page. pdfplumber is kept when it agrees with the layout engine; otherwise the
    layout text is used. Returns (lines, extraction_method, metrics). Without a layout text the pdfplumber
    text is kept but marked unverified: it is never silently trusted."""
    if (
        not plumber_lines and not layout_lines
    ):  # no text layer on either engine: nothing to read, nothing invented
        return [], "no_text", {}
    if not layout_lines:  # no reference text (None, or an empty pdftotext page): nothing to verify against
        return plumber_lines, "pdfplumber_unverified", {}
    m = page_agreement(plumber_lines, layout_lines)
    word_ok = m["word_agreement"] is None or m["word_agreement"] >= MIN_WORD_AGREEMENT
    num_ok = m["number_agreement"] is None or m["number_agreement"] >= MIN_NUMBER_AGREEMENT
    if word_ok and num_ok:
        return plumber_lines, "pdfplumber", m
    return layout_lines, "pdftotext_layout", m


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
