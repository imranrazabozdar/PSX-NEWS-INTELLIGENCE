"""Multi-period annual series from PROMOTED financial metrics (M2 follow-on).

Reads only `financial_metrics` rows, which `financials.promote` writes after a report has passed the
balance-sheet and identity checks. It therefore never presents an unreconciled value. It adds three things
the single-report view does not give:

* gaps: a missing fiscal year between two annual periods is reported, never interpolated;
* not_promoted: annual reports on file that did not reconcile are listed and excluded, with their status;
* conflicts: a period with more than one report (an original and a restatement, or two uploads) is listed
  and LEFT OUT of the series. The engine never picks one silently.

No new table, no write, no network.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

GAP_DAYS = 400  # consecutive fiscal year ends further apart than this have a missing year


def year_gaps(periods: list[dict]) -> list[dict]:
    """Missing fiscal years between consecutive annual periods (ordered by period_end)."""
    gaps = []
    for a, b in zip(periods, periods[1:], strict=False):
        days = (date.fromisoformat(b["period_end"]) - date.fromisoformat(a["period_end"])).days
        if days > GAP_DAYS:
            gaps.append({"after": a["period_end"], "before": b["period_end"],
                         "missing_years": max(1, round(days / 365) - 1)})
    return gaps


def annual_series(db, company_id: str, *, scope: str, codes: tuple[str, ...] | None = None) -> dict:
    """Return the promoted annual metrics for one company and scope, one entry per fiscal year end."""
    rows = db.execute(
        "SELECT period_end, metric, value, basis, report_id FROM financial_metrics "
        "WHERE company_id = ? AND scope = ? AND period_type = 'FY' ORDER BY period_end, metric",
        (company_id, scope))
    by_period: dict[str, dict] = defaultdict(lambda: {"metrics": {}, "reports": set(), "basis": set()})
    for r in rows:
        if codes is not None and r["metric"] not in codes:
            continue
        p = by_period[r["period_end"]]
        p["metrics"][r["metric"]] = r["value"]
        p["reports"].add(r["report_id"])
        p["basis"].add(r["basis"])

    periods, conflicts = [], []
    for pe in sorted(by_period):
        p = by_period[pe]
        if len(p["reports"]) > 1:
            conflicts.append({"period_end": pe, "report_ids": sorted(p["reports"]),
                              "note": "more than one promoted report for this period; not selected"})
            continue
        periods.append({"period_end": pe, "report_id": next(iter(p["reports"])),
                        "basis": "restated" if "restated" in p["basis"] else "reported",
                        "metrics": dict(sorted(p["metrics"].items()))})

    gaps = year_gaps(periods)

    not_promoted = [
        {"report_id": r["report_id"], "period_end": r["period_end"], "status": r["extraction_status"]}
        for r in db.execute(
            "SELECT report_id, period_end, extraction_status FROM financial_reports "
            "WHERE company_id = ? AND scope = ? AND doc_type = 'annual' "
            "AND extraction_status <> 'reconciled' "
            "ORDER BY period_end", (company_id, scope))
    ]
    return {"company_id": company_id, "scope": scope, "periods": periods, "gaps": gaps,
            "not_promoted": not_promoted, "conflicts": conflicts}
