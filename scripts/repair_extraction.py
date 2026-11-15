"""Repair extracted rows for a DATED channel without paying for a bigger model. Pure Python.

Step 1 (`clean`): drop only the rows that are individually defective -- a relative time word in the sentence,
a number that appears nowhere in the video, a number found only in a sibling video, or advice wording --
and keep the rest. Step 2 (`hints`): for every video whose figures were under-captured, list each missed
figure with the transcript text around it, so a small model only has to turn those few lines into rows
instead of re-reading the whole video.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from scripts import check_extraction_batch as gate

CONTEXT = 140  # characters of transcript kept on each side of a missed figure


def bad_row_reason(row: dict[str, Any], own: str, siblings: list[str]) -> str | None:
    text = str(row.get("fact_text", ""))
    if gate._RELATIVE_TEXT.search(text):
        return "relative"
    if gate._ADVICE.search(text):
        return "advice"
    own_nums = gate._numbers(own) | gate._date_parts(own)
    stray = [n for n in gate._checked(gate._numbers(text)) if n not in own_nums]
    if stray:
        sib: set[str] = set()
        for s in siblings:
            sib |= gate._numbers(s)
        return "bleed" if all(n in sib for n in stray) else "ungrounded"
    return None


def clean(rows: list[dict], own: str, siblings: list[str]) -> tuple[list[dict], dict[str, int]]:
    kept, dropped = [], {}
    for r in rows:
        why = bad_row_reason(r, own, siblings)
        if why:
            dropped[why] = dropped.get(why, 0) + 1
        else:
            kept.append(r)
    return kept, dropped


def missed_figures(rows: list[dict], source: str) -> list[tuple[str, str]]:
    """[(figure, transcript context)] for each distinctive figure in the source that no row carries."""
    have: set[str] = set()
    for r in rows:
        have |= gate._checked(gate._distinctive(str(r.get("fact_text", ""))))
    out, seen = [], set()
    for m in re.finditer(r"\d[\d,]*\.?\d*", source):
        n = m.group().replace(",", "").rstrip(".")
        if n in seen or n not in gate._checked(gate._distinctive(n)) or n in have:
            continue
        seen.add(n)
        a, b = max(0, m.start() - CONTEXT), min(len(source), m.end() + CONTEXT)
        out.append((n, " ".join(source[a:b].split())))
    return out


def _source_for(unit: str, chunk_dir: Path, manifest: dict[str, list[str]]) -> tuple[str, list[str]]:
    return gate._source_for(unit, chunk_dir, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--chunk-dir", type=Path, required=True)
    parser.add_argument("--clean-dir", type=Path, required=True)
    parser.add_argument("--hints-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads((args.chunk_dir / "manifest.json").read_text(encoding="utf-8"))
    args.clean_dir.mkdir(parents=True, exist_ok=True)
    args.hints_dir.mkdir(parents=True, exist_ok=True)
    totals: dict[str, int] = {}
    hinted = 0
    for path in sorted(args.out_dir.glob("*.json")):
        unit = path.stem
        rows = json.loads(path.read_text(encoding="utf-8"))
        own, siblings = _source_for(unit, args.chunk_dir, manifest)
        kept, dropped = clean(rows, own, siblings)
        for k, v in dropped.items():
            totals[k] = totals.get(k, 0) + v
        (args.clean_dir / path.name).write_text(
            json.dumps(kept, ensure_ascii=False, indent=1), encoding="utf-8")
        verdict = gate.judge(kept, own, unit, True, siblings, dated=True)
        if any("figures reached" in r for r in verdict.reasons):
            missed = missed_figures(kept, own)
            if missed:
                hinted += 1
                lines = [f"- {n}: ...{ctx}..." for n, ctx in missed]
                header = own.strip().splitlines()[:4]
                (args.hints_dir / f"{unit}.md").write_text(
                    "\n".join(header)
                    + "\n\nMISSED FIGURES (each needs a row if the transcript supports it):\n"
                    + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"rows dropped as defective: {totals}; videos needing a figures pass: {hinted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
