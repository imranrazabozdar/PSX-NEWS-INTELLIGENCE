"""Investify export to research_fact rows: what is kept, what is never stored."""

from __future__ import annotations

import sqlite3

from scripts import build_investify_capsule as b

SCRAPED = "2026-11-16T23:55:32+00:00"


def test_metric_rows_keep_numbers_and_units_and_drop_label_only_rows():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE fundamentals_metrics (symbol, metric, raw_value, numeric_value, period, scraped_at)"
    )
    db.executemany(
        "INSERT INTO fundamentals_metrics VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("HUBC", "Dividend Yield", "9.66%", 9.66, "ANNUAL 2026 FY", SCRAPED),
            ("HUBC", "Annual EPS", "Rs. 38.26", 38.26, "2026 FY", SCRAPED),
            ("HUBC", "Market Note", "n/a", None, "CURRENT", SCRAPED),
        ],
    )
    rows = {r["topic"]: r for r in b.metric_rows(db)}
    assert set(rows) == {"fundamentals.dividend_yield", "fundamentals.annual_eps"}
    assert (
        rows["fundamentals.dividend_yield"]["unit"] == "%"
        and rows["fundamentals.annual_eps"]["unit"] == "PKR"
    )
    assert (
        rows["fundamentals.annual_eps"]["value"] == 38.26
        and rows["fundamentals.annual_eps"]["source_date"] == "2026-11-16"
    )


def test_announcements_keep_date_group_and_title_only():
    lines = [
        "Highlights",
        "HUBC",
        "Hub Power Company Ltd",
        "Dividend",
        "Neutral",
        "02/11/2026, 3:01 PM",
        "HUBCO credits final cash dividend of Rs. 5 per share",
        "A long summary written by Investify.",
        "Highlights",
        "Original PDF",
    ]
    rows = b.announcement_rows("HUBC", lines, SCRAPED)
    assert len(rows) == 1 and rows[0]["topic"] == "announcements.Dividend"
    assert rows[0]["fact_text"] == "2026-11-02: HUBCO credits final cash dividend of Rs. 5 per share"
    assert rows[0]["as_of"] == "2026-11-02" and "summary" not in rows[0]["fact_text"]
    assert "Neutral" not in rows[0]["fact_text"]  # Investify's sentiment label is never stored


def test_profile_rows_take_segment_sector_and_people_but_never_the_description():
    lines = [
        "Hub Power Company Ltd",
        "Company profile",
        "HUBC",
        "•",
        "PSX",
        "Regular",
        "207.02",
        "+",
        "Company Profile",
        "Hub Power Company Ltd",
        "HUBC",
        "PSX",
        "Power Generation & Distribution",
        "The Hub Power Company Limited was incorporated in Pakistan in 1991 as a public limited company.",
        "Leadership",
        "Chairperson",
        "Mr. Habibullah Khan",
        "CEO",
        "Muhammad Kamran Kamal",
        "Registrar",
        "FAMCO Share Registration Services",
        "Auditor",
        "A.F. Ferguson & Co.",
    ]
    texts = [r["fact_text"] for r in b.profile_rows("HUBC", lines, SCRAPED)]
    assert "PSX market segment: Regular" in texts and "Sector: Power Generation & Distribution" in texts
    assert "Chairperson: Mr. Habibullah Khan" in texts and "Auditor: A.F. Ferguson & Co." in texts
    assert not [t for t in texts if "incorporated" in t]
