"""Historical validation and calibration against HUMAN labels (Stage 2, final batch).

Ground truth is only data/validation/labels.json, written by people from the headline and independent
sources. The engine's own outputs are never ground truth. The harness runs the deterministic pipeline
(headline builder -> event intel -> exposure/impact) on the labelled headlines in an isolated in-memory SQLite
database, never on a configured database, and compares the results with the labels.

* A metric is reported only with at least MIN_LABELS labelled cases; otherwise it reports
  insufficient_labelled_data with its count, and NO score.
* False positives and false negatives are listed per item, with the reason, whatever the sample size.
* Confidence calibration needs MIN_LABELS cases per confidence level.
* Market-outcome checks: a later share-price move alone does not prove an assessment. They need a market
  benchmark series (KSE-100) to control for market moves. The project stores none, so they are not_evaluable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from database.connection import SQLiteDatabase
from database.migrate import migrate
from database.seed_loader import load

LABELS_PATH = Path(__file__).resolve().parents[1] / "data" / "validation" / "labels.json"
MIN_LABELS = 30
EXPECTED_KEYS = {"primary_type", "companies", "independence", "exposed", "impacts"}


class LabelError(ValueError):
    pass


def load_labels(path: Path | str = LABELS_PATH) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    items = raw.get("items", [])
    seen = set()
    for it in items:
        for k in ("id", "headline", "published_at_utc", "publisher_domain", "labeller", "expected"):
            if not it.get(k):
                raise LabelError(f"label {it.get('id')!r}: missing '{k}'")
        if it["id"] in seen:
            raise LabelError(f"duplicate label id {it['id']!r}")
        seen.add(it["id"])
        bad = set(it["expected"]) - EXPECTED_KEYS
        if bad:
            raise LabelError(f"label {it['id']}: unknown expected keys {sorted(bad)}")
    return raw


def _run_isolated(items: list[dict]) -> tuple[SQLiteDatabase, dict[str, int]]:
    from engines import event_intel as ei
    from engines import headline_events as hb
    from engines import impact_intel as ii

    db = SQLiteDatabase()  # isolated, in memory: validation never touches a configured database
    migrate(db)
    load(db)
    ids: dict[str, int] = {}
    for it in sorted(items, key=lambda x: x["published_at_utc"]):
        sid = "val_" + hashlib.sha256(it["publisher_domain"].encode()).hexdigest()[:8]
        if not db.execute("SELECT 1 FROM sources WHERE source_id = ?", (sid,)):
            db.execute(
                "INSERT INTO sources(source_id, name, source_type, reliability_tier, is_synthetic, "
                "created_at_utc, updated_at_utc) VALUES (?,?,?,?,1,?,?)",
                (
                    sid,
                    f"VALIDATION {it['publisher_domain']}",
                    it.get("source_type", "news_media"),
                    it.get("reliability_tier", "established_media"),
                    it["published_at_utc"],
                    it["published_at_utc"],
                ),
            )
        url = f"https://{it['publisher_domain']}/validation/{it['id']}"
        db.execute(
            "INSERT INTO source_items(source_id, canonical_url, original_url, title, published_at_utc, "
            "publication_time_status, collected_at_utc, content_sha256) VALUES (?,?,?,?,?,'known',?,?)",
            (
                sid,
                url,
                url,
                it["headline"],
                it["published_at_utc"],
                it["published_at_utc"],
                hashlib.sha256(url.encode()).hexdigest(),
            ),
        )
        ids[it["id"]] = db.execute("SELECT MAX(source_item_id) AS i FROM source_items")[0]["i"]
    hb.run(db, limit=10_000)
    ei.run(db, limit=10_000)
    ii.run(db, synthetic=True, limit=10_000)
    return db, ids


def _metric(name: str, correct: int, total: int) -> dict:
    if total < MIN_LABELS:
        return {"metric": name, "status": "insufficient_labelled_data", "n": total, "required": MIN_LABELS}
    return {"metric": name, "status": "measured", "n": total, "value": round(correct / total, 4)}


def evaluate(labels: dict | None = None) -> dict:
    labels = labels if labels is not None else load_labels()
    items = labels.get("items", [])
    if not items:
        return {
            "status": "insufficient_labelled_data",
            "n": 0,
            "required": MIN_LABELS,
            "metrics": [],
            "false_positives": [],
            "false_negatives": [],
            "calibration": {"status": "insufficient_labelled_data"},
            "market_outcomes": market_outcomes(None),
            "note": "No human-labelled samples exist yet; no accuracy can be stated.",
        }
    db, ids = _run_isolated(items)
    fp, fn = [], []
    tallies = {
        k: [0, 0]
        for k in (
            "classification",
            "entity_precision",
            "entity_recall",
            "independence",
            "exposure_precision",
            "exposure_recall",
            "impact_direction",
            "impact_coverage",
        )
    }
    calib: dict[str, list[int]] = {}
    for it in items:
        sid, exp = ids[it["id"]], it["expected"]
        ext = db.execute(
            "SELECT event_id, extracted_json FROM event_extractions WHERE source_item_id = ? "
            "AND schema_version = 'event-intel/1'",
            (sid,),
        )
        rec = json.loads(ext[0]["extracted_json"]) if ext else {}
        event_id = ext[0]["event_id"] if ext else None
        if "primary_type" in exp:
            got = rec.get("classification", {}).get("primary_type", "not processed")
            tallies["classification"][1] += 1
            if got == exp["primary_type"]:
                tallies["classification"][0] += 1
            elif got == "other":
                fn.append(
                    {
                        "label": it["id"],
                        "kind": "classification",
                        "expected": exp["primary_type"],
                        "got": got,
                        "reason": "no rule matched (unclassified)",
                    }
                )
            else:
                fp.append(
                    {
                        "label": it["id"],
                        "kind": "classification",
                        "expected": exp["primary_type"],
                        "got": got,
                        "reason": "a different rule matched first",
                    }
                )
        if "companies" in exp:
            got = {e["company_id"] for e in rec.get("entities", []) if e.get("company_id")}
            want = set(exp["companies"])
            tallies["entity_precision"][0] += len(got & want)
            tallies["entity_precision"][1] += len(got)
            tallies["entity_recall"][0] += len(got & want)
            tallies["entity_recall"][1] += len(want)
            fp += [
                {"label": it["id"], "kind": "entity", "got": c, "reason": "company linked but not labelled"}
                for c in sorted(got - want)
            ]
            fn += [
                {
                    "label": it["id"],
                    "kind": "entity",
                    "expected": c,
                    "reason": "labelled company not linked "
                    "(not in the 51-company master, ambiguous, or not an exact name/ticker)",
                }
                for c in sorted(want - got)
            ]
        if "independence" in exp:
            got = rec.get("evidence", {}).get("independence")
            tallies["independence"][1] += 1
            if got == exp["independence"]:
                tallies["independence"][0] += 1
            else:
                (fp if got == "independent" else fn).append(
                    {
                        "label": it["id"],
                        "kind": "independence",
                        "expected": exp["independence"],
                        "got": got,
                        "reason": "publisher grouping or duplicate detection",
                    }
                )
        cands = (
            {
                r["company_id"]
                for r in db.execute(
                    "SELECT company_id FROM exposure_candidates WHERE event_id = ?", (event_id,)
                )
            }
            if event_id
            else set()
        )
        if "exposed" in exp:
            want = {e["company_id"] for e in exp["exposed"]}
            tallies["exposure_precision"][0] += len(cands & want)
            tallies["exposure_precision"][1] += len(cands)
            tallies["exposure_recall"][0] += len(cands & want)
            tallies["exposure_recall"][1] += len(want)
            fp += [
                {"label": it["id"], "kind": "exposure", "got": c, "reason": "unsupported exposure hypothesis"}
                for c in sorted(cands - want)
            ]
            fn += [
                {
                    "label": it["id"],
                    "kind": "exposure",
                    "expected": c,
                    "reason": "missed affected company (no documented exposure or rule)",
                }
                for c in sorted(want - cands)
            ]
        for imp in exp.get("impacts", []):
            row = (
                db.execute(
                    "SELECT direction, direction_confidence FROM impact_assessments WHERE event_id = ? AND "
                    "company_id = ? AND mechanism_id = ?",
                    (event_id, imp["company_id"], imp["mechanism"]),
                )
                if event_id
                else []
            )
            tallies["impact_coverage"][1] += 1
            if not row:
                fn.append(
                    {
                        "label": it["id"],
                        "kind": "impact",
                        "expected": imp,
                        "reason": "no assessment generated",
                    }
                )
                continue
            tallies["impact_coverage"][0] += 1
            tallies["impact_direction"][1] += 1
            ok = row[0]["direction"] == imp["direction"]
            tallies["impact_direction"][0] += int(ok)
            calib.setdefault(row[0]["direction_confidence"], [0, 0])
            calib[row[0]["direction_confidence"]][0] += int(ok)
            calib[row[0]["direction_confidence"]][1] += 1
            if not ok:
                fp.append(
                    {
                        "label": it["id"],
                        "kind": "impact_direction",
                        "expected": imp,
                        "got": row[0]["direction"],
                        "reason": "direction differs from the label",
                    }
                )
    db.close()
    return {
        "status": "evaluated",
        "n": len(items),
        "metrics": [_metric(k, c, t) for k, (c, t) in tallies.items()],
        "false_positives": fp,
        "false_negatives": fn,
        "calibration": {
            lvl: _metric(f"direction_accuracy_at_{lvl}_confidence", c, t) for lvl, (c, t) in calib.items()
        }
        or {"status": "insufficient_labelled_data"},
        "market_outcomes": market_outcomes(None),
    }


def market_outcomes(db) -> dict:
    """Outcome checks need a benchmark to control for market-wide moves; none is stored."""
    if db is not None and db.execute(
        "SELECT 1 FROM market_bars WHERE symbol IN ('KSE100', 'KSE-100') LIMIT 1"
    ):
        reason = "benchmark present, but the event-study method needs labelled impacts first (see MIN_LABELS)"
    else:
        reason = (
            "no market benchmark (KSE-100) is stored, so market and sector moves cannot be separated from "
            "an event's effect; a later share-price move alone is not proof"
        )
    return {"status": "not_evaluable", "reason": reason}
