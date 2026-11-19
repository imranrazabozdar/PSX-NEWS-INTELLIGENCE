"""Read-only view of the prospective performance tracker's results file (data branch). No writes, no model.

The file is produced by the setups forward-tracking workflow and published to the dedicated data branch. A
private repository needs a credential to read it: a fine-grained, read-only Contents token for this one
repository, kept ONLY in the hosting app's secrets (PSXNI_TRACKER_READ_TOKEN). It is never shown, logged or
put in an error message. Note: such a token can read the whole repository's contents, not only this branch.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

TOKEN_VAR = "PSXNI_TRACKER_READ_TOKEN"  # noqa: S105 - the name of a secret, not a secret
REPO_VAR = "PSXNI_TRACKER_REPO"
DEFAULT_REPO = "imranrazabozdar/PSX-NEWS-INTELLIGENCE"
BRANCH = "data/setups-forward"
PATH = "results.json"
SUPPORTED_SCHEMA = 1
ENOUGH = 20  # snapshots needed before a reading means anything
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TrackerError(RuntimeError):
    """Never carries the token."""


def _get(url: str, headers: dict[str, str]) -> str:
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 - fixed https API host
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


def fetch(
    token: str, repo: str = DEFAULT_REPO, get: Callable[[str, dict[str, str]], str] = _get
) -> dict[str, Any]:
    if not token:
        raise TrackerError(f"the tracker is not configured (set {TOKEN_VAR} in the app's secrets)")
    url = f"https://api.github.com/repos/{repo}/contents/{PATH}?ref={BRANCH}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "psxni-dashboard",
    }
    try:
        return validate(json.loads(get(url, headers)))
    except urllib.error.HTTPError as exc:
        raise TrackerError(f"the results file could not be read (HTTP {exc.code})") from None
    except (urllib.error.URLError, TimeoutError):
        raise TrackerError("the results file could not be reached") from None
    except json.JSONDecodeError:
        raise TrackerError("the results file is not valid JSON") from None


def validate(p: Any) -> dict[str, Any]:
    """Refuse anything that is not the expected, versioned shape rather than showing it."""
    if not isinstance(p, dict) or p.get("schema_version") != SUPPORTED_SCHEMA:
        raise TrackerError(f"unsupported results schema (expected version {SUPPORTED_SCHEMA})")
    for key in ("method", "generated_utc", "snapshots", "summary", "snapshot_days"):
        if key not in p:
            raise TrackerError(f"results file is missing '{key}'")
    if not isinstance(p["snapshots"], int) or not isinstance(p["summary"], list):
        raise TrackerError("results file has the wrong types")
    days = p["snapshot_days"]
    if not all(isinstance(d, str) and _DAY.match(d) for d in days) or len(set(days)) != len(days):
        raise TrackerError("results file has malformed or duplicate snapshot days")
    for row in p["summary"]:
        if not {"track", "horizon", "snapshots_scored"} <= set(row):
            raise TrackerError("a summary row is incomplete")
    return p


def reading(row: dict[str, Any]) -> str:
    n = row["snapshots_scored"]
    if n < ENOUGH:
        return f"too few snapshots to say ({n} of {ENOUGH} needed)"
    ex = row.get("avg_excess")
    if ex is None:
        return "no result yet"
    return "ahead of the group on average" if ex > 0 else "behind the group on average"


def table(p: dict[str, Any]) -> list[dict[str, Any]]:
    def pct(x: Any) -> Any:
        return None if x is None else round(x, 2)

    return [
        {
            "Ranking": r["track"],
            "Sessions ahead": r["horizon"],
            "Snapshots scored": r["snapshots_scored"],
            "Top-10 avg %": pct(r.get("top_avg")),
            "Group avg %": pct(r.get("group_avg")),
            "Excess (pp)": pct(r.get("avg_excess")),
            "Beat the group": None if r.get("beat_rate") is None else f"{100 * r['beat_rate']:.0f}%",
            "Reading": reading(r),
        }
        for r in p["summary"]
    ]
