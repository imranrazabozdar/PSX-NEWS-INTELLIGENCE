from engines import explanation_scoring as sc


def bars(closes):
    return [{"trade_date": f"2026-10-{i + 1:02d}", "close": c} for i, c in enumerate(closes)]


def test_forward_returns_are_signed_to_the_direction_of_the_move():
    up = sc.forward_signed(bars([100, 110, 112, 100, 100, 100, 100, 121]), "2026-10-02", 10.0)
    assert round(up[1], 1) == 1.8 and round(up[5], 1) == -9.1  # carried on one day, gave it back by day five
    down = sc.forward_signed(bars([100, 90, 88]), "2026-10-02", -10.0)
    assert round(down[1], 1) == 2.2  # a further fall counts as carrying on
    assert (
        sc.forward_signed(bars([100, 110]), "2026-10-02", 10.0) == {}
    )  # no later session: unknown, not zero
    assert sc.forward_signed(bars([100, 110]), "2026-10-09", 10.0) == {}


def test_buckets_follow_the_strongest_evidence():
    def item(*kinds):
        return {"evidence": [{"kind": k} for k in kinds]}

    assert sc.bucket_of(item("company_event", "sector")) == "results"
    assert sc.bucket_of(item("company_news")) == "company"
    assert sc.bucket_of(item("company_announcement", "scheduled_notice")) == "company"
    assert sc.bucket_of(item("sector")) == "shared"
    assert sc.bucket_of(item("scheduled_notice")) == "scheduled"
    assert sc.bucket_of(item()) == "unexplained"


def test_summary_counts_flags_low_samples_and_keeps_missing_forward_unknown():
    rows = [
        {"bucket": "unexplained", "move": 6.0, "forward": {1: 1.0, 5: -2.0}},
        {"bucket": "unexplained", "move": -8.0, "forward": {1: -1.0}},
        {"bucket": "results", "move": 5.0, "forward": {}},
    ]
    s = sc.summarise(rows)
    assert s["total"] == 3 and s["buckets"]["unexplained"]["n"] == 2
    assert s["buckets"]["unexplained"]["low_sample"] and s["buckets"]["all"]["n"] == 3
    assert s["buckets"]["unexplained"]["fwd_1d"] == {"n": 2, "mean": 0.0, "median": 0.0, "carried_on": 50.0}
    assert s["buckets"]["unexplained"]["fwd_5d"]["n"] == 1
    assert s["buckets"]["results"]["fwd_1d"] == {"n": 0, "mean": None, "median": None, "carried_on": None}
    assert s["buckets"]["shared"]["mean_abs_move"] is None


def test_the_report_states_its_limits_and_gives_no_advice():
    md = sc.render_markdown(
        sc.summarise([{"bucket": "company", "move": 7.0, "forward": {1: 1.0, 5: 2.0}}]),
        "2026-05-21",
        "2026-11-16",
        148,
    )
    low = md.lower()
    assert "not a rule and not a forecast" in low and "low-sample" in low
    for word in ("buy ", "sell ", "will rise", "stop loss"):
        assert word not in low
