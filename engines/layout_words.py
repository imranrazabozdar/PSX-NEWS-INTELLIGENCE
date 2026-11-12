"""Position-aware statement reading: de-overprint by coordinates, then assign figures to columns by
x-position.

Why: some statement PDFs draw each row twice (an overprinted text layer). String-level reading then sees
doubled
labels and repeated figures, and token order cannot tell a repeated figure from a real second column.

What this module does:
* De-overprint at the CHARACTER level. Two characters with the same glyph at the same (x0, top) within a
tolerance
  are one drawn glyph; the duplicate is dropped. A figure legitimately in two columns sits at two different
  x-bands
  and is kept.
* Rebuild words from the remaining characters (split on horizontal gaps), then group words into rows by top.
* Assign each figure to a value column by its right edge (x1). A note reference sits in a narrow band left
of the
  figures and is never a value.
* INTEGRITY GUARD: a row is accepted only when every figure sits in exactly one column and no column
receives two
  figures in that row. Anything else makes the row AMBIGUOUS, and the page is reported as requires_review. An
  ambiguous row is never turned into a value.

Pure functions over character records; reading the PDF is the caller's job (see page_chars in
engines/pdf_reader).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

DUP_TOL = 1.0  # points: same glyph within this distance is the same drawn glyph
ROW_TOL = 2.5  # points: words on the same baseline
WORD_GAP = 1.6  # points: a horizontal gap larger than this starts a new word
COLUMN_GAP = 18.0  # points: right edges further apart than this are different columns
COLUMN_TOL = 22.0  # points: a figure must sit within this distance of its column's right edge
MIN_COLUMN_FIGURES = 3  # figures a band needs before it counts as a value column

_FIGURE = re.compile(r"^\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?$|^\(?-?\d+\.\d+\)?$|^[-–—]$")
_NOTE = re.compile(r"^\d{1,2}(?:\.\d{1,2}){0,2}$")


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    chars: int = 1


@dataclass
class Row:
    top: float
    label: str
    cells: dict[int, tuple[str, float, float]] = field(
        default_factory=dict
    )  # column index -> (text, x1, top)
    ambiguous: list[str] = field(default_factory=list)


def dedupe_chars(chars: list[dict]) -> tuple[list[dict], int]:
    """Drop characters that are the same glyph at the same position (overprint). Returns (kept, dropped)."""
    kept: list[dict] = []
    dropped = 0
    buckets: dict[tuple[str, int], list[dict]] = {}
    for ch in sorted(chars, key=lambda c: (round(c["top"]), c["x0"])):
        key = (ch["text"], round(ch["top"] / DUP_TOL))
        same = buckets.setdefault(key, [])
        if any(abs(o["x0"] - ch["x0"]) <= DUP_TOL and abs(o["top"] - ch["top"]) <= DUP_TOL for o in same):
            dropped += 1
            continue
        same.append(ch)
        kept.append(ch)
    return kept, dropped


def words_from_chars(chars: list[dict]) -> list[Word]:
    """Words from characters: a new word starts on a line change or a horizontal gap above WORD_GAP."""
    lines: dict[int, list[dict]] = {}
    for ch in chars:
        if not ch["text"].strip():
            continue
        lines.setdefault(round(ch["top"] / ROW_TOL), []).append(ch)
    words: list[Word] = []
    for key in sorted(lines):
        line = sorted(lines[key], key=lambda c: c["x0"])
        cur: list[dict] = []
        for ch in line:
            if cur and ch["x0"] - cur[-1]["x1"] > WORD_GAP:
                words.append(_word(cur))
                cur = []
            cur.append(ch)
        if cur:
            words.append(_word(cur))
    return words


def _word(chars: list[dict]) -> Word:
    return Word(
        text="".join(c["text"] for c in chars).strip(),
        x0=min(c["x0"] for c in chars),
        x1=max(c["x1"] for c in chars),
        top=min(c["top"] for c in chars),
        chars=len(chars),
    )


def is_figure(text: str) -> bool:
    return bool(_FIGURE.match(text))


def value_columns(words: list[Word]) -> list[tuple[float, int]]:
    """Right-edge clusters of figures on the page: (centre x1, figure count), sorted left to right."""
    edges = sorted(w.x1 for w in words if is_figure(w.text))
    clusters: list[list[float]] = []
    for x in edges:
        if clusters and x - clusters[-1][-1] <= COLUMN_GAP:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    out = [(sum(c) / len(c), len(c)) for c in clusters if len(c) >= MIN_COLUMN_FIGURES]
    return out


def positional_rows(words: list[Word], columns: list[tuple[float, int]]) -> list[Row]:
    """Group words into rows and assign each figure to a column. Ambiguity is recorded, never resolved."""
    if not columns:
        return []
    rows: dict[int, Row] = {}
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        key = round(w.top / ROW_TOL)
        row = rows.setdefault(key, Row(top=w.top, label=""))
        if is_figure(w.text):
            col = _nearest_column(w.x1, columns)
            if col is None:
                row.ambiguous.append(f"figure {w.text!r} outside every column at x1={w.x1:.1f}")
            elif col in row.cells:
                row.ambiguous.append(f"two figures in one column {col}: {row.cells[col][0]!r} and {w.text!r}")
            else:
                row.cells[col] = (w.text, w.x1, w.top)
        elif _NOTE.match(w.text) and w.x1 < min(c for c, _ in columns) - COLUMN_TOL:
            continue  # the note-reference band: never a value
        else:
            row.label = (row.label + " " + w.text).strip()
    return [r for r in rows.values() if r.cells or r.label]


def _nearest_column(x1: float, columns: list[tuple[float, int]]) -> int | None:
    best = min(range(len(columns)), key=lambda i: abs(columns[i][0] - x1))
    return best if abs(columns[best][0] - x1) <= COLUMN_TOL else None


def assert_single_source_cells(rows: list[Row]) -> list[str]:
    """The integrity rule: every value comes from one source cell at one position, and no two values in a
    row share
    a cell. Returns the violations (an empty list means the rule holds)."""
    violations: list[str] = []
    for r in rows:
        seen: set[tuple[float, float]] = set()
        for _col, (_text, x1, top) in r.cells.items():
            key = (round(x1, 1), round(top, 1))
            if key in seen:
                violations.append(f"row '{r.label[:40]}': two values share the source cell {key}")
            seen.add(key)
    return violations


def read_page(chars: list[dict]) -> dict:
    """De-overprint, rebuild words, find value columns and assign rows. Returns rows, columns and a
    verdict."""
    kept, dropped = dedupe_chars(chars)
    words = words_from_chars(kept)
    columns = value_columns(words)
    rows = positional_rows(words, columns)
    ambiguous = [a for r in rows for a in r.ambiguous]
    ambiguous += assert_single_source_cells(rows)
    return {
        "rows": rows,
        "columns": columns,
        "dropped_overprint_chars": dropped,
        "ambiguous": ambiguous,
        "verdict": "requires_review" if ambiguous or not columns else "ok",
    }


_YEAR = re.compile(r"^20\d{2}$")
SHADOW_SHARE = 0.8  # two columns equal in this share of their common rows are a copy, not two periods


def header_year_columns(words: list[Word], above_top: float) -> list[float]:
    """Centres of the year columns printed above the first figure row (a repeated year counts as its own
    column)."""
    edges = sorted(w.x1 for w in words if _YEAR.match(w.text) and w.top < above_top)
    clusters: list[list[float]] = []
    for x in edges:
        if clusters and x - clusters[-1][-1] <= COLUMN_GAP:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    return [sum(c) / len(c) for c in clusters]


def shadow_pairs(rows: list[Row], columns: list[tuple[float, int]]) -> list[tuple[int, int, float]]:
    """Pairs of value columns that carry the same figure in most of their common rows: one column is a
    copy."""
    found = []
    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            common = [r for r in rows if i in r.cells and j in r.cells]
            if len(common) < 3:
                continue
            same = sum(1 for r in common if r.cells[i][0] == r.cells[j][0])
            if same / len(common) >= SHADOW_SHARE:
                found.append((i, j, same / len(common)))
    return found


def integrity_verdict(page: dict, *, expected_columns: int, header_columns: list[float]) -> dict:
    """The gate. 'ok' only when the header shows the expected number of period columns, the figure columns
    match it,
    no row is ambiguous, and no two columns are copies. Anything else is requires_review with the reasons."""
    reasons: list[str] = []
    if len(header_columns) != expected_columns:
        reasons.append(f"header shows {len(header_columns)} year columns, expected {expected_columns}")
    if len(page["columns"]) != expected_columns:
        reasons.append(f"figures fall into {len(page['columns'])} columns, expected {expected_columns}")
    shadows = shadow_pairs(page["rows"], page["columns"])
    if shadows:
        reasons.append(
            "columns are copies of each other: " + ", ".join(f"{i}~{j} ({s:.0%})" for i, j, s in shadows)
        )
    if page["ambiguous"]:
        reasons.append(f"{len(page['ambiguous'])} ambiguous figure(s) or row(s)")
    return {"verdict": "requires_review" if reasons else "ok", "reasons": reasons}
