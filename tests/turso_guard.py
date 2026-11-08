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
