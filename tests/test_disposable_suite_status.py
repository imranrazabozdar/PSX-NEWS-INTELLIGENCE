"""The disposable-integration suite status.

NOT_RUN unless a target explicitly names a test or disposable database.

Offline and synthetic: these tests only read the environment dictionary they are given, never connect
anywhere.
"""

from __future__ import annotations

from tests.turso_guard import SUITE_NOT_RUN_MESSAGE, disposable_suite_status


def test_nothing_configured_is_reported_as_not_run_with_the_exact_message():
    status, msg = disposable_suite_status({})
    assert (
        status == "NOT_RUN" and msg == "DISPOSABLE_INTEGRATION_SUITE: NOT_RUN (No disposable credentials set)"
    )
    assert msg == SUITE_NOT_RUN_MESSAGE


def test_an_explicit_test_or_disposable_name_runs():
    env = {"TURSO_DATABASE_URL": "libsql://psxni-disposable-check.example.invalid"}
    assert disposable_suite_status(env)[0] == "RUN"
    env = {"PSXNI_TEST_TURSO_DATABASE_URL": "libsql://psxni-test-db.example.invalid"}
    assert disposable_suite_status(env)[0] == "RUN"


def test_an_ambiguous_name_is_refused_not_run():
    # "latest" contains the letters "test" but is not the word
    env = {"TURSO_DATABASE_URL": "libsql://psxni-latest.example.invalid"}
    assert disposable_suite_status(env)[0] == "REFUSED"


def test_production_operational_technical_and_news_names_are_refused_even_with_test_in_the_name():
    for url in (
        "libsql://psx-prod-test.example.invalid",
        "libsql://operational-test.example.invalid",
        "libsql://technical-test.example.invalid",
        "libsql://news-test.example.invalid",
    ):
        assert disposable_suite_status({"TURSO_DATABASE_URL": url})[0] == "REFUSED", url


def test_the_production_host_is_refused():
    prod = "libsql://psxni-main.example.invalid"
    env = {"TURSO_DATABASE_URL": "libsql://psxni-main.example.invalid/test", "PSXNI_TURSO_DATABASE_URL": prod}
    assert disposable_suite_status(env)[0] == "REFUSED"
