"""Spatial (word-coordinate) layout reading for pages with side-by-side columns.

Why: on spread pages and on the auditor's KAM table, the text layer of a page interleaves the columns when
read
as one stream. Each word carries its own coordinates, so columns are assigned by word position (x0), not by
reading order. Nothing here invents text: every line is assembled from words the PDF actually contains.

Public functions take `words` (dicts with text, x0, x1, top, bottom, as pdfplumber's extract_words returns).
Reading the words from a PDF is done by engines/pdf_reader.py (`page_words`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LINE_TOLERANCE = 3.0  # points: words whose tops differ by less are on the same printed line
SPACE_GAP = 12.0  # points: a horizontal gap wider than this is printed as two spaces
# KAM headings are numbered "1." or, in some reports, "(i)" / "(ii)". The number is returned as an integer.
KAM_NUMBERED = re.compile(r"^\s*(?:(\d{1,2})\s*[\.\)]|\(([ivx]{1,4})\))\s+(.+?)\s*$", re.IGNORECASE)
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}


def _kam_number(m: re.Match) -> int:
    return int(m.group(1)) if m.group(1) else _ROMAN[m.group(2).lower()]


@dataclass
class Column:
    name: str
    x_from: float
    x_to: float  # exclusive


def _lines(words: list[dict]) -> list[dict]:
    """Group words into printed lines by vertical position. Returns [{top, text, x0}] in reading order."""
    out: list[dict] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if out and abs(out[-1]["top"] - w["top"]) <= LINE_TOLERANCE:
            cur = out[-1]
            gap = w["x0"] - cur["_x1"]
            cur["parts"].append(("  " if gap > SPACE_GAP else " ") + w["text"])
            cur["_x1"] = w["x1"]
        else:
            out.append({"top": w["top"], "x0": w["x0"], "_x1": w["x1"], "parts": [w["text"]]})
    for o in out:
        o["text"] = "".join(o["parts"]).strip()
        del o["parts"], o["_x1"]
    return out


def split_columns(words: list[dict], columns: list[Column]) -> dict[str, list[dict]]:
    """Assign each word to the column that contains its left edge. Words are never split across columns."""
    buckets: dict[str, list[dict]] = {c.name: [] for c in columns}
    for w in words:
        for c in columns:
            if c.x_from <= w["x0"] < c.x_to:
                buckets[c.name].append(w)
                break
    return buckets


def column_lines(words: list[dict], columns: list[Column]) -> dict[str, list[dict]]:
    """Printed lines per column, each with its top position (for matching rows across columns)."""
    return {name: _lines(ws) for name, ws in split_columns(words, columns).items()}


def find_phrase(words: list[dict], phrase: list[str]) -> list[dict]:
    """Occurrences of a word sequence (case-insensitive, same printed line). Returns the first word of
    each."""
    want = [p.lower() for p in phrase]
    hits = []
    ws = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    for i, w in enumerate(ws):
        if w["text"].lower() != want[0]:
            continue
        seq = [w]
        j = i + 1
        for token in want[1:]:
            while (
                j < len(ws) and abs(ws[j]["top"] - w["top"]) > LINE_TOLERANCE and ws[j]["top"] < w["top"] + 40
            ):
                j += 1
            if j < len(ws) and ws[j]["text"].lower() == token and abs(ws[j]["top"] - w["top"]) <= 40:
                seq.append(ws[j])
                j += 1
            else:
                seq = []
                break
        if seq:
            hits.append(seq[0])
    return hits


def kam_table_layout(words: list[dict]) -> dict | None:
    """Locate the KAM table on a page: its header row ("Key audit matters" | "How the matter was
    addressed"), its
    column boundaries, and its bottom edge. Returns None when the page has no KAM table header. Column
    boundaries
    come from the header words; the right-hand column (the auditor's other text) starts at the first word of
    the page's column heading that sits to the right of the response column."""
    how = find_phrase(words, ["How", "the", "matter", "was", "addressed"])
    key = find_phrase(words, ["Key", "audit", "matters"])
    if not how or not key:
        return None
    header = min(how, key=lambda w: w["top"])
    header_top = header["top"]
    key_hdr = min((k for k in key if abs(k["top"] - header_top) <= 12), key=lambda k: k["x0"], default=None)
    if key_hdr is None:
        return None
    col_how = header["x0"] - 4.0
    # the KAM column starts at the leftmost word of the header row ("S. No." sits left of "Key audit matters")
    header_row = [w for w in words if abs(w["top"] - header_top) <= 12 and w["x0"] <= key_hdr["x0"] + 1]
    kam_left = min([w["x0"] for w in header_row] + [key_hdr["x0"]]) - 4.0
    # right edge of the KAM table: the first word of any text that starts to the right of the response
    # column at
    # or below the header; the auditor's text is in that column. Use the leftmost such word.
    right_candidates = [
        w
        for w in words
        if w["x0"] > col_how + 60
        and w["top"] >= header_top + 5
        and w["text"] in ("Auditor’s", "Auditors’", "Auditor's", "Auditors'")
    ]
    col_right = min((w["x0"] for w in right_candidates), default=None)
    if col_right is None:
        # no auditor text to the right (e.g. a spread half that holds only the KAM table): the table
        # runs to the
        # furthest word printed under its header
        col_right = max(w["x1"] for w in words if w["top"] >= header_top - 2) + 4.0
    else:
        col_right -= 4.0  # the auditor's text starts here; stop just before it

    # bottom: the first full-width line below the header whose left edge is at the table's left margin and
    # that
    # starts a new report section ("Information Other than...", "Responsibilities of Management ...").
    bottom_words = [
        w
        for w in words
        if w["top"] > header_top + 30
        and w["x0"] < key_hdr["x0"] + 6
        and w["text"] in ("Information", "Responsibilities", "Other")
    ]
    bottom = min((w["top"] for w in bottom_words), default=max(w["bottom"] for w in words))
    return {
        "header_top": header_top,
        "bottom": bottom,
        "columns": [
            Column("kam", kam_left, col_how),
            Column("response", col_how, col_right),
        ],
        "left_margin": key_hdr["x0"],
    }


def parse_kam_table(words: list[dict], page: int) -> dict | None:
    """KAMs from the KAM table of one page, by column. KAM headings are the numbered lines in the KAM column
    inside the table; note references are read from that KAM's disclosure text and response text. Each KAM
    keeps
    the page number it was printed on. Returns None when there is no KAM table on the page."""
    layout = kam_table_layout(words)
    if layout is None:
        return None
    inside = [w for w in words if layout["header_top"] - 2 <= w["top"] < layout["bottom"] - 1]
    cols = column_lines(inside, layout["columns"])
    left, right = cols["kam"], cols["response"]
    headers = [ln for ln in left if KAM_NUMBERED.match(ln["text"]) and ln["top"] > layout["header_top"]]
    kams = []
    for idx, h in enumerate(headers):
        m = KAM_NUMBERED.match(h["text"])
        top_end = headers[idx + 1]["top"] if idx + 1 < len(headers) else layout["bottom"] + 1
        body = [ln for ln in left if h["top"] <= ln["top"] < top_end and ln is not h]
        # a heading printed over two lines: the continuation lines come before the "(Refer notes ...)" line
        heading_parts = [m.group(3).strip()]
        for ln in body[:2]:
            t = ln["text"].strip()
            # a wrapped heading continues in lowercase ("...development and" / "production assets ..."); a
            # sentence starts with a capital and is the disclosure text
            if not t or not t[0].islower() or t.startswith("(") or len(t) > 90:
                break
            heading_parts.append(t)
            body.remove(ln)
            if len(heading_parts) >= 3:
                break
        disclosure = [ln["text"] for ln in body]
        response = [ln["text"] for ln in right if h["top"] - 2 <= ln["top"] < top_end]
        text_all = " ".join([h["text"], *disclosure, *response])
        refs = sorted(_note_refs(text_all))
        kams.append(
            {
                "number": _kam_number(m),
                "heading": " ".join(heading_parts).strip(),
                "page": page,
                "disclosure": " ".join(disclosure),
                "audit_response": " ".join(response),
                "note_references": refs,
                "text_quality": _text_quality(text_all),
                "source": "word_coordinates",
                "confidence": 0.9,  # column-bounded from word positions; the text itself may be letter-spaced
                "columns": {
                    "kam": [layout["columns"][0].x_from, layout["columns"][0].x_to],
                    "response": [layout["columns"][1].x_from, layout["columns"][1].x_to],
                },
            }
        )
    for k in kams:
        k["excerpt"] = k["disclosure"][:300]
    return {"page": page, "kams": kams, "table_top": layout["header_top"], "table_bottom": layout["bottom"]}


def _text_quality(text: str) -> str:
    """'clean', or 'letter_spaced_or_overlapped' when many words are single letters (the PDF's own text
    layer is
    split or overlapped there, so the wording of that passage must not be quoted as exact)."""
    words = [w for w in re.findall(r"[A-Za-z]+", text) if len(w) > 0]
    if not words:
        return "clean"
    singles = sum(1 for w in words if len(w) == 1)
    return "letter_spaced_or_overlapped" if singles / len(words) > 0.12 else "clean"


_NOTE_WORD = r"N\s?o\s?t\s?e\s?s?"  # tolerant of letter-spaced text in the PDF's own text layer
_NOTE_NUMBER = r"\d{1,2}(?:\s?\.\s?\d{1,3})*"  # 9, 9.4, 2.4.10 (dotted note paragraphs)
_NOTE_NUMBERS = re.compile(
    _NOTE_WORD + r"\s+(" + _NOTE_NUMBER + r"(?:\s*(?:,|and|&)\s*" + _NOTE_NUMBER + r")*)",
    re.IGNORECASE,
)


def _note_refs(text: str) -> set[str]:
    """Note numbers cited in the text ("Note 9", "Notes 9.4", "Note 9 and 9.4"), with spaces removed from the
    numbers. Only numbers introduced by the word "Note(s)" are returned."""
    refs: set[str] = set()
    # letter-spaced passages print dotted numbers with spaces ("3 . 1 1"): close the gaps inside a
    # number first
    text = re.sub(r"(?<=\d)\s?\.\s?(?=\d)", ".", text)
    text = re.sub(r"(?<=\.\d) (?=\d)", "", text)
    text = re.sub(r"(?<=\d) (?=\d)", "", text)
    for m in _NOTE_NUMBERS.finditer(text):
        for num in re.findall(_NOTE_NUMBER, m.group(1)):
            refs.add(re.sub(r"\s", "", num))
    return refs
