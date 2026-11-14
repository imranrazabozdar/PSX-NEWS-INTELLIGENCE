"""Profile and competitor rows: facts only. The company description (Investify's own text) and the
extractor's own note are never stored. No network."""

from __future__ import annotations

import json
from pathlib import Path

from engines import investify_extract as x
from engines import research_facts as rf

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "investify"
DAY = "2026-11-16T05:00:00Z"


def _profile_rows():
    fields = x.parse_profile((FIX / "profile_synthetic.html").read_bytes(), "HUBC")
    assert fields.get("description")  # the fixture has a description, so the exclusion is really tested
    rows = rf.rows_from_fields(company="HUBC", endpoint="profile", fields=fields, url="u", fetched_at_utc=DAY)
    return fields, rows


def test_profile_rows_keep_facts_and_never_the_description():
    fields, rows = _profile_rows()
    texts = [r["fact_text"] for r in rows]
    assert not any(fields["description"][:40] in t for t in texts)
    assert "CEO: Person B" in texts and "Chairperson: Person A" in texts
    assert {r["topic"] for r in rows} >= {"profile.sector", "profile.leadership", "profile.market_structure"}
    for r in rows:
        assert r["source_name"] == rf.SOURCE_NAME and r["source_date"] == "2026-11-16"


def test_competitor_rows_list_peers_and_never_the_extractor_note():
    fields = x.parse_competitors((FIX / "competitors_synthetic.html").read_bytes(), "TGT")
    rows = rf.rows_from_fields(company="TGT", endpoint="competitors", fields=fields, url="u",
                               fetched_at_utc=DAY)
    peers = [r for r in rows if r["topic"] == "competitors.peers"]
    assert len(peers) == fields["same_sector_count"] == 16
    assert all(r["fact_text"].startswith("Peer: ") for r in peers)
    assert fields["note"] not in json.dumps(rows)


def test_the_generic_path_also_drops_any_description_field():
    rows = rf.rows_from_fields(company="X", endpoint="other", url="u", fetched_at_utc=DAY,
                               fields={"description": "Investify text", "sector": "S"})
    assert [r["fact_text"] for r in rows] == ["sector: S"]
