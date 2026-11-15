"""Quality gate for model-extracted rows: decide which outputs to trust and which to escalate.

The routing rule is "cheapest model that passes a measured check". This is the check. For every
per-video output file it measures, against that video's OWN source text:

* schema   : exact keys, fact_text <= 300 chars, confidence in {fact, analyst_view}, source says undated
* grounding: the share of numbers in fact_text that actually appear in the source transcript. A number
             the speaker never said is the clearest sign a model invented a figure
* dating   : a relative period ("last year", "currently") is a defect: it mixes eras
* advice   : buy/sell/target-price wording, which this system never emits
* density  : rows per 1,000 source characters. Too sparse means the model skimmed

* bleed    : a model reading several videos in one chunk can file a fact under the wrong video. A row whose
             numbers are missing from its own video but present in a SIBLING video of the same chunk is
             flagged. That fact has the wrong source, the wrong recency rank and the wrong speaker note.

A file that fails is not deleted: it is reported with the reason, so the caller can send that one video to
a stronger model instead of repeating the whole batch.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KEYS = {"company", "topic", "fact_text", "value", "unit", "period", "source_name", "source_url",
        "video_id", "confidence"}
_NUM = re.compile(r"\d[\d,]*\.?\d*")
_RELATIVE = re.compile(r"\b(last year|recently|currently|these days|nowadays|this year|next year|today|"
                       r"at the moment|before the video)\b", re.I)
# A DATED channel (verified upload dates) may state time-bound facts, but only with absolute dates: a relative
# word inside the sentence ("today", "last week") is a defect because the sentence outlives the video.
_RELATIVE_TEXT = re.compile(
    r"\b(today|yesterday|tomorrow|tonight|this (?:week|month|year|session|quarter)|last (?:week|month|year|"
    r"session|quarter)|next (?:week|month|year|session|quarter)|recently|currently|right now|these days|"
    r"nowadays|so far|the other day|at the moment|at present)\b|\blast (?:two|three|four|few|several|\d+) ",
    re.I)
# Advice is a recommendation addressed to a reader, not the word "sell": a power plant may "sell" electricity
# and a company may "buy back" shares. Only directive wording and price targets count.
_ADVICE = re.compile(
    r"\b(you should|should you|i would|i recommend|we recommend|must)\s+(buy|sell|hold|accumulate|avoid)\b"
    r"|\b(target price|price target)\b|\b(buy|sell) (this|the|these) (stock|share|scrip)s?\b", re.I)

MIN_GROUNDING = 0.70      # of numbers present in a row, at least this share must be in the source
MIN_DENSITY = 0.12        # rows per 1,000 source chars; the benchmark ran 1.0-1.5
MAX_ADVICE_SHARE = 0.10


@dataclass
class FileVerdict:
    unit: str
    rows: int
    ok: bool
    reasons: list[str] = field(default_factory=list)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in _NUM.findall(text)}


def _distinctive(text: str) -> set[str]:
    """Numbers specific enough to identify a video: three or more digits (years, large figures) or a decimal.

    Two-digit numbers such as 45 or 70 turn up in most transcripts by coincidence, so they cannot say which
    video a fact came from; counting them would flag honest rows.
    """
    return {n for n in _numbers(text) if len(n.replace(".", "")) >= 3 or "." in n}


def bled_rows(rows: list[dict[str, Any]], own: str, siblings: list[str]) -> list[dict[str, Any]]:
    """Rows carrying a distinctive number that is absent from the own source but present in a sibling's."""
    own_nums = _numbers(own)
    sibling_nums: set[str] = set()
    for text in siblings:
        sibling_nums |= _numbers(text)
    out = []
    for r in rows:
        stray = [n for n in _distinctive(str(r.get("fact_text", ""))) if n not in own_nums]
        if stray and all(n in sibling_nums for n in stray):
            out.append(r)
    return out


MAX_BLEED_ROWS = 1


def judge(rows: list[dict[str, Any]], source: str, unit: str = "",
          reviewed_empty: bool = False, siblings: list[str] | None = None,
          dated: bool = False) -> FileVerdict:
    reasons: list[str] = []
    chars = max(1, len(source))
    if not rows:
        # An empty file is valid when the source is short, or a person has reviewed it and confirmed it is
        # not market content. Otherwise a long source with no rows looks like a model that skimmed.
        if chars > 12_000 and not reviewed_empty:
            reasons.append("no rows from a long source: likely skimmed")
        return FileVerdict(unit, 0, not reasons, reasons)
    bad_schema = [r for r in rows if set(r) != KEYS or len(str(r.get("fact_text", ""))) > 300
                  or r.get("confidence") not in ("fact", "analyst_view")
                  or (not dated and "undated" not in str(r.get("source_name", "")).lower())]
    if bad_schema:
        reasons.append(f"{len(bad_schema)} row(s) break the schema")
    src_nums = _numbers(source)
    total = sum(len(_numbers(r["fact_text"])) for r in rows if "fact_text" in r)
    found = sum(1 for r in rows if "fact_text" in r for n in _numbers(r["fact_text"]) if n in src_nums)
    if total >= 6 and found / total < MIN_GROUNDING:
        reasons.append(f"only {found}/{total} numbers appear in the source: possible invention")
    bled = bled_rows(rows, source, siblings or [])
    if len(bled) > MAX_BLEED_ROWS:
        reasons.append(f"{len(bled)} row(s) carry numbers found only in another video of the same chunk")
    rel = sum(1 for r in rows if _RELATIVE.search(str(r.get("period") or "")))
    if rel:
        reasons.append(f"{rel} row(s) carry a relative period")
    if dated:
        rel_text = sum(1 for r in rows if _RELATIVE_TEXT.search(str(r.get("fact_text", ""))))
        if rel_text:
            reasons.append(f"{rel_text} row(s) use a relative time word in the sentence")
    advice = sum(1 for r in rows if _ADVICE.search(str(r.get("fact_text", ""))))
    if advice / len(rows) > MAX_ADVICE_SHARE:
        reasons.append(f"{advice} row(s) read as advice")
    if chars > 12_000 and len(rows) / (chars / 1000) < MIN_DENSITY:
        reasons.append(f"{len(rows)} rows from {chars // 1000}K chars is too sparse")
    return FileVerdict(unit, len(rows), not reasons, reasons)


def _blocks(unit_chunk: str, chunk_dir: Path) -> list[str]:
    return (chunk_dir / f"{unit_chunk}.md").read_text(encoding="utf-8").split("===== VIDEO =====")[1:]


def _matches(block: str, unit: str) -> bool:
    vid, _, part = unit.partition("__p")
    return f"VIDEO_ID: {vid}" in block and (not part or f"(PART {part} of" in block)


def _source_for(unit: str, chunk_dir: Path, manifest: dict[str, list[str]]) -> tuple[str, list[str]]:
    """The source text of one unit, and the text of the OTHER units in the same chunk."""
    for name, units in manifest.items():
        if unit in units:
            own, others = "", []
            for block in _blocks(name, chunk_dir):
                if _matches(block, unit):
                    own = block
                else:
                    others.append(block)
            return own, others
    return "", []


def check(out_dir: Path, chunk_dir: Path, reviewed_empty: frozenset[str] = frozenset(),
          dated: bool = False) -> list[FileVerdict]:
    manifest = json.loads((chunk_dir / "manifest.json").read_text(encoding="utf-8"))
    verdicts = []
    for path in sorted(glob.glob(str(out_dir / "*.json"))):
        unit = os.path.basename(path)[:-5]
        try:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            verdicts.append(FileVerdict(unit, 0, False, ["unreadable JSON"]))
            continue
        own, siblings = _source_for(unit, chunk_dir, manifest)
        verdicts.append(judge(rows, own, unit, unit in reviewed_empty, siblings, dated))
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--chunk-dir", required=True, type=Path)
    parser.add_argument("--reviewed-empty", type=Path, default=None,
                        help="JSON list of unit ids whose empty output a person has confirmed is correct")
    parser.add_argument("--dated", action="store_true",
                        help="verified upload dates: no 'undated' source, no relative time words")
    args = parser.parse_args(argv)
    reviewed = frozenset(json.loads(args.reviewed_empty.read_text(encoding="utf-8"))) \
        if args.reviewed_empty else frozenset()
    verdicts = check(args.out_dir, args.chunk_dir, reviewed, args.dated)
    failed = [v for v in verdicts if not v.ok]
    print(f"{len(verdicts)} file(s): {len(verdicts) - len(failed)} pass, {len(failed)} to escalate; "
          f"{sum(v.rows for v in verdicts)} rows")
    for v in failed:
        print(f"  ESCALATE {v.unit}: {'; '.join(v.reasons)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
