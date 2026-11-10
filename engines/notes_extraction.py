"""Labelled values from report notes, with page-level evidence.

Input: a list of (page_number, page_text) from a report's text layer. A row counts only when its label matches
at the start of a line and its tokens after the label are numbers. The value is parsed with the strict
financial parser (brackets read as negative, dashes are not reported, never zero). Each value keeps its page
and the verbatim line.

Several matches for one label are AMBIGUOUS: none is chosen. No match is NOT_REPORTED, never zero.
"""

from __future__ import annotations

import re
from typing import Any

from engines.financials import parse_number

ENGINE_VERSION = "notes-extraction/1"
_NUMERIC = re.compile(r"^\(?-?[\d]{1,3}(?:,\d{3})*(?:\.\d+)?\)?$|^\(?-?\d+(?:\.\d+)?\)?$")
_BLANK_TOKENS = {"-", "—", "–"}


def _numbers_after(line: str, label_end: int) -> list[float | None] | None:
    tokens = line[label_end:].split()
    if not tokens:
        return None
    values: list[float | None] = []
    for tok in tokens:
        if tok in _BLANK_TOKENS:
            values.append(None)
        elif _NUMERIC.match(tok):
            values.append(parse_number(tok))
        else:
            return None
    return values


def find(pages: list[tuple[int, str]], labels: dict[str, str]) -> dict[str, dict[str, Any]]:
    """labels: name -> regex for the start of the row label (case-insensitive)."""
    out: dict[str, dict[str, Any]] = {}
    for name, pattern in labels.items():
        rx = re.compile(r"^\s*(" + pattern + r")\b", re.IGNORECASE)
        hits = []
        for page, text in pages:
            for line in text.splitlines():
                m = rx.match(line)
                if not m:
                    continue
                values = _numbers_after(line, m.end())
                if values is None or not values:
                    continue
                hits.append({"page": page, "excerpt": line.strip(), "values": values})
        if not hits:
            out[name] = {"state": "not_reported"}
        elif len(hits) > 1:
            out[name] = {"state": "ambiguous", "candidates": hits}
        else:
            out[name] = {"state": "reported", **hits[0]}
    return out
