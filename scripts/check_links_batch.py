"""Score a batch of extracted company links against the facts they cite. Pure Python.

A link passes only when its fact_id exists, its quote is an exact substring of that fact, its direction
is one of the allowed words, and its `affected` entity is the fact's own company or named in the quote.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DIRECTIONS = {"up", "down", "mixed", "unclear"}
MIN_VALID = 0.90


def judge(links: list[dict], facts: list[dict]) -> dict:
    by_id = {int(f["id"]): f for f in facts}
    good, bad = [], []
    for link in links:
        fact = by_id.get(int(link.get("fact_id", -1)) if str(link.get("fact_id", "")).lstrip("-").isdigit()
                         else -1)
        quote = str(link.get("quote", ""))
        ok = (fact is not None and quote and quote in str(fact["fact_text"])
              and link.get("direction") in DIRECTIONS and link.get("driver") and link.get("affected"))
        (good if ok else bad).append(link)
    total = len(links)
    covered = {int(link["fact_id"]) for link in good}
    return {"links": total, "valid": len(good), "valid_share": (len(good) / total) if total else 0.0,
            "facts_with_links": len(covered), "passes": bool(total) and len(good) / total >= MIN_VALID,
            "invalid": bad}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("links", type=Path)
    parser.add_argument("facts", type=Path)
    args = parser.parse_args(argv)
    result = judge(json.loads(args.links.read_text()), json.loads(args.facts.read_text()))
    print(json.dumps({k: v for k, v in result.items() if k != "invalid"}, indent=2))
    for bad in result["invalid"][:5]:
        print("INVALID:", json.dumps(bad)[:200])
    return 0 if result["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
