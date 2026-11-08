"""Historical validation infrastructure (master plan M7; MASTER_VALIDATION_STRATEGY.md §3).

* `record_validation_run` stores a measurement with its engine versions, label count and data kind
  ('human_labelled', 'synthetic_test' or 'real_market'). Synthetic test runs can never be stored as
  human-labelled accuracy, and a labelled-accuracy run with fewer than MIN_LABELS labels stores no score.
* `walk_forward` builds fixed, non-overlapping train/test windows in time order (no tuning on test data).
* `point_in_time` keeps only rows available before the decision time; `assert_no_lookahead` fails loudly.
* `event_study` measures abnormal returns (stock minus benchmark) around an event date. It needs an approved
  benchmark series (U5). Without one it returns `not_evaluable`; a raw price move is never treated as proof.
* `evaluate_predictions` scores tracked X predictions against later benchmark-relative moves, under the same
  benchmark requirement.
Delisted companies stay in the universe (company_status_history), so evaluations do not drop failures.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from engines.validation import MIN_LABELS

SOURCE_ID = "scs_chart"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_validation_run(db, *, kind: str, data_kind: str, result: dict, engine_versions: dict,
                          label_version: str | None = None) -> int:
    n = int(result.get("n", 0))
    metrics = result.get("metrics", [])
    status = result.get("status", "recorded")
    if kind == "labelled_accuracy":
        if data_kind != "human_labelled":
            raise ValueError("labelled accuracy must come from human labels")
        if n < MIN_LABELS:
            metrics, status = [], "insufficient_labelled_data"
    db.execute(
        "INSERT INTO validation_runs(kind, engine_versions_json, label_version, label_count, data_kind, "
        "status, "
        "metrics_json, created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
        (kind, json.dumps(engine_versions), label_version, n, data_kind, status,
         json.dumps({"metrics": metrics, "false_positives": result.get("false_positives", []),
                     "false_negatives": result.get("false_negatives", [])}), _now()))
    return db.execute("SELECT MAX(run_id) AS r FROM validation_runs")[0]["r"]


def walk_forward(dates: list[str], *, train: int, test: int, step: int | None = None) -> list[dict]:
    d = sorted(set(dates))
    step = step or test
    out, i = [], 0
    while i + train + test <= len(d):
        out.append({"train": d[i:i + train], "test": d[i + train:i + train + test]})
        i += step
    return out


def point_in_time(rows: list[dict], decision_time: str, *, key: str) -> list[dict]:
    return [r for r in rows if r.get(key) is not None and r[key] < decision_time]


def assert_no_lookahead(rows: list[dict], decision_time: str, *, key: str) -> None:
    late = [r for r in rows if r.get(key) is None or r[key] >= decision_time]
    if late:
        raise AssertionError(f"{len(late)} rows not available before {decision_time} (key {key})")


def _closes(db, symbol: str) -> dict[str, float]:
    return {r["session_date_pkt"]: r["close"] for r in db.execute(
        "SELECT session_date_pkt, close FROM market_bars_current WHERE source_id = ? AND symbol = ? AND "
        "timeframe = '1d'", (SOURCE_ID, symbol))}


def event_study(db, symbol: str, event_date: str, *, benchmark: str | None, pre: int = 1,
                post: int = 5) -> dict:
    """Cumulative abnormal return from `pre` sessions before to `post` sessions after the event date."""
    if not benchmark:
        return {"state": "not_evaluable", "reason": "no approved benchmark series (U5)"}
    s, b = _closes(db, symbol), _closes(db, benchmark)
    common = sorted(set(s) & set(b))
    before = [d for d in common if d < event_date]
    after = [d for d in common if d >= event_date]
    if len(before) < pre or len(after) < post:
        return {"state": "insufficient_data", "sessions_before": len(before), "sessions_after": len(after)}
    d0, d1 = before[-pre], after[post - 1]
    rs, rb = s[d1] / s[d0] - 1, b[d1] / b[d0] - 1
    return {"state": "ok", "start": d0, "end": d1, "stock_return": rs, "benchmark_return": rb,
            "abnormal_return": rs - rb,
            "note": "abnormal return over the window; one event is not proof of an effect"}


def evaluate_predictions(db, *, benchmark: str | None, horizon_days: int = 30) -> dict:
    preds = db.execute(
        "SELECT p.prediction_id, p.direction, p.prediction_date, p.company_id, ci.value AS symbol "
        "FROM media_predictions p LEFT JOIN company_identifiers ci ON ci.company_id = p.company_id "
        "AND ci.id_type = 'psx_ticker' AND ci.valid_to IS NULL")
    if not benchmark:
        return {"state": "not_evaluable", "reason": "no approved benchmark series (U5)",
                "predictions": len(preds)}
    results = []
    for p in preds:
        if not p["symbol"] or p["direction"] not in ("positive", "negative"):
            results.append({"prediction_id": p["prediction_id"], "state": "not_evaluable",
                            "reason": "no company or no directional claim"})
            continue
        end = (date.fromisoformat(p["prediction_date"]) + timedelta(days=horizon_days)).isoformat()
        es = event_study(db, p["symbol"], p["prediction_date"], benchmark=benchmark, pre=1,
                         post=max(1, horizon_days * 5 // 7))
        if es["state"] != "ok":
            results.append({"prediction_id": p["prediction_id"], **es})
            continue
        hit = (es["abnormal_return"] > 0) == (p["direction"] == "positive")
        results.append({"prediction_id": p["prediction_id"], "state": "evaluated", "hit": hit, "until": end,
                        "abnormal_return": es["abnormal_return"]})
    scored = [r for r in results if r["state"] == "evaluated"]
    return {"state": "evaluated" if scored else "insufficient_data", "n": len(scored),
            "hit_rate": (sum(r["hit"] for r in scored) / len(scored)) if len(scored) >= MIN_LABELS else None,
            "min_required": MIN_LABELS, "results": results}


def export_label_template(db, *, limit: int = 50) -> dict:
    """Recent headlines as an EMPTY labelling template; a person fills `expected` and `labeller`."""
    rows = db.execute(
        "SELECT si.source_item_id, si.title, si.published_at_utc, si.canonical_url FROM source_items si "
        "WHERE si.title IS NOT NULL AND si.published_at_utc IS NOT NULL ORDER BY si.published_at_utc DESC "
        "LIMIT ?",
        (limit,))
    from urllib.parse import urlsplit

    return {"version": 1, "instructions": "Fill expected (primary_type, companies, independence, exposed, "
            "impacts) from the headline and independent sources; set labeller. Leave out keys you cannot "
            "judge. Never copy engine output as a label.",
            "items": [{"id": f"si-{r['source_item_id']}", "headline": r["title"],
                       "published_at_utc": r["published_at_utc"],
                       "publisher_domain": urlsplit(r["canonical_url"] or "").hostname or "",
                       "labeller": "", "expected": {}} for r in rows]}
