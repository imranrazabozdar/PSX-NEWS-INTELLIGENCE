"""Source registry: fail closed. Offline, pure functions."""

from __future__ import annotations

import json

import pytest

from engines import source_registry as sr

# ------------------------------------------------------------------ source registry


def _write(tmp_path, sources):
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"version": 1, "sources": sources}))
    return p


def _entry(**over):
    e = {
        "source_id": "owner_ogdc",
        "symbol": "OGDC",
        "company": "Oil & Gas Development Co",
        "category": "annual_report",
        "financial_year": 2025,
        "url_pattern": "https://reports.example.invalid/ogdc/{year}.pdf",
        "permission_status": "permitted",
        "auth_env_var": None,
        "enabled": True,
        "notes": "",
    }
    e.update(over)
    return e


def test_the_shipped_registry_is_empty_so_only_manual_upload_is_possible():
    assert sr.load() == []


def test_automated_fetch_needs_permission_enabled_and_a_pattern(tmp_path):
    src = sr.load(_write(tmp_path, [_entry()]))
    assert src[0].automated_fetch_allowed is True
    for over in (
        {"permission_status": "pending"},
        {"permission_status": "restricted"},
        {"permission_status": "manual_only"},
        {"permission_status": "not_requested"},
        {"enabled": False},
        {"url_pattern": None},
    ):
        blocked = sr.load(_write(tmp_path, [_entry(**over)]))[0]
        assert blocked.automated_fetch_allowed is False, over


def test_an_entry_without_a_valid_status_is_refused_at_load(tmp_path):
    with pytest.raises(sr.RegistryError, match="permission_status"):
        sr.load(_write(tmp_path, [_entry(permission_status="probably_fine")]))


def test_credentials_are_refused_in_urls_and_values_are_refused_in_env_refs(tmp_path):
    with pytest.raises(sr.RegistryError, match="must not contain credentials"):
        sr.load(_write(tmp_path, [_entry(url_pattern="https://user:secret@host.example.invalid/x.pdf")]))
    with pytest.raises(sr.RegistryError, match="PSXNI_"):
        sr.load(_write(tmp_path, [_entry(auth_env_var="sk-live-abc123")]))
    ok = sr.load(_write(tmp_path, [_entry(auth_env_var="PSXNI_OWNER_SOURCE_TOKEN")]))
    assert ok[0].auth_env_var == "PSXNI_OWNER_SOURCE_TOKEN"  # a name only


def test_duplicate_ids_and_unknown_versions_are_refused(tmp_path):
    with pytest.raises(sr.RegistryError, match="duplicate"):
        sr.load(_write(tmp_path, [_entry(), _entry()]))
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"version": 2, "sources": []}))
    with pytest.raises(sr.RegistryError, match="version"):
        sr.load(p)


def test_selection_for_a_document_returns_only_permitted_matches(tmp_path):
    src = sr.load(
        _write(tmp_path, [_entry(), _entry(source_id="other", symbol="PPL", permission_status="pending")])
    )
    assert [
        s.source_id
        for s in sr.automated_allowed(src, symbol="OGDC", category="annual_report", financial_year=2025)
    ] == ["owner_ogdc"]
    assert sr.automated_allowed(src, symbol="OGDC", category="annual_report", financial_year=2024) == []
