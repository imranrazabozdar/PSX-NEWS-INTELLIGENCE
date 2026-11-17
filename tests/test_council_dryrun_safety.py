"""The dry run cannot write to production, cannot reach another database, and fails closed."""

from __future__ import annotations

import re
from pathlib import Path

from scripts import council_news_dryrun as cli

ROOT = Path(__file__).resolve().parents[1]
DRYRUN_FILES = (
    "engines/council_news.py",
    "engines/council_ledger.py",
    "engines/news_importance.py",
    "scripts/council_news_dryrun.py",
)
WRITE_WORDS = re.compile(
    r"INSERT INTO|UPDATE \w+ SET|DELETE FROM|CREATE TABLE|CREATE INDEX|DROP |ALTER TABLE"
)


def test_no_dry_run_module_contains_a_database_write_or_ddl_statement():
    for name in DRYRUN_FILES:
        text = (ROOT / name).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith(("#", '"', "'")))
        assert not WRITE_WORDS.search(code), f"{name} mentions a write statement"
        assert "absorb_sector_capsule" not in text and "apply_library" not in text, name


def test_the_runner_fails_closed_without_a_database(monkeypatch, tmp_path):
    for var in ("PSXNI_LIBRARY_TURSO_DATABASE_URL", "PSXNI_LIBRARY_TURSO_AUTH_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    assert cli.main(["--mode", "auto", "--ledger", str(tmp_path / "l.json")]) == 2


def test_the_runner_refuses_a_foreign_database_url(monkeypatch, tmp_path):
    monkeypatch.setenv("PSXNI_LIBRARY_TURSO_DATABASE_URL", "libsql://technical-archive-prod.turso.io")
    monkeypatch.setenv("PSXNI_LIBRARY_TURSO_AUTH_TOKEN", "x")
    assert (
        cli.main(["--mode", "auto", "--ledger", str(tmp_path / "l.json")]) == 2
    )  # the target guard refuses it


def test_the_workflow_is_read_only_dry_run_with_the_agreed_triggers_and_secrets():
    text = (ROOT / ".github/workflows/council_news_dryrun.yml").read_text(encoding="utf-8")
    assert 'workflows: ["News collector"]' in text and "types: [completed]" in text
    assert "options: [ten, auto, report]" in text
    assert re.search(r"permissions:\n  contents: read\n  actions: read\n", text)
    assert "cancel-in-progress: false" in text and "group: council-news-dryrun" in text
    secrets = set(re.findall(r"secrets\.(\w+)", text))
    allowed = {"PSXNI_LIBRARY_TURSO_DATABASE_URL", "PSXNI_LIBRARY_TURSO_AUTH_TOKEN"}
    assert secrets - allowed == {
        "PSXNI_GROQ_API_KEY_ONE",
        "PSXNI_GROQ_API_KEY_TWO",
        "PSXNI_GROQ_API_KEY_THREE",
        "PSXNI_GEMINI_API_KEY_ONE",
        "PSXNI_OPENROUTER_API_KEY_ONE",
    }
    assert "ANTHROPIC" not in text
    runs = " ".join(re.findall(r"run: (.*)", text))
    assert "--apply" not in runs and "absorb" not in runs and "migration" not in runs
