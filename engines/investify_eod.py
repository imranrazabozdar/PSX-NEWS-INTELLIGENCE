"""End-of-day progress report for the Investify library. Reads stored data and the audit log only; no fetch.

Backfill progress, against the watchlist:
* library coverage: companies with at least one stored dataset, over the watchlist (the backfill percent);
* pass 1, breadth: companies with a profile or fundamentals record;
* pass 2, depth: companies with all four datasets (profile, fundamentals, competitors, announcements).

Today's announcements (Pakistan time), grouped by the taxonomy, with Material, Insiders and Financials
highlighted.
Each company's data-as-of time is shown, so stale data is visible rather than silent.

The good-citizen footprint for the day (requests, 304 share, budget used, any cooldown).

The report is persisted as one JSON file per day, so progress can be compared day over day.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from collectors import investify_good_citizen as gc
from collectors import investify_policy as pol
from engines import investify_taxonomy as tax

DATASETS = ("profile", "fundamentals", "competitors", "announcements")
HIGHLIGHT = ("Material", "Insiders", "Financials")
SOURCE_ID = "investify_fundamentals"


def _stored(db: Any, symbol: str, endpoint: str) -> dict[str, Any] | None:
    rows = db.execute("SELECT source_metadata_json FROM source_items WHERE source_id = ? AND "
                      "(external_id = ? OR external_id LIKE ?) ORDER BY collected_at_utc DESC LIMIT 1",
                      (SOURCE_ID, f"{symbol}:{endpoint}", f"{symbol}:{endpoint}:%"))
    if not rows:
        return None
    meta = json.loads(rows[0]["source_metadata_json"])
    return {"fields": meta.get("fields") or {}, "fetched_at_utc": meta.get("fetched_at_utc")}


def _pkt_day(text: str) -> str:
    return pol._utc(text).astimezone(pol.PKT).date().isoformat()


def _percent(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def build_report(db: Any, *, watchlist: list[str], day: str, now: datetime,
                 audit_events: list[dict[str, Any]], policy: gc.Policy | None) -> dict[str, Any]:
    total = len(watchlist)
    company_data: dict[str, dict[str, Any]] = {}
    for sym in watchlist:
        got = {ep: _stored(db, sym, ep) for ep in DATASETS}
        company_data[sym] = {ep: (rec["fetched_at_utc"] if rec else None) for ep, rec in got.items()}
        company_data[sym]["_announcements"] = (got["announcements"] or {}).get("fields", {}).get("items", [])
    with_any = [s for s, d in company_data.items() if any(d[ep] for ep in DATASETS)]
    with_profile_or_fund = [s for s, d in company_data.items() if d["profile"] or d["fundamentals"]]
    all_four = [s for s, d in company_data.items() if all(d[ep] for ep in DATASETS)]

    todays: list[dict[str, Any]] = []
    for sym in watchlist:
        for item in company_data[sym]["_announcements"]:
            if _pkt_day(item["announced_at_utc"]) == day:
                group = tax.classify(item.get("event_type"), item.get("sub_type"))
                todays.append({"symbol": sym, "group": group, "sub_type": item.get("sub_type"),
                               "title": item.get("title"), "announced_at_utc": item["announced_at_utc"],
                               "highlight": group in HIGHLIGHT})
    todays.sort(key=lambda r: (not r["highlight"], r["symbol"], r["announced_at_utc"]))
    counts = {g: 0 for g in tax.GROUPS}
    for r in todays:
        counts[r["group"]] += 1

    footprint = gc.footprint(audit_events, now, policy)
    cooldowns = [e for e in audit_events if e.get("event") == "owner_alert"]
    report = {
        "day_pkt": day,
        "generated_utc": pol._iso(now),
        "backfill": {
            "watchlist_total": total,
            "library_coverage_percent": _percent(len(with_any), total),
            "pass1_breadth_percent": _percent(len(with_profile_or_fund), total),
            "pass2_depth_percent": _percent(len(all_four), total),
            "companies_with_any_data": len(with_any),
            "companies_with_all_four": len(all_four),
        },
        "announcements_today": {"count": len(todays), "by_group": counts, "items": todays},
        "companies": {sym: {ep: company_data[sym][ep] for ep in DATASETS} for sym in watchlist},
        "footprint": footprint,
        "cooldowns_today": [{"at": e.get("ts_utc"), "why": e.get("why")} for e in cooldowns
                            if e.get("ts_utc") and _pkt_day(e["ts_utc"]) == day],
        "data_note": "Announcements are the stored records as of their fetch time; they are not live.",
    }
    return report


def render_text(report: dict[str, Any]) -> str:
    b = report["backfill"]
    a = report["announcements_today"]
    f = report["footprint"]
    lines = [
        f"Investify EOD, {report['day_pkt']} (Pakistan time). Private research use; "
        "attribution: investify.pk.",
        f"Backfill: library coverage {b['library_coverage_percent']}% ({b['companies_with_any_data']} of "
        f"{b['watchlist_total']}); pass 1 breadth {b['pass1_breadth_percent']}%; pass 2 depth "
        f"{b['pass2_depth_percent']}%.",
        f"Announcements today: {a['count']}. " + ", ".join(f"{g} {n}" for g, n in a["by_group"].items() if n),
    ]
    for it in a["items"]:
        if it["highlight"]:
            lines.append(f"  ! {it['symbol']} [{it['group']}] {it['title']}")
    lines.append(f"Footprint: {f['requests_today']} requests today, {f['requests_this_week']} this week, "
                 f"304 share {f['share_304_percent']}%, errors {f['errors']}.")
    for w in f["warnings"]:
        lines.append(f"  {w}")
    if report["cooldowns_today"]:
        lines.append(f"Cooldowns today: {len(report['cooldowns_today'])} (owner alerted).")
    lines.append(report["data_note"])
    return "\n".join(lines)


def persist(report: dict[str, Any], directory: Path) -> Path:
    """One JSON file per day. Refuses to overwrite a day already written, so the history stays intact."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{report['day_pkt']}.json"
    if path.exists():
        raise FileExistsError(f"EOD report for {report['day_pkt']} already exists: {path}")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return path
