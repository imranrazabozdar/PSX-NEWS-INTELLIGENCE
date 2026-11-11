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
import shutil
import subprocess
from pathlib import Path

from engines.pdf_extraction import DocumentText, Page, choose_page_text

try:  # the reader is available only when the approved dependency is installed
    import pdfplumber
except ImportError:  # pragma: no cover - exercised only when the dependency is absent
    pdfplumber = None

MIN_TEXT_CHARS = 20  # fewer characters than this on a page is treated as "no text layer" (scanned or image)
MODES = ("auto", "pdfplumber", "layout")
PDFTOTEXT_TIMEOUT_S = 120


def available() -> bool:
    return pdfplumber is not None


def _pdftotext() -> str | None:
    """Absolute path of Poppler's pdftotext, resolved once from PATH. The program is run with a fixed argument
    list and never through a shell; the input path is the owner's document and is passed as one argument."""
    return shutil.which("pdftotext")


def layout_available() -> bool:
    """True when Poppler's pdftotext is on PATH (the layout-preserving second engine)."""
    return _pdftotext() is not None


def read_layout_pages(path: Path | str) -> list[list[str]]:
    """Per-page text from `pdftotext -layout`, one list of lines per page. Arguments are passed as a list (no
    shell). Raises RuntimeError if pdftotext is missing or fails; never returns partial output silently."""
    if not layout_available():
        raise RuntimeError("pdftotext is not installed (Poppler); layout extraction unavailable")
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, absolute pdftotext path
            [_pdftotext(), "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            timeout=PDFTOTEXT_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("pdftotext timed out") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"pdftotext failed (exit {proc.returncode})")
    chunks = proc.stdout.decode("utf-8", errors="replace").split("\f")
    if chunks and not chunks[-1].strip():
        chunks = chunks[:-1]  # the trailing form feed produces an empty final chunk
    return [[ln.rstrip() for ln in c.split("\n") if ln.strip()] for c in chunks]


def region_lines(path: Path | str, page: int, side: str) -> list[str]:
    """Text of one half of a PDF page (side "L" or "R"), from pdftotext -layout with a crop. Two-page spreads
    print two statements side by side (e.g. the balance sheet beside the auditor's text, or the P&L beside the
    other comprehensive income); reading the full width would mix them. The page size comes from
    pdfplumber."""
    if side not in ("L", "R"):
        raise ValueError(f"side must be L or R, got {side!r}")
    if not layout_available():
        raise RuntimeError("pdftotext is not installed (Poppler); region extraction unavailable")
    try:
        with pdfplumber.open(Path(path)) as pdf:
            if not 1 <= page <= len(pdf.pages):
                raise ValueError(f"page {page} is outside the document (1-{len(pdf.pages)})")
            w, h = float(pdf.pages[page - 1].width), float(pdf.pages[page - 1].height)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"not a readable PDF: {Path(path).name} ({type(exc).__name__})") from exc
    half = w / 2.0
    x0, width = (0.0, half) if side == "L" else (half, w - half)
    cmd = [
        _pdftotext(),
        "-layout",
        "-enc",
        "UTF-8",
        "-f",
        str(page),
        "-l",
        str(page),
        "-x",
        str(int(x0)),
        "-y",
        "0",
        "-W",
        str(int(width)),
        "-H",
        str(int(h)),
        str(path),
        "-",
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv built above, no shell
            cmd, capture_output=True, timeout=PDFTOTEXT_TIMEOUT_S, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("pdftotext timed out") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"pdftotext failed (exit {proc.returncode})")
    text = proc.stdout.decode("utf-8", errors="replace").split("\f")[0]
    return [ln.rstrip() for ln in text.split("\n") if ln.strip()]


def _read_plumber(p: Path) -> list[Page]:
    """The pdfplumber pass. Raises ValueError for input it cannot open (never an empty document)."""
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
            pages.append(
                Page(
                    number=i,
                    lines=lines if has_text else [],
                    has_text=has_text,
                    tables=tables,
                    extraction_method="pdfplumber",
                )
            )
    return pages


def read(path: Path | str, mode: str = "auto") -> DocumentText:
    """Read every page of a PDF.

    mode="pdfplumber": pdfplumber text only.
    mode="layout":     pdftotext -layout text only (raises if pdftotext is missing).
    mode="auto":       pdfplumber for every page, cross-checked page by page against pdftotext -layout; a page
                       whose pdfplumber text disagrees with the layout text is replaced by the layout text.
                       If pdftotext is missing, pdfplumber text is kept and marked "pdfplumber_unverified"
                       with
                       a warning. Each page records its extraction_method.

    Raises RuntimeError if the approved reader is not installed, and ValueError if the file is not a readable
    PDF (never an empty result)."""
    if mode not in MODES:
        raise ValueError(f"unknown extraction mode: {mode}")
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is not installed (approved dependency, requirements.txt)")
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"not a file: {p.name}")

    if mode == "layout":
        layout = read_layout_pages(p)
        plumber_count = len(_read_plumber(p))  # the page count authority, and the readability check
        if len(layout) != plumber_count:
            raise ValueError(
                f"page count mismatch for {p.name}: pdftotext {len(layout)}, pdfplumber {plumber_count}"
            )
        pages = []
        for i, lines in enumerate(layout, start=1):
            has_text = sum(len(ln) for ln in lines) >= MIN_TEXT_CHARS
            pages.append(
                Page(
                    number=i,
                    lines=lines if has_text else [],
                    has_text=has_text,
                    extraction_method="pdftotext_layout",
                )
            )
        return DocumentText(pages)

    pages = _read_plumber(p)
    if mode == "pdfplumber":
        return DocumentText(pages)

    warnings: list[str] = []
    layout: list[list[str]] | None
    try:
        layout = read_layout_pages(p)
    except RuntimeError as exc:
        layout = None
        warnings.append(f"layout cross-check unavailable ({exc}); pdfplumber text kept unverified")
    if layout is not None and len(layout) != len(pages):
        warnings.append(
            f"layout page count {len(layout)} differs from pdfplumber {len(pages)}; cross-check skipped"
        )
        layout = None

    out: list[Page] = []
    for i, pg in enumerate(pages):
        ref = layout[i] if layout is not None else None
        if ref is None:  # not cross-checked: kept, but marked as unverified
            out.append(
                Page(
                    number=pg.number,
                    lines=pg.lines,
                    has_text=pg.has_text,
                    tables=pg.tables,
                    extraction_method="pdfplumber_unverified",
                )
            )
            continue
        lines, method, metrics = choose_page_text(pg.lines, ref)
        has_text = pg.has_text if method == "pdfplumber" else sum(len(ln) for ln in lines) >= MIN_TEXT_CHARS
        out.append(
            Page(
                number=pg.number,
                lines=lines if has_text else [],
                has_text=has_text,
                tables=pg.tables,
                extraction_method=method,
                agreement=metrics,
            )
        )
    return DocumentText(out, warnings=warnings)


def page_size(path: Path | str, page: int) -> tuple[float, float]:
    """Width and height of one page, in points."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is not installed (approved dependency, requirements.txt)")
    with pdfplumber.open(Path(path)) as pdf:
        if not 1 <= page <= len(pdf.pages):
            raise ValueError(f"page {page} is outside the document (1-{len(pdf.pages)})")
        pg = pdf.pages[page - 1]
        return float(pg.width), float(pg.height)


def page_words(path: Path | str, page: int) -> list[dict]:
    """Words of one page with their coordinates (pdfplumber). Raises ValueError for a page outside the
    document."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is not installed (approved dependency, requirements.txt)")
    with pdfplumber.open(Path(path)) as pdf:
        if not 1 <= page <= len(pdf.pages):
            raise ValueError(f"page {page} is outside the document (1-{len(pdf.pages)})")
        return [
            {
                "text": w["text"],
                "x0": float(w["x0"]),
                "x1": float(w["x1"]),
                "top": float(w["top"]),
                "bottom": float(w["bottom"]),
            }
            for w in pdf.pages[page - 1].extract_words(
                x_tolerance=1.2, use_text_flow=False, keep_blank_chars=False
            )
            if re.sub(r"\(cid:\d+\)", "", w["text"]).strip()  # unmapped glyph codes carry no text
        ]
