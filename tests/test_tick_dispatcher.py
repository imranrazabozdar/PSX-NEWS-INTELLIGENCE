"""The dispatcher starts the tick on the same slots, reads the secret, and never prints it. No network."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / ".github" / "workflows" / "tick-dispatcher.yml").read_text(encoding="utf-8")
TICK = (ROOT / ".github" / "workflows" / "psx_fetch.yml").read_text(encoding="utf-8")


def test_the_dispatcher_uses_the_same_weekday_slots_as_the_tick():
    cron = re.search(r'cron: "([^"]+)"', TEXT).group(1)
    assert cron == re.search(r'cron: "([^"]+)"', TICK).group(1) == "0,30 1-11 * * 1-5"


def test_the_dispatcher_reads_the_secret_and_never_echoes_it():
    assert "secrets.PSXNI_DISPATCH_TOKEN" in TEXT
    assert not re.search(r"echo[^\n]*\$\{\{\s*secrets\.", TEXT)
    assert "echo \"$GH_TOKEN\"" not in TEXT and "set -x" not in TEXT


def test_the_dispatcher_only_starts_the_tick_workflow_on_main():
    assert "gh workflow run psx_fetch.yml --ref main" in TEXT
    assert "investify" not in TEXT.lower()
