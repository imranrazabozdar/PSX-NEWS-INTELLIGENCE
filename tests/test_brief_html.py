from engines import brief_html as bh


def brief():
    return {
        "symbol": "A<b>",
        "sector": "Cement & Co",
        "price": {
            "date": "2026-11-19",
            "close": 726.11,
            "change_1d": 1.2,
            "change_5d": None,
            "change_20d": -3.0,
            "series": [],
        },
    }


def test_header_is_escaped_colours_the_sign_and_shows_unknown_changes_as_na():
    html = bh.header(brief(), "Mari <Petroleum>")
    assert "A&lt;b&gt;" in html and "Mari &lt;Petroleum&gt;" in html and "Cement &amp; Co" in html
    assert 'class="g">+1.2%' in html and 'class="r">-3.0%' in html and "n/a" in html
    none = bh.header({"symbol": "X", "sector": None, "price": None})
    assert "No price series on file" in none and "sector unknown" in none


def test_standing_shows_ranks_or_the_reason_it_is_not_scored():
    row = {"technical": 93.2, "fundamental": None, "combined": None}
    found = {"row": row, "ranks": {"technical": (3, 74), "fundamental": None, "combined": None}, "reason": ""}
    html = bh.standing(found)
    assert "rank 3 of 74" in html and "unknown" in html and "not advice" in html
    assert "thinly traded" in bh.standing({"row": None, "reason": "thinly traded", "ranks": {}})
    assert bh.standing(None) == ""


def test_announcements_news_moves_and_facts_render_safely_with_empty_states():
    ann = [
        {
            "weight": "material",
            "tier": "major",
            "label": "M&A",
            "date": "2026-11-16",
            "text": "<x> deal",
            "basis": ["60% stake"],
        },
        {"weight": "routine", "tier": "routine", "label": "Board Meeting", "date": "2026-11-15", "text": "r"},
    ]
    html = bh.announcements(ann)
    assert "&lt;x&gt; deal" in html and "size: major" in html and "1 routine filings not listed" in html
    assert "No announcements" in bh.announcements([])
    assert "No news" in bh.news([]) and "source" in bh.news(
        [{"day": "d", "stories": 2, "top_title": "T", "top_url": "https://x/y"}]
    )
    mv = [
        {
            "day": "2026-11-18",
            "move": 6.1,
            "volume_x": 3.0,
            "verdict": "evidence on file about this company is consistent with the move",
            "evidence": [{"kind": "company_event", "date": "d", "source": "s", "text": "e<1>"}],
        }
    ]
    html = bh.moves(mv)
    assert "PLAUSIBLE_CATALYST" in html and "e&lt;1&gt;" in html and "No notable move" in bh.moves([])
    assert "No results" in bh.facts([], "No results on file.")
