"""Quality gate for model-extracted rows: decide which outputs to trust and which to escalate.

The routing rule is "cheapest model that passes a measured check". This is the check. For every
per-video output file it measures, against that video's OWN source text:

* schema   : exact keys, fact_text <= 300 chars, confidence in {fact, analyst_view}, source says undated
* grounding: the share of numbers in fact_text that actually appear in the source transcript. A number
             the speaker never said is the clearest sign a model invented a figure
* dating   : a relative period ("last year", "currently") is a defect: it mixes eras
* advice   : buy/sell/target-price wording, which this system never emits
* density  : rows per 1,000 source characters. Too sparse means the model skimmed

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


def judge(rows: list[dict[str, Any]], source: str, unit: str = "",
          reviewed_empty: bool = False) -> FileVerdict:
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
                  or "undated" not in str(r.get("source_name", "")).lower()]
    if bad_schema:
        reasons.append(f"{len(bad_schema)} row(s) break the schema")
    src_nums = _numbers(source)
    total = sum(len(_numbers(r["fact_text"])) for r in rows if "fact_text" in r)
    found = sum(1 for r in rows if "fact_text" in r for n in _numbers(r["fact_text"]) if n in src_nums)
    if total >= 6 and found / total < MIN_GROUNDING:
        reasons.append(f"only {found}/{total} numbers appear in the source: possible invention")
    rel = sum(1 for r in rows if _RELATIVE.search(str(r.get("period") or "")))
    if rel:
        reasons.append(f"{rel} row(s) carry a relative period")
    advice = sum(1 for r in rows if _ADVICE.search(str(r.get("fact_text", ""))))
    if advice / len(rows) > MAX_ADVICE_SHARE:
        reasons.append(f"{advice} row(s) read as advice")
    if chars > 12_000 and len(rows) / (chars / 1000) < MIN_DENSITY:
        reasons.append(f"{len(rows)} rows from {chars // 1000}K chars is too sparse")
    return FileVerdict(unit, len(rows), not reasons, reasons)


def _source_for(unit: str, chunk_dir: Path, manifest: dict[str, list[str]]) -> str:
    """The source text of one unit: its block inside whichever chunk file holds it."""
    for name, units in manifest.items():
        if unit in units:
            text = (chunk_dir / f"{name}.md").read_text(encoding="utf-8")
            vid, _, part = unit.partition("__p")
            for block in text.split("===== VIDEO =====")[1:]:
                if f"VIDEO_ID: {vid}" not in block:
                    continue
                if part and f"(PART {part} of" not in block:
                    continue
                return block
    return ""


def check(out_dir: Path, chunk_dir: Path, reviewed_empty: frozenset[str] = frozenset()) -> list[FileVerdict]:
    manifest = json.loads((chunk_dir / "manifest.json").read_text(encoding="utf-8"))
    verdicts = []
    for path in sorted(glob.glob(str(out_dir / "*.json"))):
        unit = os.path.basename(path)[:-5]
        try:
            rows = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            verdicts.append(FileVerdict(unit, 0, False, ["unreadable JSON"]))
            continue
        verdicts.append(judge(rows, _source_for(unit, chunk_dir, manifest), unit, unit in reviewed_empty))
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--chunk-dir", required=True, type=Path)
    parser.add_argument("--reviewed-empty", type=Path, default=None,
                        help="JSON list of unit ids whose empty output a person has confirmed is correct")
    args = parser.parse_args(argv)
    reviewed = frozenset(json.loads(args.reviewed_empty.read_text(encoding="utf-8"))) \
        if args.reviewed_empty else frozenset()
    verdicts = check(args.out_dir, args.chunk_dir, reviewed)
    failed = [v for v in verdicts if not v.ok]
    print(f"{len(verdicts)} file(s): {len(verdicts) - len(failed)} pass, {len(failed)} to escalate; "
          f"{sum(v.rows for v in verdicts)} rows")
    for v in failed:
        print(f"  ESCALATE {v.unit}: {'; '.join(v.reasons)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
