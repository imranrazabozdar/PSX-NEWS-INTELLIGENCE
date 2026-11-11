"""Auditor's report extraction: opinion, emphasis of matter, going-concern uncertainty, and KAMs.

Deterministic. Every finding carries the page number and an exact excerpt copied from the text, so it can be
checked by a reader. Rules:
  * The opinion is classified only from explicit wording. If more than one class is supported, the result is
    'ambiguous' and every candidate with its excerpt is returned. No class is chosen.
  * 'present fairly' is not counted when preceded by 'do not', so an adverse opinion is not read as
    unqualified.
  * KAM headings are structural candidates (short, not a sentence, followed by a description). Confidence is
    recorded as 0.6 for structural KAM detection. Nothing is invented when no KAM section is found.
"""

from __future__ import annotations

import re
from collections import defaultdict

OPINION_PATTERNS = {
    "unqualified": [
        re.compile(r"(?<!not )present fairly,? in all material respects", re.I),
        re.compile(r"(?<!not )give a true and fair view", re.I),
        re.compile(r"unqualified opinion", re.I),
        re.compile(r"unmodified opinion", re.I),
    ],
    "qualified": [
        re.compile(r"qualified opinion", re.I),
        re.compile(r"except for the (?:effects? of the )?matter", re.I),
        re.compile(r"except for (?:the )?effects? of", re.I),
    ],
    "adverse": [
        re.compile(r"adverse opinion", re.I),
        re.compile(r"do not present fairly", re.I),
        re.compile(r"do not give a true and fair view", re.I),
    ],
    "disclaimer": [
        re.compile(r"we do not express an opinion", re.I),
        re.compile(r"disclaimer of opinion", re.I),
    ],
}
EMPHASIS = re.compile(r"emphasis of matter", re.I)
GOING_CONCERN = re.compile(
    r"material uncertainty (?:related to|that may cast significant doubt).{0,80}going concern|"
    r"going concern.{0,120}material uncertainty",
    re.I | re.S,
)
# Standard ISA wording says what the auditor WILL report if an uncertainty exists ("If we conclude that a
# material uncertainty exists..."). That conditional sentence is not a going-concern uncertainty.
# "whether a material uncertainty exists ..." is the same conditional wording, printed in a different order.
CONDITIONAL_UNCERTAINTY = re.compile(
    r"if (?:we|such)\b[^.]{0,120}material uncertainty|if we conclude|whether a material uncertainty exists",
    re.I,
)
KAM_SECTION = re.compile(r"key audit matters?", re.I)
KAM_END = re.compile(
    r"other information|responsibilities of management|other legal and regulatory|independent auditor|"
    r"statement of financial position|statement of profit or loss|statement of cash flows|"
    r"statement of changes in equity|balance sheet|income statement",
    re.IGNORECASE,
)
NOTE_LINE = re.compile(r"^\s*(?:note\s+\d{1,2}\b|\d{1,2}\s*[\.\)]\s+[A-Za-z])", re.IGNORECASE)


def _excerpt(text: str, match: re.Match, width: int = 160) -> str:
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + width)
    return text[start:end].strip()


def classify_opinion(doc) -> dict:
    hits: dict[str, list[dict]] = defaultdict(list)
    for pg in doc.pages:
        if not pg.has_text:
            continue
        text = " ".join(pg.lines)
        for cls, patterns in OPINION_PATTERNS.items():
            for pat in patterns:
                for m in pat.finditer(text):
                    hits[cls].append({"page": pg.number, "phrase": m.group(0), "excerpt": _excerpt(text, m)})
    if not hits:
        return {"opinion": "not_found", "candidates": {}}
    if len(hits) > 1:
        return {"opinion": "ambiguous", "candidates": dict(hits)}
    cls = next(iter(hits))
    return {"opinion": cls, "evidence": hits[cls]}


def emphasis_and_uncertainty(doc) -> dict:
    emphasis, uncertainty, boilerplate = [], [], 0
    for pg in doc.pages:
        if not pg.has_text:
            continue
        text = " ".join(pg.lines)
        for m in EMPHASIS.finditer(text):
            emphasis.append({"page": pg.number, "excerpt": _excerpt(text, m)})
        for m in GOING_CONCERN.finditer(text):
            window = text[max(0, m.start() - 40) : m.end() + 240]
            if CONDITIONAL_UNCERTAINTY.search(window):
                boilerplate += 1  # the conditional ISA sentence: counted, never reported as an uncertainty
                continue
            uncertainty.append({"page": pg.number, "excerpt": _excerpt(text, m, width=240)})
    return {
        "emphasis_of_matter": emphasis,
        "going_concern_material_uncertainty": uncertainty,
        "going_concern_conditional_boilerplate": boilerplate,
    }


def key_audit_matters(doc) -> list[dict]:
    """Structural KAM extraction. A heading is a short line that is not a sentence and is followed by a longer
    description line. Extraction stops at the next report section."""
    kams: list[dict] = []
    in_section = False
    current = None
    for pg in doc.pages:
        if not pg.has_text:
            continue
        for raw in pg.lines:
            line = raw.strip()
            if not line:
                continue
            if KAM_SECTION.search(line) and len(line.split()) <= 8:
                in_section = True
                current = None
                continue
            if not in_section:
                continue
            if KAM_END.search(line) or NOTE_LINE.match(line):
                in_section = False
                current = None
                continue
            is_heading = (
                len(line.split()) <= 12 and not line.endswith(".") and line[0].isupper() and len(line) < 120
            )
            if is_heading and (current is None or current["description"]):
                current = {"heading": line, "description": "", "page": pg.number, "confidence": 0.6}
                kams.append(current)
            elif current is not None:
                current["description"] = (current["description"] + " " + line).strip()
    for k in kams:
        k["excerpt"] = k["description"][:300]
    return [k for k in kams if k["description"]]


def audit_summary(doc) -> dict:
    return {"opinion": classify_opinion(doc), **emphasis_and_uncertainty(doc), "kams": key_audit_matters(doc)}
