"""Turn the owner's PSX announcement export (announceWithSymbol.lis, or the .Z the exchange ships) into a
capsule.

Dry run only: writes a JSON capsule for scripts/absorb_sector_capsule.py and prints what it holds.
Nothing is loaded and
nothing is fetched from PSX: the file is one the owner downloaded and supplied.

    python -m scripts.build_psx_announcement_capsule announceWithSymbol.lis.Z --out capsule.json [--since
    2023-01-01]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from engines import psx_announcements as pa
from engines import psx_feed_parser
from engines import research_facts as rf


def read_text(path: Path) -> tuple[str, str]:
    """The file's text and its SHA-256. PSX ships a PKZip (even when the name ends .Z); a real
    UNIX-compressed .Z is
    unpacked with the system gzip; anything else is read as plain latin-1 text."""
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if data[:2] == b"PK":
        return psx_feed_parser.unpack_member(data, ".lis"), digest
    if data[:2] == b"\x1f\x9d":
        out = subprocess.run(["gzip", "-dc"], input=data, capture_output=True, check=True)  # noqa: S603, S607
        data = out.stdout
    return data.decode("latin-1"), digest


def build(path: Path, since: date) -> tuple[list[dict], Counter, str, int]:
    text, digest = read_text(path)
    lines = text.splitlines()
    rows, skipped = pa.build_rows(pa.read_announcements(lines), since)
    return [rf.validate_fact(r) for r in rows], skipped, digest, len(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("feed", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--since", default="2023-01-01")
    ap.add_argument("--examples", type=int, default=2)
    args = ap.parse_args(argv)
    rows, skipped, digest, n_lines = build(args.feed, date.fromisoformat(args.since))
    print(
        f"file sha256 {digest[:16]}...; {n_lines} lines; rows since {args.since}: {len(rows)}; "
        f"companies: {len({r['company'] for r in rows})}"
    )
    print("by topic:", dict(Counter(r["topic"] for r in rows).most_common()))
    print("by year:", dict(sorted(Counter(r["source_date"][:4] for r in rows).items())))
    print("lines not recognised (top):", dict(skipped.most_common(12)))
    seen: Counter = Counter()
    for r in rows:
        if seen[r["topic"]] < args.examples:
            seen[r["topic"]] += 1
            print(f"  [{r['topic']}] {r['company']} {r['source_date']}: {r['fact_text'][:150]}")
    args.out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"capsule written: {args.out}. Nothing was loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
