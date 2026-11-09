"""pdfplumber reader for the M2 extraction contract (owner-approved, U3).

See engines/pdf_extraction.py for the contract.

Adapter only: it turns a PDF into `DocumentText` (per-page lines, a has_text flag and optional tables).
It never interprets figures. Parsing, mapping and reconciliation stay in engines/financials.py.

Honesty rules
* A page with no text layer is returned with has_text=False and NO text. It is never OCR'd and never invented.
* Page numbers are the PDF's own 1-based order. Every line keeps the page it came from.
* Tables are returned as the library reads them, unmodified. Nothing is merged or repaired here.
* A file that is not a readable PDF raises ValueError; it is never treated as an empty document.
"""

from __future__ import annotations

from pathlib import Path

from engines.pdf_extraction import DocumentText, Page

try:  # the reader is available only when the approved dependency is installed
    import pdfplumber
except ImportError:  # pragma: no cover - exercised only when the dependency is absent
    pdfplumber = None

MIN_TEXT_CHARS = 20  # fewer characters than this on a page is treated as "no text layer" (scanned or image)


def available() -> bool:
    return pdfplumber is not None


def read(path: Path | str) -> DocumentText:
    """Read every page of a PDF. Raises RuntimeError if the approved reader is not installed, and ValueError
    if the file is not a readable PDF (never an empty result)."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is not installed (approved dependency, requirements.txt)")
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"not a file: {p.name}")
    try:
        pdf = pdfplumber.open(p)
    except Exception as exc:  # corrupt, encrypted or non-PDF input
        raise ValueError(f"not a readable PDF: {p.name} ({type(exc).__name__})") from exc
    pages: list[Page] = []
    with pdf:
        if not pdf.pages:
            raise ValueError(f"PDF has no pages: {p.name}")
        for i, pg in enumerate(pdf.pages, start=1):
            text = pg.extract_text() or ""
            lines = [ln for ln in text.split("\n") if ln.strip()]
            has_text = len(text.strip()) >= MIN_TEXT_CHARS
            tables = []
            if has_text:
                try:
                    raw = pg.extract_tables() or []
                    tables = [[[cell or "" for cell in row] for row in t] for t in raw]
                except Exception:  # a table-detection failure must not hide the page's text
                    tables = []
            pages.append(Page(number=i, lines=lines if has_text else [], has_text=has_text, tables=tables))
    return DocumentText(pages)
