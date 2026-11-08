"""The pending-migration DDL gate: a Turso URL alone never authorises executing migration DDL."""

from __future__ import annotations

from tests.turso_guard import OPT_IN_VALUE, OPT_IN_VAR, pending_migration_ddl_permitted

URL = "libsql://example-disposable.turso.io"


def test_url_alone_is_insufficient():
    assert not pending_migration_ddl_permitted({"PSXNI_TURSO_DATABASE_URL": URL})


def test_url_plus_unrelated_configuration_is_insufficient():
    env = {"PSXNI_TURSO_DATABASE_URL": URL, "PSXNI_TURSO_AUTH_TOKEN": "x", "PSXNI_LIVE_SOURCE_TESTS": "1",
           OPT_IN_VAR: "1", "PSXNI_KILL_SWITCH": "0"}
    assert not pending_migration_ddl_permitted(env)   # "1" is not the explicit value
    env[OPT_IN_VAR] = "true"
    assert not pending_migration_ddl_permitted(env)


def test_explicit_opt_in_with_url_is_required():
    assert pending_migration_ddl_permitted({"PSXNI_TURSO_DATABASE_URL": URL, OPT_IN_VAR: OPT_IN_VALUE})
    assert not pending_migration_ddl_permitted({OPT_IN_VAR: OPT_IN_VALUE})            # no URL
    assert not pending_migration_ddl_permitted({"PSXNI_TURSO_DATABASE_URL": "sqlite://:memory:",
                                                OPT_IN_VAR: OPT_IN_VALUE})            # not Turso


def test_ci_workflow_never_sets_the_opt_in():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for wf in (root / ".github" / "workflows").glob("*.yml"):
        assert OPT_IN_VAR not in wf.read_text(encoding="utf-8"), wf.name
