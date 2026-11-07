"""Phase 0 acceptance: app skeleton starts; settings come only from PSXNI_ variables."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from config.settings import load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_app_starts_without_errors(monkeypatch):
    monkeypatch.delenv("PSXNI_TURSO_DATABASE_URL", raising=False)
    at = AppTest.from_file(str(REPO_ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "PSX Fundamental & News Intelligence"
    assert any(m.value == "Not connected" for m in at.metric)


def test_settings_defaults(monkeypatch):
    for name in ("PSXNI_ENV", "PSXNI_KILL_SWITCH", "PSXNI_TURSO_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    s = load_settings()
    assert s.env == "local"
    assert s.kill_switch is False
    assert s.database_configured is False


def test_settings_ignore_unprefixed_variables(monkeypatch):
    monkeypatch.delenv("PSXNI_TURSO_DATABASE_URL", raising=False)
    monkeypatch.setenv("TURSO_DATABASE_URL", "libsql://someone-else.example")
    assert load_settings().database_configured is False


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("PSXNI_KILL_SWITCH", "true")
    assert load_settings().kill_switch is True


def test_no_secrets_files_committed():
    for name in (".env", ".streamlit/secrets.toml"):
        assert not (REPO_ROOT / name).exists() or _is_ignored(name)


def _is_ignored(rel: str) -> bool:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    return rel in gitignore or Path(rel).name in gitignore
