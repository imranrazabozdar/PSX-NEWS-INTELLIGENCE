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

import re
import statistics
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


# ---------------------------------------------------------------- side-by-side statements (layout-aware)
# A figure is a number of three or more digits (comma-grouped or plain), optionally bracketed. Note references
# (1-2 digit integers) and dashes are never used to find a column boundary: they occur in single tables too.
_VALUE = re.compile(r"^\(?-?(\d{1,3}(,\d{3})+|\d{3,})(\.\d+)?\)?$")  # 3+ digits, not note refs
MIN_BOUNDARY_ROWS = 3  # rows that must show the same boundary before a split is trusted
BOUNDARY_TOLERANCE = 0.02  # fraction of page width that the boundary may vary between rows


def _rows(words: list[dict]) -> list[list[dict]]:
    grouped: dict[int, list[dict]] = {}
    for w in words:
        grouped.setdefault(round(w["top"] / 3), []).append(w)
    return [sorted(r, key=lambda w: w["x0"]) for _, r in sorted(grouped.items())]


def detect_columns(page_words: list[dict], page_width: float) -> dict:
    """Find a side-by-side boundary from rows of the form  label  figure  label  figure.

    Returns {"layout": "single" | "two_column" | "uncertain", "gutter_x": float | None, "rows": int}.
    A row that matches the pattern proves that two statement blocks share the line. The gutter is the
    midpoint between the right edge of the first figure and the start of the second label. Splitting is
    trusted only when enough rows agree on the same gutter; otherwise the page is flagged, never guessed.
    """
    gutters: list[float] = []
    for row in _rows(page_words):
        tok = ["V" if _VALUE.match(w["text"]) else "T" for w in row]
        for i in range(1, len(tok)):
            if tok[i] == "T" and tok[i - 1] == "V":
                j = i
                while j < len(tok) and tok[j] == "T":
                    j += 1
                label = row[i:j]
                if j < len(tok) and tok[j] == "V" and any(
                        len(w["text"]) >= 3 and w["text"].isalpha() for w in label):
                    gutters.append((row[i - 1]["x1"] + row[i]["x0"]) / 2)
                break
    if not gutters:
        return {"layout": "single", "gutter_x": None, "rows": 0}
    if len(gutters) < MIN_BOUNDARY_ROWS:
        return {"layout": "uncertain", "gutter_x": None, "rows": len(gutters)}
    spread = max(gutters) - min(gutters)
    if spread > BOUNDARY_TOLERANCE * page_width:
        return {"layout": "uncertain", "gutter_x": None, "rows": len(gutters)}
    return {"layout": "two_column", "gutter_x": round(statistics.median(gutters), 1), "rows": len(gutters)}


_FRAGMENT = re.compile(r"^\d{1,3}$")
_GROUPED = re.compile(r"^\d{1,3},\d{3}")
TOUCH_GAP = 0.2  # points: glyphs closer than this are one run; a genuine column gap is about 20 points


def join_touching_figures(words: list[dict], page: int) -> tuple[list[dict], list[dict]]:
    """Join a 1-3 digit fragment to a comma-grouped figure when the two glyph boxes touch (gap <= 0.2 pt).

    The text layer of one document split single digits from their figures ("6 0,720,610" for 60,720,610).
    The touching boxes show that the digits belong to one number; the join is recorded with the original
    text, so it can be reviewed. A genuine separator (about 20 points) is never joined."""
    ws = sorted((dict(w) for w in words), key=lambda w: (round(w["top"]), w["x0"]))
    out: list[dict] = []
    repairs: list[dict] = []
    for w in ws:
        if out:
            prev = out[-1]
            same_row = abs(prev["top"] - w["top"]) < 1.0
            gap = w["x0"] - prev["x1"]
            touching = 0 <= gap <= TOUCH_GAP
            if same_row and touching and _FRAGMENT.match(prev["text"]) and _GROUPED.match(w["text"]):
                joined = prev["text"] + w["text"]
                repairs.append({"page": page, "original": f"{prev['text']} {w['text']}", "joined": joined,
                                "gap_pt": round(gap, 2)})
                prev["text"] = joined
                prev["x1"] = w["x1"]
                continue
        out.append(w)
    return out, repairs


def _lines_of(words: list[dict]) -> list[str]:
    return [" ".join(w["text"] for w in row) for row in _rows(words) if row]


def split_page(path: Path | str, number: int) -> tuple[dict, list[Page]]:
    """Layout-aware read of one page. Returns the detection result and the page parts: one part per
    statement column for a clear side-by-side layout, or the whole page when it is single or uncertain."""
    import pdfplumber

    with pdfplumber.open(Path(path)) as pdf:
        pg = pdf.pages[number - 1]
        words = pg.extract_words()
        width = float(pg.width)
    words, repairs = join_touching_figures(words, number)
    info = detect_columns(words, width)
    info["repairs"] = len(repairs)
    if info["layout"] == "two_column" and any(w["x0"] < info["gutter_x"] - 0.5 < w["x1"] for w in words):
        info = {**info, "layout": "uncertain", "reason": "a label or figure crosses the gutter"}
    if info["layout"] == "two_column":
        g = info["gutter_x"]
        left = [w for w in words if w["x0"] < g]
        right = [w for w in words if w["x0"] >= g]
        parts = [Page(number, _lines_of(left), True, [], column="L", repairs=repairs),
                 Page(number, _lines_of(right), True, [], column="R", repairs=[])]
        return info, parts
    layout_flag = "uncertain" if info["layout"] == "uncertain" else None
    lines = _lines_of(words)
    return info, [Page(number, lines, bool(lines), [], layout_flag=layout_flag, repairs=repairs)]


def read_with_layout(path: Path | str, split_pages: list[int]) -> DocumentText:
    """The approved read, with side-by-side detection applied to the listed pages only."""
    base = read(path)
    if not split_pages:
        return base
    out: list[Page] = []
    for pg in base.pages:
        if pg.number in split_pages and pg.has_text:
            _, parts = split_page(path, pg.number)
            out.extend(parts)
        else:
            out.append(pg)
    return DocumentText(out)
