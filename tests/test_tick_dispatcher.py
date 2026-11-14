"""The dispatcher starts the tick on the same slots, reads the secret, and never prints it. No network."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github" / "workflows" / "tick-dispatcher.yml").read_text(encoding="utf-8")
TICK = (ROOT / ".github" / "workflows" / "psx_fetch.yml").read_text(encoding="utf-8")


def test_both_schedules_are_off_the_top_of_the_hour_and_on_weekdays():
    tick = re.search(r'cron: "([^"]+)"', TICK).group(1)
    dispatch = re.search(r'cron: "([^"]+)"', TEXT).group(1)
    assert tick == "17,47 1-11 * * 1-5" and dispatch == "7,37 1-11 * * 1-5"
    for expr in (tick, dispatch):
        assert "0" not in expr.split()[0].split(",") and "30" not in expr.split()[0].split(",")


def test_the_dispatcher_reads_the_secret_and_never_echoes_it():
    assert "secrets.PSXNI_DISPATCH_TOKEN" in TEXT
    assert not re.search(r"echo[^\n]*\$\{\{\s*secrets\.", TEXT)
    assert "echo \"$GH_TOKEN\"" not in TEXT and "set -x" not in TEXT


def test_the_dispatcher_only_starts_the_tick_workflow_on_main():
    assert "gh workflow run psx_fetch.yml --ref main" in TEXT
    assert "investify" not in TEXT.lower()
