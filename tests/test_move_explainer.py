from datetime import date, timedelta

from engines import move_explainer as me
from scripts import explain_moves as ex


def series(sym, closes, vols=None, start=date(2026, 10, 1)):
    return [
        {
            "symbol": sym,
            "trade_date": (start + timedelta(days=i)).isoformat(),
            "close": c,
            "volume": (vols[i] if vols else 100.0),
        }
        for i, c in enumerate(closes)
    ]


def flat_then(sym, last, n=25):
    return series(sym, [100.0] * (n - 1) + [last])


def moves_for(spec):
    return me.daily_moves({s: rows for s, rows in spec.items()})


def explain_one(
    extra_facts=(), news=(), sector="Banks", peers=("P1", "P2", "P3", "P4"), peer_last=100.0, macro=()
):
    spec = {"AAA": flat_then("AAA", 110.0)}
    for p in peers:
        spec[p] = flat_then(p, peer_last)
    mv = moves_for(spec)
    day = spec["AAA"][-1]["trade_date"]
    item = {"symbol": "AAA", "day": day, **mv[("AAA", day)]}
    return me.explain(
        item,
        facts=list(extra_facts),
        history=[],
        news_rows=list(news),
        sector=sector,
        sector_symbols=["AAA", *peers],
        moves=mv,
        all_symbols=sorted(spec),
        macro_facts=list(macro),
    ), day


def test_notable_moves_need_a_big_move_or_heavy_volume():
    spec = {
        "AAA": flat_then("AAA", 110.0),
        "BBB": flat_then("BBB", 101.0),
        "CCC": series("CCC", [100.0] * 24 + [101.0], [100.0] * 24 + [500.0]),
    }
    out = me.notable(moves_for(spec), "2026-10-01")
    assert {m["symbol"] for m in out} == {"AAA", "CCC"}


def test_no_evidence_says_so_and_names_what_is_missing():
    item, _ = explain_one()
    assert item["verdict"] == "no identified cause in the evidence on file"
    assert item["evidence"] == [] and any("no company news" in u for u in item["unknown"])


def test_a_result_the_evening_before_is_consistent_evidence_and_ranks_first():
    item0, day = explain_one()
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    fact = {
        "topic": "results.quarterly",
        "fact_text": "Financial result: EPS 5",
        "source_date": prev,
        "source_name": "PSX",
        "value": 5.0,
        "unit": "PKR/share",
        "period": "x",
    }
    item, _ = explain_one(extra_facts=[fact], news=[{"day": day, "stories": 2, "top_title": "AAA jumps"}])
    assert item["verdict"].startswith("evidence on file about this company")
    assert [e["kind"] for e in item["evidence"]][0] == "company_event"
    assert "not proof" not in item["verdict"]


def test_an_old_result_is_not_offered_as_the_cause():
    item0, day = explain_one()
    old = (date.fromisoformat(day) - timedelta(days=10)).isoformat()
    fact = {
        "topic": "results.quarterly",
        "fact_text": "EPS 5",
        "source_date": old,
        "source_name": "PSX",
        "value": 5.0,
        "unit": "PKR/share",
        "period": "x",
    }
    item, _ = explain_one(extra_facts=[fact])
    assert item["evidence"] == []


def test_moving_with_the_sector_is_reported_and_the_residual_shrinks():
    item, _ = explain_one(peer_last=104.0)
    kinds = [e["kind"] for e in item["evidence"]]
    assert "sector" in kinds and item["verdict"].startswith("the move was shared")
    assert round(item["residual_vs_group"], 1) == 6.0


def test_too_few_peers_means_no_sector_claim():
    item, _ = explain_one(peers=("P1", "P2"), peer_last=104.0)
    assert "sector" not in [e["kind"] for e in item["evidence"]]


def test_macro_facts_are_context_only_and_never_a_cause():
    item0, day = explain_one()
    m = {
        "topic": "market.rates",
        "fact_text": "SBP held the policy rate",
        "source_date": day,
        "source_name": "x",
    }
    item, _ = explain_one(macro=[m])
    assert item["macro_context"] and item["verdict"] == "no identified cause in the evidence on file"
    md = me.render_markdown([item], day, 5)
    assert "not shown to cause" in md and "not proof" in md


def test_the_report_gives_no_action_words():
    item, day = explain_one(peer_last=104.0)
    md = me.render_markdown([item], day, 5).lower()
    for word in ("buy ", "sell ", "target", "stop loss", "will rise"):
        assert word not in md


def test_sector_names_come_from_the_profile_fact():
    class DB:
        def execute(self, sql, params=()):
            return [
                {"company": "HBL", "topic": "profile.sector", "fact_text": "Sector: Commercial Banks"},
                {"company": "HBL", "topic": "profile.leadership", "fact_text": "CEO x"},
            ]

    assert ex.sectors_of(DB(), ["HBL"]) == {"HBL": "Commercial Banks"}


def _announcement(day, label, text="x"):
    return {
        "topic": f"announcements.{label}",
        "fact_text": f"{day}: {text}",
        "source_date": day,
        "source_name": "Investify",
        "value": None,
        "unit": None,
        "period": day,
    }


def test_a_material_announcement_counts_as_company_evidence():
    item0, day = explain_one()
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    item, _ = explain_one(extra_facts=[_announcement(prev, "Management Change", "CEO resigns")])
    assert item["verdict"].startswith("evidence on file about this company")
    assert [e["kind"] for e in item["evidence"]][0] == "company_announcement"


def test_a_scheduled_notice_alone_is_not_called_a_cause():
    item0, day = explain_one()
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    item, _ = explain_one(extra_facts=[_announcement(prev, "Board Meeting", "to consider dividend")])
    assert item["verdict"].startswith("only routine scheduled notices")
    assert [e["kind"] for e in item["evidence"]] == ["scheduled_notice"]
    assert item["unknown"] and any("no company news" in u for u in item["unknown"])


def test_routine_labels_are_left_out_and_the_report_lists_the_unexplained():
    item0, day = explain_one()
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    item, _ = explain_one(
        extra_facts=[
            _announcement(prev, "Report Transmission"),
            _announcement(prev, "Insider Sell"),
            _announcement(prev, "Other"),
        ]
    )
    assert item["evidence"] == [] and item["verdict"] == "no identified cause in the evidence on file"
    md = me.render_markdown([item], day, 5)
    assert "Unexplained (no cause on file): 1 of 1." in md
