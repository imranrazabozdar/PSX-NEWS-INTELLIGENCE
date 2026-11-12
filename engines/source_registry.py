"""Owner-configured source registry (config/sources_registry.json). Fails closed.

Automated retrieval is allowed for an entry only when ALL hold:
  * permission_status == "permitted" (the owner's written permission or licence is recorded),
  * enabled is true,
  * url_pattern is set.
Any other combination, including an unknown status, blocks automated retrieval. Manual PDF upload (the
vault intake
in engines/document_intake.py) needs no registry entry and is always available.

The file never holds a credential. auth_env_var names an environment variable, and the value is read at
run time.
A URL containing user information (user:password@) is refused at load.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "sources_registry.json"
PERMISSION_STATUSES = ("permitted", "pending", "restricted", "manual_only", "not_requested")
CATEGORIES = ("annual_report", "half_yearly_report", "quarterly_report", "nine_month_report", "other")
_ENV_NAME = re.compile(r"^PSXNI_[A-Z0-9_]+$")
_SYMBOL = re.compile(r"^[A-Z0-9]{1,12}$")
_USERINFO = re.compile(r"^[a-z]+://[^/@\s]+@", re.IGNORECASE)


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    source_id: str
    symbol: str
    company: str
    category: str
    financial_year: int | None
    url_pattern: str | None
    permission_status: str
    auth_env_var: str | None
    enabled: bool
    notes: str

    @property
    def automated_fetch_allowed(self) -> bool:
        return self.permission_status == "permitted" and self.enabled and bool(self.url_pattern)


def _check(e: dict, i: int) -> Source:
    def fail(msg: str):
        raise RegistryError(f"entry {i} ({e.get('source_id', '?')}): {msg}")

    for k in ("source_id", "symbol", "company", "category", "permission_status", "enabled"):
        if k not in e:
            fail(f"missing {k}")
    if not re.fullmatch(r"[a-z0-9_]{1,40}", str(e["source_id"])):
        fail("source_id must be lower-case letters, digits and underscores")
    if not _SYMBOL.fullmatch(str(e["symbol"])):
        fail("symbol must be an upper-case PSX symbol")
    if e["category"] not in CATEGORIES:
        fail(f"category must be one of {CATEGORIES}")
    if e["permission_status"] not in PERMISSION_STATUSES:
        fail(f"permission_status must be one of {PERMISSION_STATUSES}")
    if not isinstance(e["enabled"], bool):
        fail("enabled must be true or false")
    url = e.get("url_pattern")
    if url is not None:
        if not str(url).startswith(("https://", "http://")):
            fail("url_pattern must be an http(s) URL or pattern")
        if _USERINFO.match(str(url)):
            fail("url_pattern must not contain credentials")
    env = e.get("auth_env_var")
    if env is not None and not _ENV_NAME.fullmatch(str(env)):
        fail("auth_env_var must name a PSXNI_ environment variable, never a value")
    fy = e.get("financial_year")
    if fy is not None and not (isinstance(fy, int) and 1990 <= fy <= 2100):
        fail("financial_year must be an integer year or null")
    return Source(
        str(e["source_id"]),
        str(e["symbol"]),
        str(e["company"]),
        str(e["category"]),
        fy,
        url,
        str(e["permission_status"]),
        env,
        e["enabled"],
        str(e.get("notes", "")),
    )


def load(path: Path | str = REGISTRY_PATH) -> list[Source]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise RegistryError("unsupported registry version")
    sources = [_check(e, i) for i, e in enumerate(data.get("sources", []))]
    ids = [s.source_id for s in sources]
    if len(ids) != len(set(ids)):
        raise RegistryError("duplicate source_id")
    return sources


def automated_allowed(
    sources: list[Source], *, symbol: str, category: str, financial_year: int | None
) -> list[Source]:
    """Entries that may be fetched automatically for this document.

    An empty list means manual upload only."""
    return [
        s
        for s in sources
        if s.symbol == symbol
        and s.category == category
        and (s.financial_year is None or s.financial_year == financial_year)
        and s.automated_fetch_allowed
    ]
