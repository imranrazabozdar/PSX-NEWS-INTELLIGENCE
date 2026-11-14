"""Run the three-lens council over one event and print the verdict. Optionally store it.

Runs anywhere the free-tier keys are in the environment: a GitHub Actions job needs no Claude Code and
no interactive session. The evidence pack is built HERE, in Python, from psx-library research_fact rows
and the event text; the models receive only that pack and never fetch anything themselves.

Default is a dry run: it prints the verdict as JSON and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from engines import analyst_council as council
from engines import library_db, llm

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0003_council_verdict.sql"
INSERT = ("INSERT INTO council_verdict (event, created_at, lenses_answered, conflict_count, "
          "verdict_json) VALUES (?, ?, ?, ?, ?)")
# Which lens each kind of stored knowledge belongs to. A topic with no rule here is not shown to anyone,
# so a new topic cannot quietly reach a lens that should not weigh it.
TOPIC_KIND = (
    ("announcements.", "announcement"),
    ("report.", "figure"),
    ("fundamentals.", "figure"),
    ("balance_sheet", "figure"),
    ("receivables", "figure"),
    ("operating_cash", "figure"),
    ("eps", "figure"),
    ("revenue", "figure"),
    ("net_profit", "figure"),
    ("finance_costs", "figure"),
    ("dividend", "figure"),
    ("valuation.", "sector_rule"),
    ("cost.", "sector_rule"),
    ("cycle.", "sector_rule"),
    ("capacity.", "sector_rule"),
    ("operations.", "sector_rule"),
    ("strategy.", "sector_rule"),
    ("signal.", "sector_rule"),
    ("returns.", "sector_rule"),
    ("macro.", "macro"),
    ("policy_rate", "macro"),
    ("profile.", "note"),
    ("competitors.", "note"),
)


def kind_for(topic: str) -> str | None:
    for prefix, kind in TOPIC_KIND:
        if topic.startswith(prefix):
            return kind
    return None


def build_pack(event: str, companies: list[str], db: Any, *, limit_per_company: int = 40,
               news: list[str] | None = None) -> council.EvidencePack:
    """The event, plus what the brain already knows about these companies and their sectors."""
    items: list[council.Evidence] = []
    for n, text in enumerate(news or [], start=1):
        items.append(council.Evidence(f"n{n}", "news", text[:500], "Owner-supplied event text",
                                      "", company=companies[0] if companies else None))
    if not items:
        items.append(council.Evidence("n1", "news", event[:500], "Owner-supplied event text", ""))
    seq = 0
    for company in companies:
        rows = db.execute(
            "SELECT topic, fact_text, source_name, source_date FROM research_fact "
            "WHERE company = ? ORDER BY id DESC LIMIT ?", (company, limit_per_company))
        for row in rows:
            kind = kind_for(str(row["topic"]))
            if kind is None:
                continue
            seq += 1
            items.append(council.Evidence(
                f"e{seq}", kind, str(row["fact_text"]), str(row["source_name"]),
                str(row["source_date"]), company=company))
    return council.EvidencePack(event=event, items=items)


def run(event: str, companies: list[str], *, store: bool, db: Any = None,
        gateway_for: Any = None) -> int:
    if db is None:
        conn = library_db.get_library_connection()  # target guard runs here
        db = conn.db
        print(f"library host: {conn.host}", file=sys.stderr)
    pack = build_pack(event, companies, db)
    print(f"evidence pack: {len(pack.items)} item(s) across {len(pack.companies)} company(ies)",
          file=sys.stderr)
    if gateway_for is None:
        def gateway_for(role: str) -> Any:
            return llm.LLMGateway(provider=council.provider_for_role(role),
                                  pricing=llm.Pricing(0.0, 0.0), limits=llm.Limits.from_env())
    try:
        verdict = council.deliberate(pack, gateway_for)
    except council.CouncilError as exc:
        print(f"council REFUSED: {exc}", file=sys.stderr)
        return 3
    payload = verdict.to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"lenses that answered: {', '.join(verdict.lenses_that_answered) or 'none'}", file=sys.stderr)
    print(f"conflicts found: {len(verdict.conflicted)}", file=sys.stderr)
    if not store:
        print("dry run: nothing stored. Re-run with --store to keep this verdict.", file=sys.stderr)
        return 0
    from scripts import apply_library_migration as mig

    for stmt in mig.statements(SCHEMA.read_text(encoding="utf-8")):
        db.execute(stmt)
    db.execute(INSERT, (verdict.event, verdict.created_at, ",".join(verdict.lenses_that_answered),
                        len(verdict.conflicted), json.dumps(payload, sort_keys=True)))
    print("verdict stored.", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--event", required=True, help="what happened, in one or two sentences")
    parser.add_argument("--companies", default="",
                        help="comma-separated tickers whose stored knowledge to put in the pack")
    parser.add_argument("--store", action="store_true", help="keep the verdict (default: dry run)")
    args = parser.parse_args(argv)
    companies = [c.strip().upper() for c in args.companies.split(",") if c.strip()]
    try:
        return run(args.event, companies, store=args.store)
    except library_db.LibraryConfigError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
