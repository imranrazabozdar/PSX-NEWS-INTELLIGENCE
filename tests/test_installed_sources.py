"""Tests for scripts/check_installed_sources.py."""

from __future__ import annotations

import json

from scripts import check_installed_sources as cis


class _FakeDist:
    def __init__(self, name, direct_url=None):
        self.metadata = {"Name": name}
        self._direct = direct_url

    def read_text(self, filename):
        return json.dumps(self._direct) if filename == "direct_url.json" and self._direct else None


def test_vcs_and_local_installs_are_reported(monkeypatch):
    dists = [
        _FakeDist("streamlit"),
        _FakeDist("evil", {"url": "https://example.com/x.git", "vcs_info": {"vcs": "git"}}),
        _FakeDist("local", {"url": "file:///other/project", "dir_info": {"editable": True}}),
    ]
    monkeypatch.setattr(cis.metadata, "distributions", lambda: dists)
    problems = cis.non_index_installs()
    assert len(problems) == 2
    assert any("vcs" in p for p in problems)
    assert any("editable/local dir" in p for p in problems)


def test_missing_declared_dependency_is_reported(monkeypatch):
    monkeypatch.setattr(cis.metadata, "distributions", lambda: [_FakeDist("pytest")])
    assert "streamlit" in cis.missing_declared()


def test_current_environment_is_clean():
    assert cis.non_index_installs() == []
