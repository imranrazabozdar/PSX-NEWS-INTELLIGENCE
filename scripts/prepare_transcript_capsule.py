"""Turn extracted transcript rows into ONE validated capsule for scripts/absorb_sector_capsule.py.

The archive these rows come from carries NO publication dates. That is handled explicitly rather than
papered over:

* `source_date` is the date the ARCHIVE WAS CAPTURED, not the date the video was published, and
  `source_name` says "undated" so the two are never confused.
* `period` carries the era the CLAIM belongs to, when the speaker stated one ("FY25", "Budget 2026").
  A time-bound claim with no stated period was dropped at extraction: an undated snapshot of a price
  or a policy rate would quietly mix eras, which is the one thing this archive must not do.

Near-duplicates are collapsed. One analyst repeating a point across 200 videos should leave ONE row,
so a later capsule about the same company adds knowledge instead of restating it.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from engines import research_facts as rf

ARCHIVE_CAPTURE_DATE = "2026-11-14"
SCHEMA_KEYS = set(rf.COLUMNS)
_WORD = re.compile(r"[a-z0-9]+")
# absorb_sector_capsule refuses a source that looks like a placeholder; a real title may contain "..."
_ELLIPSIS = re.compile(r"\.{3,}")


def normalise(text: str) -> frozenset[str]:
    """A bag of significant words: the comparison key for near-duplicate detection."""
    words = _WORD.findall(text.lower())
    return frozenset(w for w in words if len(w) > 3)


def is_near_duplicate(a: frozenset[str], b: frozenset[str], threshold: float = 0.75) -> bool:
    if not a or not b:
        return False
    overlap = len(a & b) / min(len(a), len(b))
    return overlap >= threshold


def convert(row: dict[str, Any]) -> dict[str, Any]:
    """One extracted row to one research_fact row. Raises ResearchFactError on anything malformed."""
    source = _ELLIPSIS.sub("…", str(row.get("source_name", "")).strip())
    out = {
        "company": str(row.get("company", "")).strip(),
        "topic": str(row.get("topic", "")).strip(),
        "fact_text": " ".join(str(row.get("fact_text", "")).split()),
        "value": row.get("value") if isinstance(row.get("value"), (int, float)) else None,
        "unit": (str(row["unit"]).strip() or None) if row.get("unit") else None,
        "period": (str(row["period"]).strip() or None) if row.get("period") else None,
        "source_name": source,
        "source_url": (str(row["source_url"]).strip() or None) if row.get("source_url") else None,
        "source_date": ARCHIVE_CAPTURE_DATE,
        "as_of": None,
        "confidence": str(row.get("confidence", "analyst_view")).strip(),
        "created_at": f"{ARCHIVE_CAPTURE_DATE}T00:00:00Z",
    }
    if "undated" not in out["source_name"].lower():
        raise rf.ResearchFactError(f"source must declare it is undated: {out['source_name'][:60]!r}")
    return rf.validate_fact(out)


def build(in_dir: Path, out_path: Path) -> int:
    files = sorted(glob.glob(str(in_dir / "*.json")))
    if not files:
        print(f"no extracted rows found in {in_dir}")
        return 1
    kept: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], list[frozenset[str]]] = {}
    read = dropped_dup = dropped_bad = 0
    problems: Counter[str] = Counter()
    for path in files:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        for raw in rows:
            read += 1
            try:
                row = convert(raw)
            except rf.ResearchFactError as exc:
                dropped_bad += 1
                problems[str(exc)[:70]] += 1
                continue
            key = (row["company"], row["topic"].split(".", 1)[0])
            words = normalise(row["fact_text"])
            if any(is_near_duplicate(words, prior) for prior in seen.get(key, [])):
                dropped_dup += 1
                continue
            seen.setdefault(key, []).append(words)
            kept.append(row)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(kept, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"read {read} row(s) from {len(files)} file(s)")
    print(f"  dropped as malformed : {dropped_bad}")
    for reason, n in problems.most_common(5):
        print(f"      {n:4d} x {reason}")
    print(f"  dropped as near-dupe : {dropped_dup}")
    print(f"  kept                 : {len(kept)}  ->  {out_path}")
    print("\ntop entities:")
    for company, n in Counter(r["company"] for r in kept).most_common(25):
        print(f"   {company:28} {n}")
    print("\ntopic families:")
    for fam, n in Counter(r["topic"].split(".", 1)[0] for r in kept).most_common():
        print(f"   {fam:28} {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    return build(args.in_dir, args.out)


if __name__ == "__main__":
    sys.exit(main())
