"""The read-only row check runs SELECT statements only, and has no write or fetch path. No network."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_check_script_runs_only_select_statements():
    text = (ROOT / "scripts" / "check_research_rows.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)\b", text)
    assert "SELECT" in text


def test_the_check_workflow_is_dispatch_only_with_no_investify_step():
    text = (ROOT / ".github" / "workflows" / "library-readonly-check.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch" in text and "schedule" not in text
    assert "scripts.check_research_rows" in text and "investify" not in text.lower()
