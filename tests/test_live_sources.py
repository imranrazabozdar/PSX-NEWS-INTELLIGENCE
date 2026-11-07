"""Live source checks. Run only with PSXNI_LIVE_SOURCE_TESTS=1; never required for CI.

They fetch and parse the real feeds of sources whose access has been reviewed, using a dry run
against a local SQLite copy of the registry, so nothing is written to any production database.
"""

from __future__ import annotations

import os

import pytest

from collectors.engine import CollectionRefused, collect
from collectors.http import HttpClient
from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate

pytestmark = pytest.mark.skipif(os.environ.get("PSXNI_LIVE_SOURCE_TESTS") != "1",
                                reason="live source tests not enabled (PSXNI_LIVE_SOURCE_TESTS=1)")

LIVE_SOURCES = ("pbs", "dawn", "brecorder", "tribune")


@pytest.fixture(scope="module")
def registry():
    db = SQLiteDatabase()
    migrate(db)
    seed_loader.load(db)
    return db


@pytest.fixture(scope="module")
def client():
    return HttpClient(min_interval=1.5)


@pytest.mark.parametrize("source_id", LIVE_SOURCES)
def test_live_feed_dry_run(registry, client, source_id):
    r = collect(registry, source_id, client=client, dry_run=True, max_items=200)
    assert r.status == "dry_run" and r.http_status == 200, r.errors
    assert r.fetched > 0
    assert all(e["canonical_url"] for e in r.entries)
    assert sum(e["publication_time_status"] == "known" for e in r.entries) == len(r.entries)


def test_robots_restriction_is_honoured_live(registry, client):
    # Policy refuses EIA before any request; robots.txt independently disallows its RSS path.
    with pytest.raises(CollectionRefused):
        collect(registry, "eia", client=client, dry_run=True)
    assert client.allowed_by_robots("https://www.eia.gov/rss/todayinenergy.xml") is False
