"""Unified history access for analysis engines (ratio, valuation, announcement context).

One entry point returns multi-period annual history with its SOURCE stated, so no caller can mistake a
fallback
for archive depth:

* "archive": the archive database holds promoted or summarised history for this company and scope;
* "main_fallback": the archive has no periods, so the operational database's promoted metrics are used;
* "none": neither database holds history.

Both sources contain only reconciled values. The archive is always tried first when a handle is supplied.
"""

from __future__ import annotations

from database import financial_repo as repo
from engines import financial_series as fs


def load_history(main_db, archive_db, company_id: str, *, scope: str,
                 codes: tuple[str, ...] | None = None) -> dict:
    if archive_db is not None:
        series = repo.annual_series(archive_db, company_id, scope=scope, metrics=codes)
        if series["periods"] or series["conflicts"]:
            return {"source": "archive", **series}
    if main_db is not None:
        series = fs.annual_series(main_db, company_id, scope=scope, codes=codes)
        if series["periods"] or series["conflicts"]:
            return {"source": "main_fallback", **series}
        return {"source": "none", **series}
    return {"source": "none", "company_id": company_id, "scope": scope, "periods": [], "gaps": [],
            "conflicts": [], "not_promoted": []}
