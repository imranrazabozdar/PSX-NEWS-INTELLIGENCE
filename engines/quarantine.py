"""Quarantine for extraction records that did not originate in this project's pipeline.

Legacy records were written before database separation by a different codebase, with other schema
versions (for example `event_candidate/1`). They are unreviewed and unverified. This module:

* classifies every extraction record by its schema version against an explicit allow-list of this
  project's own schema versions (fail closed: anything not listed is quarantined);
* reports counts without changing a single record. It never updates, deletes, approves or rejects;
* gives scoring code one place to ask whether a record may be used.

Records are append-only (database triggers block updates and deletes), so quarantine is enforced at
read time, not by editing rows.
"""

from __future__ import annotations

from typing import Any

# This project's own extraction schema versions. Keep in step with the modules that write them
# (engines/event_intel.py, engines/schema.py, engines/headline_events.py). Tests check this.
NEWS_SCHEMA_VERSIONS: frozenset[str] = frozenset({"event-intel/1", "event-extraction/1", "headline-event/1"})

ELIGIBLE = "eligible_project_schema"
QUARANTINED = "quarantined_unknown_or_legacy"


def classify(schema_version: str | None) -> str:
    """ELIGIBLE only for an exact project schema version. Empty, missing or unknown means quarantined."""
    if schema_version and schema_version in NEWS_SCHEMA_VERSIONS:
        return ELIGIBLE
    return QUARANTINED


def sql_eligible_filter(column: str = "schema_version") -> str:
    """SQL fragment that keeps only eligible rows. Values come from the constant above, never from input."""
    quoted = ", ".join("'" + v.replace("'", "''") + "'" for v in sorted(NEWS_SCHEMA_VERSIONS))
    return f"{column} IN ({quoted})"


def report(db: Any) -> dict[str, Any]:
    """Read-only inventory of extraction records by schema version and classification."""
    rows = db.execute("SELECT schema_version, COUNT(*) AS n, COUNT(DISTINCT event_id) AS events "
                      "FROM event_extractions GROUP BY schema_version ORDER BY schema_version")
    by_schema: dict[str, dict[str, Any]] = {}
    totals = {ELIGIBLE: 0, QUARANTINED: 0}
    for r in rows:
        sv = r["schema_version"]
        status = classify(sv)
        by_schema[sv] = {"records": int(r["n"]), "events": int(r["events"]), "status": status}
        totals[status] += int(r["n"])
    return {"by_schema": by_schema, "totals": totals,
            "changed_records": 0,  # by construction: this function only reads
            "note": "legacy records are quarantined at read time and are never modified"}


def is_eligible(schema_version: str | None) -> bool:
    return classify(schema_version) == ELIGIBLE
