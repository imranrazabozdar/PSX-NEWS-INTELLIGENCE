#!/usr/bin/env python3
"""Generate docs/SOURCE_ACCESS_REGISTER.md from database/seed/*.json (do not edit it by hand).

Usage: python scripts/build_source_register.py [--check]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "SOURCE_ACCESS_REGISTER.md"


def _cell(v) -> str:
    return "" if v is None else str(v).replace("|", "\\|").replace("\n", " ")


def build() -> str:
    reg = json.loads((ROOT / "database/seed/sources.json").read_text(encoding="utf-8"))
    wl = json.loads((ROOT / "database/seed/media_watchlist.json").read_text(encoding="utf-8"))
    src = reg["sources"]
    lines = [
        "# Source access and licensing register",
        "",
        "Generated from `database/seed/sources.json` and `database/seed/media_watchlist.json` by",
        "`scripts/build_source_register.py`. Do not edit by hand. "
        f"Access review date: {reg.get('reviewed_on', 'n/a')}.",
        "",
        "**No source is ACTIVE.** A source can only become ACTIVE through a reviewed change to the",
        "registry seed, once its terms are `approved` and access is `verified_permitted`. The database",
        "enforces this with a trigger. Registering a provider or access route records how data could",
        "be obtained lawfully; it is **not** permission to collect or store data.",
        "",
        "Collector status (lifecycle) and feed freshness are separate: a collector can be implemented",
        "and its last test can pass while the feed itself is stale.",
        "",
        "## Status summary",
        "",
        "| Lifecycle status | Sources |",
        "|---|---|",
    ]
    for status, n in sorted(Counter(s["lifecycle_status"] for s in src).items()):
        lines.append(f"| {status} | {n} |")
    lines += ["", "## Sources", "",
              "| Priority | Source ID | Name | Official URL | Category | Format / adapter | Terms "
              "| Licensing | Access | Lifecycle | Last test | Newest item | Freshness | Review notes |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in sorted(src, key=lambda s: (s.get("priority") or 9, s["source_id"])):
        fmt = s.get("content_format", "unknown") + (f" / {s['adapter']}" if s.get("adapter") else "")
        lines.append("| " + " | ".join(_cell(x) for x in (
            s.get("priority"), s["source_id"], s["name"], s.get("official_url"), s.get("category"), fmt,
            s.get("terms_status"), s.get("licensing_status"), s.get("access_status"),
            s.get("lifecycle_status"),
            f"{s.get('last_test_result', 'not_tested')} {(s.get('last_test_at_utc') or '')[:10]}".strip(),
            s.get("newest_item_at_utc"), s.get("freshness_status", "unknown"),
            s.get("review_notes"))) + " |")
    lines += ["", "## Social and media watchlist (collection: Phase 11)", "",
              "Handles and URLs are exactly as supplied by the owner. All accounts are `disabled`, have no",
              "authorised access yet, and their identity is unverified.", "",
              "| Platform | Handle | Supplied URL | Category | Purpose | Notes |",
              "|---|---|---|---|---|---|"]
    for a in wl["accounts"]:
        lines.append("| " + " | ".join(_cell(x) for x in (
            a["platform"], a["handle"] or f"(pending: {a['display_name']})", a.get("supplied_url"),
            a.get("category"), a.get("monitoring_purpose"), a.get("notes"))) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    text = build()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("docs/SOURCE_ACCESS_REGISTER.md is out of date; run scripts/build_source_register.py")
            return 1
        print("Source register is up to date.")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
