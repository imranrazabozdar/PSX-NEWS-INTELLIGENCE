"""Turn the owner's Investify export (investify_psx.db, a read-only SQLite file) into a research_fact capsule.

Dry run only: it writes a JSON capsule that scripts/absorb_sector_capsule.py can load. Nothing is loaded here.
Follows the existing Investify policy (engines/research_facts.rows_from_fields): distilled facts only.
Investify's own summary text, sentiment and materiality labels, and its technical buy/sell votes are never
stored; price and volume belong to the separate price system. Every row names the source, the page URL and
the export date.

    python -m scripts.build_investify_capsule /path/to/investify_psx.db --out capsule.json [--examples 5]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from engines import research_facts as rf

SOURCE = rf.SOURCE_NAME
ANN_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4}), \d{1,2}:\d{2} [AP]M$")
GROUPS_SKIP = {"Highlights", "Original PDF", "Original Image"}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _unit(raw: str) -> str | None:
    raw = raw.strip()
    if raw.endswith("%"):
        return "%"
    if raw.startswith("Rs"):
        return "PKR"
    return None


def metric_rows(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = []
    for sym, metric, raw, num, period, scraped in db.execute(
        "SELECT symbol, metric, raw_value, numeric_value, period, scraped_at FROM fundamentals_metrics"
    ):
        if num is None or not str(raw or "").strip():
            continue  # no number to keep: the label alone is not a fact
        day = scraped[:10]
        text = f"{metric}: {raw}" + (f" ({period})" if period else "")
        rows.append(
            rf.validate_fact(
                {
                    "company": sym,
                    "topic": f"fundamentals.{slug(metric)}",
                    "fact_text": text[: rf.MAX_FACT_CHARS],
                    "value": float(num),
                    "unit": _unit(str(raw)),
                    "period": period or None,
                    "source_name": SOURCE,
                    "source_url": f"https://investify.pk/company/{sym}/fundamentals",
                    "source_date": day,
                    "as_of": day,
                    "confidence": "fact",
                    "created_at": scraped,
                }
            )
        )
    return rows


def announcement_rows(sym: str, lines: list[str], scraped: str) -> list[dict[str, Any]]:
    """[... group, sentiment, 'dd/mm/yyyy, h:mm AM', title, summary ...]: keep date, group and title only."""
    rows = []
    for i, line in enumerate(lines):
        m = ANN_DATE.match(line)
        if not m or i < 2 or i + 1 >= len(lines):
            continue
        group, title = lines[i - 2].strip(), lines[i + 1].strip()
        if not title or group in GROUPS_SKIP or len(group) > 40:
            continue
        when = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        text = f"{when}: {title}"
        rows.append(
            rf.validate_fact(
                {
                    "company": sym,
                    "topic": f"announcements.{group}",
                    "fact_text": text[: rf.MAX_FACT_CHARS],
                    "value": None,
                    "unit": None,
                    "period": when,
                    "source_name": SOURCE,
                    "source_url": f"https://investify.pk/company/{sym}/announcements",
                    "source_date": scraped[:10],
                    "as_of": when,
                    "confidence": "fact",
                    "created_at": scraped,
                }
            )
        )
    return rows


def _after(lines: list[str], label: str, count: int = 1) -> list[str]:
    for i, line in enumerate(lines):
        if line == label:
            return lines[i + 1 : i + 1 + count]
    return []


def profile_rows(sym: str, lines: list[str], scraped: str) -> list[dict[str, Any]]:
    """Sector, leadership, registrar, auditor, address, website; the business description is never copied."""
    day = scraped[:10]
    url = f"https://investify.pk/company/{sym}/profile"
    out: list[dict[str, Any]] = []

    def add(topic: str, text: str, value: float | None = None, unit: str | None = None) -> None:
        out.append(
            rf.validate_fact(
                {
                    "company": sym,
                    "topic": f"profile.{topic}",
                    "fact_text": text[: rf.MAX_FACT_CHARS],
                    "value": value,
                    "unit": unit,
                    "period": None,
                    "source_name": SOURCE,
                    "source_url": url,
                    "source_date": day,
                    "as_of": day,
                    "confidence": "fact",
                    "created_at": scraped,
                }
            )
        )

    head = lines[:10]
    if (
        "PSX" in head
    ):  # the page header: ... symbol, bullet, PSX, market segment (Regular, Defaulter, ETF, ...)
        seg = lines[head.index("PSX") + 1]
        if seg in ("Regular", "Defaulter", "Preference", "ETF", "Non-voting"):
            add("market_segment", f"PSX market segment: {seg}")
    for i, line in enumerate(lines):  # the profile block: 'Company Profile', name, symbol, 'PSX', sector
        if line == "Company Profile" and i + 4 < len(lines) and lines[i + 3] == "PSX":
            sector = lines[i + 4].strip()
            if sector and len(sector) < 60:
                add("sector", f"Sector: {sector}")
            break
    for role, label in (
        ("Chairperson", "Chairperson"),
        ("CEO", "CEO"),
        ("Company Secretary", "Company secretary"),
    ):
        v = _after(lines, role)
        if v and v[0].strip() and len(v[0]) < 80:
            add("leadership", f"{label}: {v[0].strip()}")
    for label, topic in (
        ("Registered Address", "registered_address"),
        ("Website", "website"),
        ("Registrar", "registrar"),
        ("Auditor", "auditor"),
    ):
        v = _after(lines, label)
        if v and v[0].strip() and len(v[0]) < 250:
            add(topic, f"{label}: {v[0].strip()}")
    return out


def build(db_path: Path) -> list[dict[str, Any]]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = metric_rows(db)
    for sym, tab, js, scraped in db.execute("SELECT symbol, tab, lines_json, scraped_at FROM company_pages"):
        if tab not in ("announcements", "profile"):
            continue
        lines = [str(x) for x in json.loads(js)]
        rows += (
            announcement_rows(sym, lines, scraped)
            if tab == "announcements"
            else profile_rows(sym, lines, scraped)
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("db", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--examples", type=int, default=3)
    args = ap.parse_args(argv)
    rows = build(args.db)
    kinds = Counter(r["topic"].split(".")[0] for r in rows)
    print(f"rows: {len(rows)} | by kind: {dict(kinds)} | companies: {len({r['company'] for r in rows})}")
    groups = Counter(r["topic"] for r in rows if r["topic"].startswith("announcements."))
    print("announcement groups:", dict(groups.most_common(8)))
    seen: Counter = Counter()
    for r in rows:
        k = r["topic"].split(".")[0]
        if seen[k] < args.examples:
            seen[k] += 1
            print(f"  [{r['topic']}] {r['company']}: {r['fact_text'][:110]}")
    args.out.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    print(f"capsule written: {args.out}. Nothing was loaded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
