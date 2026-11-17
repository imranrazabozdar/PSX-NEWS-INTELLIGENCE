"""Run the three-lens council over one event and print the verdict. Optionally store it.

Runs anywhere the free-tier keys are in the environment: a GitHub Actions job needs no Claude Code and
no interactive session. The evidence pack is built HERE, in Python, from psx-library research_fact rows
and the event text; the models receive only that pack and never fetch anything themselves.

Default is a dry run: it prints the verdict as JSON and writes nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from engines import analyst_council as council
from engines import freshness, library_db, llm
from engines import research_facts as rf

SCHEMA = Path(__file__).resolve().parents[1] / "database" / "library" / "0003_council_verdict.sql"
INSERT = ("INSERT INTO council_verdict (event, created_at, lenses_answered, conflict_count, "
          "verdict_json) VALUES (?, ?, ?, ?, ?)")
# Which lens each kind of stored knowledge belongs to. A topic with no rule here is not shown to anyone,
# so a new topic cannot quietly reach a lens that should not weigh it.
TOPIC_KIND = (
    ("announcements.", "announcement"),
    # PSX feed: results are figures; dividends, closures, meetings and issues are notices.
    ("results.", "figure"),
    ("corporate_action.", "announcement"),
    # Dated channel facts (verified upload date): reported results and payouts are figures for the financial
    # lens, other company/economy events are news, and market data (index, oil, flows, rates) is macro.
    ("news.results", "figure"),
    ("news.dividend", "figure"),
    ("news.", "announcement"),
    ("market.", "macro"),
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
    ("tax.", "macro"),
    ("policy_rate", "macro"),
    ("profile.", "note"),
    ("competitors.", "note"),
    # Analyst commentary about ONE company: its thesis, risks, catalysts, quality of management. This
    # is the financial lens's business, not the macro lens's -- it is a reading of the company itself.
    ("commentary.", "note"),
    ("risk.", "note"),
    ("thesis.", "note"),
    ("catalyst.", "note"),
    # How to analyse something (a valuation approach, a rule of thumb) belongs with the accounts.
    ("method.", "note"),
)


def kind_for(topic: str) -> str | None:
    for prefix, kind in TOPIC_KIND:
        if topic.startswith(prefix):
            return kind
    return None


def sectors_for(companies: list[str], db: Any, extra: list[str] | None = None,
                by_company: dict[str, list[dict]] | None = None, known: set[str] | None = None) -> list[str]:
    """Which SECTOR:* knowledge belongs with these companies.

    A sector is included when it was asked for, or when its name is one of the dotted segments of a
    company's own stored topic. The match is on whole segments, not on substrings: "announcements"
    contains "cement", so a substring test would hand cement knowledge to every company that has ever
    filed an announcement.

    Without this the macro lens has nothing to cite, every assessment it makes is discarded for citing
    no evidence, and the council loses the one lens that looks for second-order effects.

    `by_company` holds the facts build_pack already read; `known` is the set of SECTOR:* entities. Without
    them this queries the database (by index).
    """
    if known is None:
        known = ({c for c in by_company if c.startswith("SECTOR:")} if by_company is not None
                 else rf.sector_names(db))
    wanted = {f"SECTOR:{s.strip().upper()}" for s in (extra or []) if s.strip()} & known
    segments: set[str] = set()
    for company in companies:
        if by_company is not None:
            topics = {str(r["topic"]) for r in by_company.get(company, [])}
        else:
            topics = {str(r["topic"]) for r in
                      db.execute("SELECT DISTINCT topic FROM research_fact WHERE company = ?", (company,))}
        for topic in topics:
            segments.update(re.split(r"[^a-z0-9]+", topic.lower()))
    for sector in known:
        if sector.split(":", 1)[1].lower() in segments:
            wanted.add(sector)
    return sorted(wanted)


def _date_map(db: Any) -> dict[str, str]:
    """url -> verified upload date for archive videos. One small read per pack (215 rows), not a join
    per fact: the join scanned video_source for every fact row and burned the row budget."""
    try:
        return {str(r["url"]): str(r["day"]) for r in db.execute(
            "SELECT v.url AS url, d.date_to AS day FROM video_source v "
            "JOIN video_dating d ON d.video_id = v.video_id")}
    except library_db.LibraryConfigError:
        raise
    except Exception as exc:  # noqa: BLE001 - archive tables absent (older database)
        if "budget" in str(exc).lower():
            raise
        return {}


def _is_budget(exc: Exception) -> bool:
    return "budget" in str(exc).lower()


def _dated_rows(rows: list[dict], dates: dict[str, str]) -> list[dict]:
    """An entity's facts, newest first by the video's verified upload date (shown as source_date).

    A fact with no dated source keeps its own source_date. Sorting is done here, on rows read once,
    because the facts table has no index on company and every extra query scans all of it.
    """
    out = [dict(r, source_date=dates.get(str(r["source_url"]), str(r["source_date"]))) for r in rows]
    out.sort(key=lambda r: (str(r["source_date"]), int(r["id"])), reverse=True)
    return out


def _brief(rows: list[dict], company: str) -> str:
    """What the brain holds on this company: size, span, strongest topics, source mix. Counts only."""
    if not rows:
        return f"The brain holds no stored knowledge on {company}; treat any view of it as unsupported."
    topics: dict[str, int] = {}
    for r in rows:
        topics[str(r["topic"])] = topics.get(str(r["topic"]), 0) + 1
    top = ", ".join(f"{t} ({n})" for t, n in sorted(topics.items(), key=lambda kv: -kv[1])[:6])
    total = len(rows)
    text = f"{company}: {total} stored fact(s) across {len(topics)} topic(s); most covered: {top}."
    channels = {str(r["source_name"]).split(",")[0] for r in rows}
    views = sum(1 for r in rows if r.get("confidence") == "analyst_view")
    text += (f" Drawn from {len(channels)} distinct source(s); {views} of {total} are analyst views, "
             "not reported figures.")
    if len(channels) == 1:
        text += " Single-source knowledge: weigh with caution."
    from scripts import apply_entity_aliases

    if company in apply_entity_aliases.delisted():
        text += " DELISTED on PSX: these facts are history, not a live stock."
    return text


def _link_items(db: Any, entities: list[str], wanted: set[str], start: int, dates: dict[str, str],
                limit: int = 8) -> list[Any]:
    """Stored driver -> affected links for these entities, event-relevant first, newest source first.

    Each is an analyst's stated cause-and-effect, quoted from the fact it came from, never a calculation.
    One query for all entities (the table has no index on `affected`, so one scan, not one per entity).
    """
    marks = ",".join("?" for _ in entities)
    try:
        sql = ("SELECT l.affected, l.driver, l.direction, l.quote, f.source_url, f.source_date "  # noqa: S608
               "FROM company_link l JOIN research_fact f ON f.id = l.fact_id "
               f"WHERE l.affected IN ({marks})")  # only "?" placeholders are interpolated
        rows = [dict(r) for r in db.execute(sql, tuple(entities))]
    except Exception as exc:  # noqa: BLE001 - link table absent (older database)
        if _is_budget(exc):
            raise
        return []
    out: list[Any] = []
    seq = start
    for entity in entities:
        mine = [r for r in rows if r["affected"] == entity]
        for row in mine:
            row["day"] = dates.get(str(row["source_url"]), str(row["source_date"]))
        mine.sort(key=lambda r: str(r["day"]), reverse=True)
        mine.sort(key=lambda r: not (wanted & freshness.factors_in(f"{r['driver']} {r['quote']}")))
        for row in mine[:limit]:
            seq += 1
            text = f"Analyst view: {row['driver']} affects {entity} ({row['direction']}): {row['quote']}"
            out.append(council.Evidence(f"l{seq}", "macro", text, "Stored cause-and-effect link",
                                        freshness.age_text(str(row["day"])), company=entity))
    return out


def build_pack(event: str, companies: list[str], db: Any, *, limit_per_company: int = 40,
               news: list[str] | None = None, sectors: list[str] | None = None) -> council.EvidencePack:
    """The event, plus what the brain already knows about these companies and their sectors."""
    items: list[council.Evidence] = []
    for n, text in enumerate(news or [], start=1):
        items.append(council.Evidence(f"n{n}", "news", text[:500], "Owner-supplied event text",
                                      "", company=companies[0] if companies else None))
    if not items:
        items.append(council.Evidence("n1", "news", event[:500], "Owner-supplied event text", ""))
    seq = 0
    # Only this pack's entities are read (idx_research_fact_company), then the sectors that belong to them.
    columns = "id, company, topic, fact_text, source_name, source_url, source_date, confidence"
    by_company: dict[str, list[dict]] = {}

    def read(names: list[str]) -> None:
        for r in rf.facts_for(db, [n for n in names if n not in by_company], columns):
            by_company.setdefault(str(r["company"]), []).append(dict(r))
        for n in names:
            by_company.setdefault(n, [])

    read(list(companies) + ["MACRO:PAKISTAN"])
    for company in companies:
        items.append(council.Evidence(f"b{company}", "note", _brief(by_company.get(company, []), company),
                                      "Brain summary (computed)", "", company=company))
    wanted = freshness.factors_in(event + " " + " ".join(news or []))
    dates = _date_map(db)
    # MACRO:PAKISTAN is always in the pack: the macro lens needs the country backdrop for any event.
    chosen = sectors_for(companies, db, sectors, by_company, known=rf.sector_names(db))
    read(chosen)
    entities = list(companies) + chosen + ["MACRO:PAKISTAN"]
    for company in entities:
        rows = _dated_rows(by_company.get(company, []), dates)
        # Facts about the factors this event touches first, then the rest, each newest-first.
        rows.sort(key=lambda r: not (wanted & freshness.factors_in(f"{r['topic']} {r['fact_text']}")))
        for row in rows[:limit_per_company]:
            kind = kind_for(str(row["topic"]))
            if kind is None:
                continue
            seq += 1
            items.append(council.Evidence(
                f"e{seq}", kind, str(row["fact_text"]), str(row["source_name"]),
                freshness.age_text(str(row["source_date"])), company=company))
    items.extend(_link_items(db, entities, wanted, seq, dates))
    return council.EvidencePack(event=event, items=items)


def run(event: str, companies: list[str], *, store: bool, db: Any = None,
        gateway_for: Any = None, sectors: list[str] | None = None) -> int:
    if db is None:
        conn = library_db.get_library_connection()  # target guard runs here
        db = conn.db
        print(f"library host: {conn.host}", file=sys.stderr)
    pack = build_pack(event, companies, db, sectors=sectors)
    print(f"evidence pack: {len(pack.items)} item(s) across {len(pack.companies)} company(ies)",
          file=sys.stderr)
    if gateway_for is None:
        def gateway_for(role: str) -> Any:
            # db is passed so an account already at its free-tier limit is skipped before any call.
            return llm.LLMGateway(provider=council.provider_for_role(role, db=db),
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
    parser.add_argument("--sectors", default="",
                        help="comma-separated sector knowledge to add, e.g. CEMENT")
    parser.add_argument("--store", action="store_true", help="keep the verdict (default: dry run)")
    args = parser.parse_args(argv)
    companies = [c.strip().upper() for c in args.companies.split(",") if c.strip()]
    try:
        sectors = [s.strip() for s in args.sectors.split(",") if s.strip()]
        return run(args.event, companies, store=args.store, sectors=sectors)
    except library_db.LibraryConfigError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
