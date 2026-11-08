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


# ------------------------------------------------------------------ disposable-database gate
from tests.turso_guard import (  # noqa: E402
    DISPOSABLE_TOKEN_VAR,
    DISPOSABLE_URL_VAR,
    PRODUCTION_TOKEN_VAR,
    PRODUCTION_URL_VAR,
    disposable_config_status,
)

D_URL = "libsql://psxni-disposable-verify-20261108-example.turso.io"


def _status(**env):
    return disposable_config_status(env)[0]


def test_disposable_gate_skips_when_nothing_configured():
    assert _status() == "skip"
    assert _status(**{PRODUCTION_URL_VAR: URL, PRODUCTION_TOKEN_VAR: "p"}) == "skip"   # never falls back


def test_disposable_gate_fails_on_incomplete_configuration():
    assert _status(**{DISPOSABLE_URL_VAR: D_URL}) == "fail"
    assert _status(**{DISPOSABLE_TOKEN_VAR: "t"}) == "fail"


def test_disposable_gate_refuses_non_turso_and_production_targets():
    ok = {DISPOSABLE_URL_VAR: D_URL, DISPOSABLE_TOKEN_VAR: "t"}
    assert _status(**ok) == "ok"
    assert _status(**dict(ok, **{DISPOSABLE_URL_VAR: "sqlite:///tmp/x.db"})) == "fail"
    assert _status(**dict(ok, **{DISPOSABLE_URL_VAR: "libsql://psx-news-intelligence-imranrazabozdar"
                                                     ".aws-ap-south-1.turso.io"})) == "fail"
    prod = "libsql://prod-db-example.turso.io"
    same_host_other_scheme = "https://PROD-DB-EXAMPLE.turso.io/"
    assert _status(**dict(ok, **{DISPOSABLE_URL_VAR: same_host_other_scheme,
                                 PRODUCTION_URL_VAR: prod})) == "fail"
    assert _status(**dict(ok, **{PRODUCTION_TOKEN_VAR: "t"})) == "fail"          # production token reused
    assert _status(**dict(ok, **{PRODUCTION_URL_VAR: prod, PRODUCTION_TOKEN_VAR: "p"})) == "ok"


def test_ci_workflow_never_configures_the_disposable_database():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for wf in (root / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        assert DISPOSABLE_URL_VAR not in text and DISPOSABLE_TOKEN_VAR not in text, wf.name
