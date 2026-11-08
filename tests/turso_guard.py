"""Safety gate for any test that would execute pending-migration DDL against a Turso database.

A configured PSXNI_TURSO_DATABASE_URL alone never authorises DDL. The separate, explicit variable
PSXNI_TURSO_ALLOW_PENDING_MIGRATION_DDL must equal exactly "yes-execute-migration-ddl", and CI never
sets it. Even then the DDL runs only inside a batch that is always rolled back.
"""

from __future__ import annotations

from collections.abc import Mapping

OPT_IN_VAR = "PSXNI_TURSO_ALLOW_PENDING_MIGRATION_DDL"
OPT_IN_VALUE = "yes-execute-migration-ddl"


def pending_migration_ddl_permitted(env: Mapping[str, str]) -> bool:
    url = env.get("PSXNI_TURSO_DATABASE_URL", "")
    if not url.startswith(("libsql://", "https://")):
        return False
    return env.get(OPT_IN_VAR, "") == OPT_IN_VALUE


# ------------------------------------------------------------------ disposable-database gate (gate 3)
DISPOSABLE_URL_VAR = "PSXNI_TURSO_DISPOSABLE_DATABASE_URL"
DISPOSABLE_TOKEN_VAR = "PSXNI_TURSO_DISPOSABLE_AUTH_TOKEN"  # noqa: S105 - a variable name
PRODUCTION_URL_VAR = "PSXNI_TURSO_DATABASE_URL"
PRODUCTION_TOKEN_VAR = "PSXNI_TURSO_AUTH_TOKEN"  # noqa: S105 - a variable name
PRODUCTION_MARKERS = ("psx-news-intelligence-imranrazabozdar",)


def _host(url: str) -> str:
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0].split("?", 1)[0].lower().rstrip(".")


def disposable_config_status(env: Mapping[str, str]) -> tuple[str, str]:
    """Decide whether the disposable-Turso tests may run: ('skip' | 'fail' | 'ok', reason).

    Nothing configured -> skip. Incomplete or unsafe configuration -> fail (never a silent fallback). The
    production variables are only read to refuse a disposable URL or token that matches them; they are never
    used to connect.
    """
    url = env.get(DISPOSABLE_URL_VAR, "").strip()
    token = env.get(DISPOSABLE_TOKEN_VAR, "").strip()
    if not url and not token:
        return "skip", "disposable Turso database not configured: gate 3 not run"
    if not (url and token):
        return "fail", f"incomplete configuration: set both {DISPOSABLE_URL_VAR} and {DISPOSABLE_TOKEN_VAR}"
    if not url.startswith(("libsql://", "https://")):
        return "fail", "the disposable URL must be a libsql:// or https:// Turso URL"
    host = _host(url)
    if not host:
        return "fail", "the disposable URL has no host"
    if any(m in url.lower() for m in PRODUCTION_MARKERS):
        return "fail", "refusing to run: the disposable URL looks like the production database"
    prod_url = env.get(PRODUCTION_URL_VAR, "").strip()
    if prod_url and _host(prod_url) == host:
        return "fail", "refusing to run: the disposable URL points at the production database host"
    prod_token = env.get(PRODUCTION_TOKEN_VAR, "").strip()
    if prod_token and prod_token == token:
        return "fail", "refusing to run: the disposable token equals the production token"
    return "ok", ""
