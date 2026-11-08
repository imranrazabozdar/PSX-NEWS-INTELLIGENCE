"""Macro and commodity series (master plan M6): registry, manual import with vintages, point-in-time reads.

* Definitions come from config/macro_series.json; no values are seeded.
* Values enter only by owner-attested manual import of an official release (`import_observations`), each
  with its release date. A second value for the same reference period is a NEW vintage, never an overwrite.
* `as_known_at` returns what was known on a date (latest vintage released on or before it), so backtests and
  reports never see later revisions.
* `driver_changes` gives, for a T1-T9 mechanism, the sourced change in each linked series between two
  dates, the "sourced driver change" the impact framework requires before a magnitude can be discussed.
Automated EIA / World Bank collection is BLOCKED (owner decision U2); SBP automation is blocked (403, R3).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

from database import repositories as repo

REGISTRY = Path(__file__).resolve().parents[1] / "config" / "macro_series.json"
_PERIOD = {
    "daily": r"\d{4}-\d\d-\d\d", "weekly": r"\d{4}-\d\d-\d\d", "irregular": r"\d{4}-\d\d-\d\d",
    "monthly": r"\d{4}-\d\d", "quarterly": r"\d{4}-Q[1-4]", "annual": r"\d{4}",
}


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_registry(db, path: Path | str = REGISTRY) -> int:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    n = 0
    for s in raw["series"]:
        if not db.execute("SELECT 1 FROM macro_series WHERE series_code = ?", (s["series_code"],)):
            db.execute(
                "INSERT INTO macro_series(series_code, name, unit, frequency, source_id, mechanisms, "
                "definition, "
                "access_state, created_at_utc) VALUES (?,?,?,?,?,?,?,'manual_import',?)",
                (s["series_code"], s["name"], s["unit"], s["frequency"], s["source_id"],
                 json.dumps(s["mechanisms"]), s["definition"], _now()))
            n += 1
    return n


def import_observations(db, series_code: str, rows: list[dict], *, importer: str, release_url: str | None,
                        release_title: str, rights_attestation: str) -> dict:
    """rows: [{reference_period, value, release_date}]. Idempotent: an identical value is not re-added."""
    if not importer.strip() or not rights_attestation.strip():
        raise ValueError("importer and rights_attestation are required")
    s = db.execute("SELECT * FROM macro_series WHERE series_code = ?", (series_code,))
    if not s:
        raise ValueError(f"unknown series {series_code!r}")
    pat = _PERIOD[s[0]["frequency"]]
    item = repo.record_source_item(
        db, source_id=s[0]["source_id"], collected_at_utc=_now(), url=release_url,
        external_id=f"macro:{series_code}:{release_title}", content=json.dumps(rows, sort_keys=True),
        title=release_title, provenance={"retrieval_method": "manual", "source_metadata_json": json.dumps(
            {"importer": importer, "rights_attestation": rights_attestation})})
    added, unchanged, rejected = [], [], []
    for r in rows:
        try:
            if not re.fullmatch(pat, str(r["reference_period"])):
                raise ValueError(f"reference_period must match {pat}")
            date.fromisoformat(r["release_date"])
            v = float(r["value"])
        except (KeyError, TypeError, ValueError) as exc:
            rejected.append({"row": r, "reason": str(exc)})
            continue
        prev = db.execute("SELECT value, vintage FROM macro_observations WHERE series_code = ? AND "
                          "reference_period = ? ORDER BY vintage DESC LIMIT 1",
                          (series_code, r["reference_period"]))
        if prev and prev[0]["value"] == v:
            unchanged.append(r["reference_period"])
            continue
        vintage = prev[0]["vintage"] + 1 if prev else 1
        db.execute("INSERT INTO macro_observations(series_code, reference_period, value, release_date, "
                   "vintage, "
                   "source_item_id, recorded_at_utc) VALUES (?,?,?,?,?,?,?)",
                   (series_code, r["reference_period"], v, r["release_date"], vintage,
                    item.source_item_id, _now()))
        added.append({"reference_period": r["reference_period"], "vintage": vintage})
    return {"added": added, "unchanged": unchanged, "rejected": rejected,
            "source_item_id": item.source_item_id}


def as_known_at(db, series_code: str, known_at: str, *, reference_period: str | None = None) -> dict | None:
    """Latest observation (by reference period, then vintage) released on or before `known_at`."""
    rows = db.execute(
        "SELECT reference_period, value, release_date, vintage, source_item_id FROM macro_observations "
        "WHERE series_code = ? AND release_date <= ? AND (? IS NULL OR reference_period = ?) "
        "ORDER BY reference_period DESC, vintage DESC LIMIT 1",
        (series_code, known_at, reference_period, reference_period))
    return dict(rows[0]) if rows else None


def driver_changes(db, mechanism: str, *, start: str, end: str) -> list[dict]:
    """Sourced change, as known at each date, for every series linked to a T-mechanism."""
    out = []
    for s in db.execute("SELECT series_code, name, unit, mechanisms FROM macro_series ORDER BY series_code"):
        if mechanism not in json.loads(s["mechanisms"]):
            continue
        a, b = as_known_at(db, s["series_code"], start), as_known_at(db, s["series_code"], end)
        row = {"series_code": s["series_code"], "name": s["name"], "unit": s["unit"], "start": a, "end": b}
        if a is None or b is None:
            row.update(state="data_unavailable", change=None)
        elif a["reference_period"] == b["reference_period"] and a["vintage"] == b["vintage"]:
            row.update(state="no_new_observation", change=None)
        else:
            row.update(state="ok", change=b["value"] - a["value"],
                       pct_change=(b["value"] / a["value"] - 1) if a["value"] else None)
        out.append(row)
    return out
