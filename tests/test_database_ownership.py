"""Database ownership (fail closed). The production database is exclusive to PSX-NEWS-INTELLIGENCE.

These tests make no network calls: TursoHTTPDatabase does no I/O in its constructor."""

from __future__ import annotations

import pytest

from database.connection import (
    OWNED_PRODUCTION_HOST,
    DatabaseConfigError,
    TursoHTTPDatabase,
    check_database_host,
    connect,
    remote_host,
)

OWNED = f"libsql://{OWNED_PRODUCTION_HOST}"
TECHNICAL_LIKE = "libsql://psx-intelligence-technical-example.aws-us-east-1.turso.io"


def test_the_owned_production_host_is_accepted_for_production():
    db = TursoHTTPDatabase(OWNED, "token")
    assert db.url == f"https://{OWNED_PRODUCTION_HOST}"


@pytest.mark.parametrize("url", [
    TECHNICAL_LIKE,
    "libsql://psx-news-intelligence-imranrazabozdar.example.com",
    f"libsql://{OWNED_PRODUCTION_HOST}.evil.example",            # lookalike suffix
    f"libsql://evil.example/{OWNED_PRODUCTION_HOST}",            # host hidden in the path
    f"libsql://user@{OWNED_PRODUCTION_HOST}",                    # userinfo smuggled in
    f"libsql://{OWNED_PRODUCTION_HOST}?tls=1",                   # query smuggled in
    "libsql://psxni-migration-rehearsal-x.aws-us-east-1.turso.io",   # a rehearsal host is not production
])
def test_production_refuses_every_other_host(url):
    with pytest.raises(DatabaseConfigError):
        TursoHTTPDatabase(url, "token")


def test_production_accepts_case_and_trailing_dot_variants_of_the_owned_host_only():
    assert remote_host(f"libsql://{OWNED_PRODUCTION_HOST.upper()}.") == OWNED_PRODUCTION_HOST
    assert remote_host(f"libsql://{OWNED_PRODUCTION_HOST}:443") == OWNED_PRODUCTION_HOST


def test_disposable_needs_the_rehearsal_prefix_and_never_the_owned_host():
    check_database_host("libsql://psxni-migration-rehearsal-1109-x.aws-us-east-1.turso.io", "disposable")
    with pytest.raises(DatabaseConfigError):
        check_database_host(OWNED, "disposable")
    with pytest.raises(DatabaseConfigError):
        check_database_host(TECHNICAL_LIKE, "disposable")


def test_test_purpose_needs_the_test_prefix_and_never_the_owned_host():
    check_database_host("libsql://psxni-test-integration.aws-us-east-1.turso.io", "test")
    with pytest.raises(DatabaseConfigError):
        check_database_host(OWNED, "test")
    with pytest.raises(DatabaseConfigError):
        check_database_host("libsql://psxni-migration-rehearsal-1.turso.io", "test")


def test_unknown_purpose_is_refused():
    with pytest.raises(DatabaseConfigError):
        check_database_host(OWNED, "shared")


def test_the_technical_engine_cannot_reach_the_production_host_through_connect(monkeypatch):
    """connect() reads the environment: a technical host there must be refused, not used."""
    monkeypatch.setenv("PSXNI_TURSO_DATABASE_URL", TECHNICAL_LIKE)
    monkeypatch.setenv("PSXNI_TURSO_AUTH_TOKEN", "token")
    with pytest.raises(DatabaseConfigError):
        connect()


def test_connect_with_the_owned_host_in_the_environment_is_allowed(monkeypatch):
    monkeypatch.setenv("PSXNI_TURSO_DATABASE_URL", OWNED)
    monkeypatch.setenv("PSXNI_TURSO_AUTH_TOKEN", "token")
    assert isinstance(connect(), TursoHTTPDatabase)


def test_a_disposable_handle_cannot_be_used_on_the_production_host():
    with pytest.raises(DatabaseConfigError):
        TursoHTTPDatabase(OWNED, "token", purpose="disposable")


def test_no_module_hard_codes_a_second_production_host():
    """No runtime module may name a Turso host other than the owned one (fixtures live in tests)."""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    host = re.compile(r"[a-z0-9][a-z0-9-]*\.aws-[a-z0-9-]+\.turso\.io")
    hits = []
    for path in list((root / "database").glob("*.py")) + list((root / "engines").glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            for found in host.findall(line):
                if found != OWNED_PRODUCTION_HOST:
                    hits.append(f"{path.name}: {found}")
    assert hits == [], hits
