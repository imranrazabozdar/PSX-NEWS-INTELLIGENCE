"""Company view and descriptive screening signals, from STORED Investify data only (local, private).

Reads only. Nothing here fetches, writes, or publishes. The data is Investify's (investify.pk); every view
carries the attribution. Signals describe a company's state against owner-visible thresholds
(config/screening_thresholds.json). They are not buy or sell rules and never use directive language.

A dataset that is not stored is reported as NOT YET COLLECTED. No number is filled in for it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ATTRIBUTION = "Data: investify.pk (private research use)"
SOURCE = "investify.pk"
SOURCE_ID = "investify_fundamentals"
THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "config" / "screening_thresholds.json"
NOT_COLLECTED = "not yet collected"
DATASETS = ("profile", "fundamentals", "competitors", "announcements")

# Groups as Investify shows them. The first matching keyword wins, in this order.
GROUP_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("EPS", ("EPS", "Earnings per share")),
    ("P/E", ("P/E", "Price to earnings")),
    ("Growth", ("Growth", "PEG")),
    ("Book & Market Value", ("Book", "Market Cap", "Enterprise Value")),
    ("Profitability", ("Margin", "Return on")),
    ("Financial Health", ("Ratio", "/ Assets", "Debt")),
    ("Dividends", ("Dividend",)),
)
GROUP_ORDER = tuple(g for g, _ in GROUP_RULES) + ("Other",)


def group_for(label: str) -> str:
    for group, keywords in GROUP_RULES:
        if any(k in label for k in keywords):
            return group
    return "Other"


def _connect_readonly(path: str | Path) -> sqlite3.Connection:
    text = str(path)
    if "://" in text:
        raise ValueError("refused: a local database file is required, not a URL")
    return sqlite3.connect(f"file:{Path(text).resolve()}?mode=ro", uri=True)


def _newest_record(con: sqlite3.Connection, symbol: str, endpoint: str) -> dict[str, Any] | None:
    """The newest stored record for this company and endpoint, if it carries Investify attribution."""
    row = con.execute(
        "SELECT source_metadata_json FROM source_items WHERE source_id = ? "
        "AND (external_id = ? OR external_id LIKE ?) ORDER BY collected_at_utc DESC LIMIT 1",
        (SOURCE_ID, f"{symbol}:{endpoint}", f"{symbol}:{endpoint}:%")).fetchone()
    if row is None:
        return None
    meta = json.loads(row[0])
    if meta.get("source") != SOURCE:
        return None  # not Investify-attributed: never shown
    return {"fields": meta.get("fields") or {}, "fetched_at_utc": meta.get("fetched_at_utc"),
            "triggering_announcement_id": meta.get("triggering_announcement_id"),
            "attribution": meta.get("attribution")}


def company_symbols(path: str | Path) -> list[str]:
    con = _connect_readonly(path)
    try:
        rows = con.execute(
            "SELECT DISTINCT substr(external_id, 1, instr(external_id, ':') - 1) FROM source_items "
            "WHERE source_id = ? AND external_id LIKE '%:%'", (SOURCE_ID,)).fetchall()
    finally:
        con.close()
    return sorted({r[0] for r in rows if r[0]})


def load_company(path: str | Path, symbol: str) -> dict[str, dict[str, Any] | None]:
    """Each dataset, or None where it has not been collected. Read-only."""
    con = _connect_readonly(path)
    try:
        return {ep: _newest_record(con, symbol, ep) for ep in DATASETS}
    finally:
        con.close()


def grouped_metrics(fundamentals: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUP_ORDER}
    for m in fundamentals.get("metrics", []):
        out[group_for(m["label"])].append({
            "label": m["label"], "value_text": m["value"]["text"], "value": m["value"].get("value"),
            "unit": m["value"].get("unit"), "period_basis": m["period_basis"],
            "sentiment": m.get("sentiment"), "description": m.get("description"),
        })
    return {g: rows for g, rows in out.items() if rows}


def load_rules(path: Path = THRESHOLDS_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))["rules"]


_OPS = {"<": lambda a, b: a < b, ">": lambda a, b: a > b}


def screening_signals(metrics: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each rule, evaluated against the stored metrics. A rule whose metric is not stored says so; it never
    produces a value. Every result shows the criterion and the observed value, never an action."""
    by_label = {m["label"]: m for m in metrics}
    results = []
    for rule in rules:
        criterion = f"{' or '.join(rule['metrics'])} {rule['op']} {rule['threshold']}"
        present = next((by_label[name] for name in rule["metrics"] if name in by_label), None)
        if present is None or present.get("value") is None:
            results.append({"id": rule["id"], "label": rule["label"], "criterion": criterion,
                            "status": NOT_COLLECTED, "observed": None, "period_basis": None,
                            "met": None})
            continue
        met = _OPS[rule["op"]](present["value"], rule["threshold"])
        results.append({"id": rule["id"], "label": rule["label"], "criterion": criterion,
                        "status": "evaluated", "observed": present["value_text"],
                        "period_basis": present["period_basis"], "met": met})
    return results
