from scripts import build_investify_highlights as bh

LINES = [
    "ABC",
    "ABC Ltd",
    "Rights / Bonus",
    "Positive",
    "11/11/2026, 3:29 PM",
    "ABC announces a 36.97% right issue at PKR 10 per share",
    "36.97% right shares at Rs 10 · Book closure 19/11/2026",
    "ABC's final offer document sets out a right issue representing about 36.97% of paid-up capital.",
    "Highlights",
    "Original PDF",
    "Original Image",
    "ABC",
    "ABC Ltd",
    "Other",
    "Neutral",
    "10/11/2026, 9:00 AM",
    "ABC files a notice",
    "Highlights",
    "Original PDF",
]


def test_the_key_line_and_summary_become_linked_facts_and_empty_cards_make_none():
    from engines import announcement_substance as asub

    rows = bh.highlight_rows("ABC", LINES, "2026-11-16T23:55:32Z")
    assert len(rows) == 1  # the second card has no text under its title
    r = rows[0]
    assert r["topic"] == "announcement_highlights" and r["company"] == "ABC" and r["period"] == "2026-11-11"
    assert r["fact_text"].startswith("2026-11-11: 36.97% right shares at Rs 10")  # the title is not repeated
    assert "Book closure 19/11/2026" in r["fact_text"] and len(r["fact_text"]) <= 300
    title = "ABC announces a 36.97% right issue at PKR 10 per share"
    assert r["source_url"].endswith(f"#{asub.title_key(title)}-1")
    assert asub.highlight_text(rows, "2026-11-11", title).startswith("36.97% right shares at Rs 10")
    assert "investify" in r["source_name"].lower() and r["value"] is None


def test_it_refuses_before_the_addendum_is_in_force(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(bh.pol, "highlights_allowed", lambda now: False)
    assert bh.main([str(tmp_path / "none.db"), "--out", str(tmp_path / "o.json")]) == 2
    assert "refused" in capsys.readouterr().out
