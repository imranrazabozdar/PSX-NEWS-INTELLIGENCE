"""The pending-migration DDL gate: a Turso URL alone never authorises executing migration DDL."""

from __future__ import annotations

import pathlib

import pytest

from tests.turso_guard import OPT_IN_VALUE, OPT_IN_VAR, pending_migration_ddl_permitted

URL = "libsql://example-disposable.turso.io"
PROD_URL = "libsql://psx-news-intelligence-imranrazabozdar.aws-us-east-1.turso.io"


def test_url_alone_is_insufficient():
    assert not pending_migration_ddl_permitted({"PSXNI_TURSO_DATABASE_URL": URL})


def test_url_plus_unrelated_configuration_is_insufficient():
    env = {"PSXNI_TURSO_DATABASE_URL": URL, "PSXNI_TURSO_AUTH_TOKEN": "x", "PSXNI_LIVE_SOURCE_TESTS": "1",
           OPT_IN_VAR: "1", "PSXNI_KILL_SWITCH": "0"}
    assert not pending_migration_ddl_permitted(env)   # "1" is not the explicit value
    env[OPT_IN_VAR] = "true"
    assert not pending_migration_ddl_permitted(env)


def test_explicit_opt_in_requires_the_dedicated_test_database():
    test_env = {"PSXNI_TEST_TURSO_DATABASE_URL": URL, "PSXNI_TEST_TURSO_AUTH_TOKEN": "t"}
    assert pending_migration_ddl_permitted({**test_env, OPT_IN_VAR: OPT_IN_VALUE})
    assert not pending_migration_ddl_permitted({OPT_IN_VAR: OPT_IN_VALUE})            # no URL
    assert not pending_migration_ddl_permitted({"PSXNI_TEST_TURSO_DATABASE_URL": "sqlite://:memory:",
                                                "PSXNI_TEST_TURSO_AUTH_TOKEN": "t",
                                                OPT_IN_VAR: OPT_IN_VALUE})            # not Turso
    # production configuration can never authorise DDL, even with the opt-in
    assert not pending_migration_ddl_permitted({"PSXNI_TURSO_DATABASE_URL": URL,
                                                "PSXNI_TURSO_AUTH_TOKEN": "p", OPT_IN_VAR: OPT_IN_VALUE})
    assert not pending_migration_ddl_permitted({"PSXNI_TEST_TURSO_DATABASE_URL": PROD_URL,
                                                "PSXNI_TEST_TURSO_AUTH_TOKEN": "t", OPT_IN_VAR: OPT_IN_VALUE})


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


# ------------------------------------------------------------------ integration-test isolation (CI)
from tests.turso_guard import (  # noqa: E402
    PRODUCTION_HOST,
    TEST_TOKEN_VAR,
    TEST_URL_VAR,
    integration_config_status,
)

T_URL = "libsql://psxni-integration-test-example.turso.io"


def _it(**env):
    return integration_config_status(env)[0]


def test_production_credentials_are_never_a_fallback():
    prod = {PRODUCTION_URL_VAR: PROD_URL, PRODUCTION_TOKEN_VAR: "p"}
    assert _it(**prod) == "skip"                     # production config alone never enables tests
    assert "never used" in integration_config_status(prod)[1]


def test_missing_test_credentials_skip_cleanly():
    assert _it() == "skip"
    assert _it(**{TEST_URL_VAR: T_URL}) == "fail"     # incomplete config fails loudly instead
    assert _it(**{TEST_TOKEN_VAR: "t"}) == "fail"


@pytest.mark.parametrize("url", [
    PROD_URL,
    "https://" + PRODUCTION_HOST,
    "https://" + PRODUCTION_HOST.upper() + "/",
    "libsql://" + PRODUCTION_HOST + ".",
    "libsql://" + PRODUCTION_HOST + "?tls=1",
])
def test_production_host_is_rejected_in_every_spelling(url):
    assert _it(**{TEST_URL_VAR: url, TEST_TOKEN_VAR: "t"}) == "fail"


def test_test_target_matching_production_configuration_is_rejected():
    other = "libsql://some-other-prod-alias.turso.io"
    assert _it(**{TEST_URL_VAR: other, TEST_TOKEN_VAR: "t", PRODUCTION_URL_VAR: other}) == "fail"
    assert _it(**{TEST_URL_VAR: T_URL, TEST_TOKEN_VAR: "same", PRODUCTION_TOKEN_VAR: "same"}) == "fail"
    assert _it(**{TEST_URL_VAR: "sqlite:///x.db", TEST_TOKEN_VAR: "t"}) == "fail"


def test_dedicated_test_database_is_accepted():
    assert _it(**{TEST_URL_VAR: T_URL, TEST_TOKEN_VAR: "t", PRODUCTION_URL_VAR: PROD_URL,
                  PRODUCTION_TOKEN_VAR: "p"}) == "ok"


def test_integration_module_is_gated_only_by_test_credentials(monkeypatch):
    """Importing the integration module with only production configuration must skip it."""
    import importlib

    for var in (TEST_URL_VAR, TEST_TOKEN_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(PRODUCTION_URL_VAR, PROD_URL)
    monkeypatch.setenv(PRODUCTION_TOKEN_VAR, "p")
    import tests.test_turso_integration as it
    it = importlib.reload(it)
    assert it._STATUS == "skip"
    src = (pathlib.Path(__file__).resolve().parent / "test_turso_integration.py").read_text(encoding="utf-8")
    assert "connect()" not in src
    assert 'environ["PSXNI_TURSO' not in src and 'environ.get("PSXNI_TURSO' not in src


def test_ci_never_passes_production_secrets_to_tests():
    root = pathlib.Path(__file__).resolve().parents[1]
    ci = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "secrets.PSXNI_TURSO_DATABASE_URL" not in ci and "secrets.PSXNI_TURSO_AUTH_TOKEN" not in ci
    assert "secrets.PSXNI_TEST_TURSO_DATABASE_URL" in ci and "secrets.PSXNI_TEST_TURSO_AUTH_TOKEN" in ci
    for wf in (root / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text(encoding="utf-8")
        if "secrets.PSXNI_TURSO_" in text:
            # Only the scheduled collection workflows may hold production secrets, and never run pytest.
            # investify-collect.yml is the consented Investify job (docs/consent/investify-2026-11-12.md).
            allowed = {"scheduled-jobs.yml", "investify-collect.yml"}
            assert wf.name in allowed and "pytest" not in text, wf.name
