"""The extraction quality gate: what it trusts, and what it sends to a stronger model."""

from __future__ import annotations

from scripts import check_extraction_batch as gate

SOURCE = ("cement energy is 70 percent of cost and limestone is 5 percent " * 400) + " 1500 2000 3000 45 60"


def row(text, period=None, **kw):
    base = {"company": "SECTOR:CEMENT", "topic": "cost.energy_share", "fact_text": text, "value": None,
            "unit": None, "period": period, "source_name": "ARN, 'X' (YouTube transcript, undated)",
            "source_url": "https://y/x", "video_id": "x", "confidence": "analyst_view"}
    base.update(kw)
    return base


def test_a_well_grounded_file_passes():
    rows = [row("Energy is 70 percent of cost.") for _ in range(40)]
    assert gate.judge(rows, SOURCE).ok


def test_numbers_the_speaker_never_said_are_flagged_as_invented():
    rows = [row("Margins were 9123 and 8841 and 7712 and 6655 and 5544 and 4433.") for _ in range(40)]
    v = gate.judge(rows, SOURCE)
    assert not v.ok and any("possible invention" in r for r in v.reasons)


def test_a_relative_period_is_a_defect_because_it_mixes_eras():
    rows = [row("Energy is 70 percent of cost.", period="last year") for _ in range(40)]
    assert any("relative period" in r for r in gate.judge(rows, SOURCE).reasons)


def test_a_sparse_file_from_a_long_source_is_escalated_as_skimmed():
    v = gate.judge([row("Energy is 70 percent of cost.")], SOURCE)
    assert not v.ok and any("too sparse" in r for r in v.reasons)


def test_an_empty_file_is_fine_for_a_short_source_and_suspect_for_a_long_one():
    assert gate.judge([], "short personal finance talk").ok
    assert not gate.judge([], SOURCE).ok


def test_buy_sell_wording_is_flagged():
    rows = [row("You should buy this stock at 45.") for _ in range(40)]
    assert any("advice" in r for r in gate.judge(rows, SOURCE).reasons)


def test_a_row_missing_the_undated_declaration_breaks_the_schema():
    rows = [row("Energy is 70 percent of cost.", source_name="ARN, 'X'") for _ in range(40)]
    assert any("schema" in r for r in gate.judge(rows, SOURCE).reasons)


# ---------- advice means a recommendation to a reader, not the word "sell"

def test_selling_electricity_or_buying_back_shares_is_not_advice():
    rows = [row("A power plant may sell electricity directly to private customers.") for _ in range(40)]
    rows += [row("The company announced a plan to buy back shares.") for _ in range(5)]
    assert not any("advice" in r for r in gate.judge(rows, SOURCE).reasons)


def test_a_directive_to_the_reader_still_counts_as_advice():
    for text in ("You should buy this stock now.", "I would sell the shares at 45.",
                 "The target price is 45.", "Buy the stock before the result."):
        rows = [row(text) for _ in range(40)]
        assert any("advice" in r for r in gate.judge(rows, SOURCE).reasons), text


def test_a_reviewed_empty_file_is_trusted_but_an_unreviewed_one_is_still_flagged():
    assert not gate.judge([], SOURCE).ok
    assert gate.judge([], SOURCE, reviewed_empty=True).ok


# ---------- bleed: a fact filed under the wrong video of the same chunk

OWN = ("financial statements balance sheet profit margin " * 300) + " 2500 4100"
SIBLING = ("petroleum policy royalty gas price " * 300) + " 1994 1997 2001 2012 12.5"


def test_numbers_found_only_in_a_sibling_video_are_flagged_as_bleed():
    rows = [row("Policies from 1994, 1997, 2001 and 2012 set the producer price.") for _ in range(3)]
    v = gate.judge(rows * 12, OWN, siblings=[SIBLING])
    assert any("another video of the same chunk" in r for r in v.reasons)


def test_a_row_grounded_in_its_own_video_is_not_bleed():
    rows = [row("Profit before tax was 2500 in the period.") for _ in range(40)]
    assert not any("another video" in r for r in gate.judge(rows, OWN, siblings=[SIBLING]).reasons)


def test_a_number_in_neither_video_is_invention_not_bleed():
    rows = [row("Margins reached 9123 and 8841 and 7712 and 6655 and 5544 and 4433.") for _ in range(40)]
    reasons = gate.judge(rows, OWN, siblings=[SIBLING]).reasons
    assert any("possible invention" in r for r in reasons)
    assert not any("another video" in r for r in reasons)


def test_a_single_stray_row_is_tolerated_but_a_pattern_is_not():
    clean = [row("Profit before tax was 2500 in the period.") for _ in range(40)]
    one = clean + [row("Royalty was 12.5 percent of the gas price.")]
    assert not any("another video" in r for r in gate.judge(one, OWN, siblings=[SIBLING]).reasons)


def test_dated_mode_accepts_a_dated_source_and_refuses_relative_words_in_the_sentence():
    src = "words " * 100 + "KSE closed at 164000 points"
    ok = {"company": "MACRO:PAKISTAN", "topic": "market.kse100_move", "value": 164000, "unit": "points",
          "fact_text": "On 9 Oct 2026 the KSE-100 closed at 164000 points.", "period": "2026-10-09",
          "source_name": "Standard Capital Securities, 'T' (YouTube, 2026-10-09)", "source_url": "u",
          "video_id": "v", "confidence": "fact"}
    assert gate.judge([ok], src, dated=True).ok
    assert not gate.judge([ok], src).ok  # ARN mode still insists on "undated"
    bad = dict(ok, fact_text="Today the KSE-100 closed at 164000 points.")
    verdict = gate.judge([bad], src, dated=True)
    assert not verdict.ok and "relative time word" in "; ".join(verdict.reasons)


def test_dated_mode_flags_a_skimmed_source_whose_figures_did_not_reach_rows():
    figures = " ".join(f"{n}.5" for n in range(100, 112))
    src = "words " * 400 + figures
    row = {"company": "MACRO:PAKISTAN", "topic": "market.x", "value": None, "unit": None,
           "fact_text": "On 9 Oct 2026 the index closed at 100.5 points.", "period": "2026-10-09",
           "source_name": "S, 'T' (YouTube, 2026-10-09)", "source_url": "u", "video_id": "v",
           "confidence": "fact"}
    verdict = gate.judge([row], src, dated=True)
    assert not verdict.ok and "figures reached a row" in "; ".join(verdict.reasons)
    assert "figures reached a row" not in "; ".join(gate.judge([row], src).reasons)  # ARN mode unchanged


def test_dated_mode_does_not_flag_years_dates_or_small_spoken_numbers():
    src = ("PUBLICATION_DATE: 2024-01-22\n" + "words " * 300 + "OGDC fell 2.5 percent")
    row = {"company": "OGDC", "topic": "news.x", "value": None, "unit": None,
           "fact_text": "On 22 Jan 2024 OGDC fell 2.5 percent; 3 of 4 analysts saw a rebound by Feb 2025.",
           "period": "2024-01-22", "source_name": "S, 'T' (YouTube, 2024-01-22)", "source_url": "u",
           "video_id": "v", "confidence": "fact"}
    assert gate.judge([row], src, dated=True).ok
    invented = dict(row, fact_text="On 22 Jan 2024 OGDC fell 7.9 percent.")
    verdicts = gate.judge([invented] * 6, src, dated=True)
    assert not verdicts.ok and "possible invention" in "; ".join(verdicts.reasons)
