"""Safety gate for any test that would execute pending-migration DDL against a Turso database.

Only the dedicated integration-test database (PSXNI_TEST_TURSO_*) can be targeted, never production, and a
configured URL alone never authorises DDL. The separate, explicit variable
PSXNI_TURSO_ALLOW_PENDING_MIGRATION_DDL must equal exactly "yes-execute-migration-ddl", and CI never
sets it. Even then the DDL runs only inside a batch that is always rolled back.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

OPT_IN_VAR = "PSXNI_TURSO_ALLOW_PENDING_MIGRATION_DDL"
OPT_IN_VALUE = "yes-execute-migration-ddl"


def pending_migration_ddl_permitted(env: Mapping[str, str]) -> bool:
    """Only for the dedicated integration-test database: its gate must pass, and the explicit opt-in
    must be set. Production configuration (PSXNI_TURSO_*) can never authorise DDL."""
    if integration_config_status(env)[0] != "ok":
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


# ------------------------------------------------------------------ integration-test gate (CI isolation)
TEST_URL_VAR = "PSXNI_TEST_TURSO_DATABASE_URL"
TEST_TOKEN_VAR = "PSXNI_TEST_TURSO_AUTH_TOKEN"  # noqa: S105 - a variable name
# The production database. Integration tests must never connect to it, whatever the configuration.
PRODUCTION_HOST = "psx-news-intelligence-imranrazabozdar.aws-us-east-1.turso.io"


def integration_config_status(env: Mapping[str, str]) -> tuple[str, str]:
    """Decide whether the real-Turso integration tests may run: ('skip' | 'fail' | 'ok', reason).

    Only the dedicated PSXNI_TEST_TURSO_* variables can enable them. The production variables
    (PSXNI_TURSO_*) are never used as a fallback; they are read only to refuse a test target that
    matches them. A production target fails closed before any connection is made.
    """
    url = env.get(TEST_URL_VAR, "").strip()
    token = env.get(TEST_TOKEN_VAR, "").strip()
    if not url and not token:
        return "skip", (
            f"{TEST_URL_VAR} / {TEST_TOKEN_VAR} not set: real-Turso integration tests not run "
            "(production credentials are never used for tests)"
        )
    if not (url and token):
        return "fail", f"incomplete configuration: set both {TEST_URL_VAR} and {TEST_TOKEN_VAR}"
    if not url.startswith(("libsql://", "https://")):
        return "fail", "the test database URL must be a libsql:// or https:// Turso URL"
    host = _host(url)
    if not host:
        return "fail", "the test database URL has no host"
    if host == PRODUCTION_HOST or any(m in url.lower() for m in PRODUCTION_MARKERS):
        return "fail", "refusing to run: the integration-test target is the production database"
    prod_url = env.get(PRODUCTION_URL_VAR, "").strip()
    if prod_url and _host(prod_url) == host:
        return "fail", "refusing to run: the integration-test target has the production database host"
    prod_token = env.get(PRODUCTION_TOKEN_VAR, "").strip()
    if prod_token and prod_token == token:
        return "fail", "refusing to run: the integration-test token equals the production token"
    return "ok", ""


# ------------------------------------------------------------------ suite-level status (offline-safe)
# The disposable integration suite is a named suite. Its status is one of RUN, NOT_RUN or REFUSED, and the
# offline test run never fails because of it.
SUITE_NOT_RUN_MESSAGE = "DISPOSABLE_INTEGRATION_SUITE: NOT_RUN (No disposable credentials set)"
TARGET_URL_VARS = (
    "PSXNI_TURSO_DISPOSABLE_DATABASE_URL",
    "PSXNI_TEST_TURSO_DATABASE_URL",
    "TURSO_DATABASE_URL",
)
_DISPOSABLE_NAME = re.compile(r"(?<![a-z0-9])(?:test|disposable)(?![a-z0-9])")
_FORBIDDEN_NAME = re.compile(r"(?<![a-z0-9])(?:prod|production|operational|technical|news)(?![a-z0-9])")


def disposable_suite_status(env: Mapping[str, str]) -> tuple[str, str]:
    """('RUN' | 'NOT_RUN' | 'REFUSED', message).

    RUN only when a target URL explicitly names itself a test or disposable database (as a whole word) and
    names no
    production, operational, technical or news database, and does not point at the production host. Nothing
    set
    gives NOT_RUN with SUITE_NOT_RUN_MESSAGE. An ambiguous or unsafe target is REFUSED, never run. This
    never reads
    a production credential to connect; it only refuses."""
    urls = [(v, env.get(v, "").strip()) for v in TARGET_URL_VARS if env.get(v, "").strip()]
    if not urls:
        return "NOT_RUN", SUITE_NOT_RUN_MESSAGE
    for var, url in urls:
        name = _host(url) + " " + url.lower()
        if _FORBIDDEN_NAME.search(name):
            return "REFUSED", f"{var} names a production/operational/technical/news database: refused"
        if not _DISPOSABLE_NAME.search(name):
            return "REFUSED", f"{var} does not explicitly name a test or disposable database: refused"
        prod = env.get(PRODUCTION_URL_VAR, "").strip()
        if prod and _host(prod) == _host(url):
            return "REFUSED", f"{var} points at the production database host: refused"
    return "RUN", "disposable target explicitly named and accepted"
