from datetime import datetime, timedelta

from engines import announcement_events as ae
from engines import announcement_substance as asub
from engines import council_ledger as cl
from engines import council_news as cn
from engines import news_importance as ni
from tests.test_council_news_dryrun import NOW, VOCAB, fake_pack, make_db


def bars(n=30, vol=100.0, last_vol=100.0, last_close=100.0):
    start = datetime(2026, 10, 1)
    out = [
        {"trade_date": (start + timedelta(days=i)).strftime("%Y-%m-%d"), "close": 100.0, "volume": vol}
        for i in range(n)
    ]
    out[-1]["close"], out[-1]["volume"] = last_close, last_vol
    return out, out[-1]["trade_date"]


def test_reaction_measures_volume_and_move_and_is_unknown_without_history():
    b, day = bars(last_vol=800, last_close=105)
    r = ae.reaction(b, day)
    assert round(r["volume_x"]) == 8 and round(r["move"]) == 5
    assert ae.reaction(b[:10], b[9]["trade_date"]) is None


def test_gate_sends_big_or_reacting_announcements_only():
    assert ae.gate({"tier": "major", "basis": []}, None) == "size graded major"
    assert ae.gate({"tier": "routine"}, {"volume_x": 50, "move": 9}) is None
    assert ae.gate({"tier": "unquantified"}, {"volume_x": 1.0, "move": 0.5}) is None
    assert "reacted" in ae.gate({"tier": "unquantified"}, {"volume_x": 6.0, "move": 0.5})
    assert ae.gate({"tier": "minor"}, None) is None


def test_to_event_is_a_rule_8_announcement_event_with_stable_id():
    e = ae.to_event("MARI", "2026-11-16", "Copper discovery", "size graded major", "x", "https://u")
    assert e.kind == "announcement" and e.event_id.startswith("ann-MARI-") and e.hits[0].rule == 8
    assert ni.priority(e, NOW) > 0
    assert e.event_id == ae.to_event("MARI", "2026-11-16", "Copper discovery", "y", "z", "u").event_id


def test_the_ledger_scan_cadence(tmp_path):
    led = cl.Ledger(tmp_path / "l.json")
    assert led.scan_due("announcements", NOW, 6)
    led.mark_scan("announcements", NOW)
    assert not led.scan_due("announcements", NOW + timedelta(hours=5), 6)
    assert led.scan_due("announcements", NOW + timedelta(hours=6), 6)


def _run(tmp_path, gate, now=NOW, exec_id="g1"):
    led = cl.Ledger(tmp_path / "ledger.json")
    out = cn.execution(
        db=cn.ReadOnlyDB(make_db()),
        env={},
        ledger=led,
        now=now,
        exec_id=exec_id,
        vocab=VOCAB,
        signals_for=lambda d, n: ([], {"baseline": "x"}),
        build_pack=fake_pack,
        calendar=None,
        announcement_events=gate,
    )
    return led, out


def test_gate_events_enter_the_same_queue_and_scan_is_throttled(tmp_path):
    calls = []

    def gate(db, now):
        calls.append(now)
        return [ae.to_event("MARI", "2026-11-16", "Big deal", "size graded major", "d", "https://u")]

    led, out = _run(tmp_path, gate)
    g = out["summary"]["announcement_gate"]
    assert g["scanned"] and g["events"] == 1 and g["error"] is None
    assert any(p["event_id"].startswith("ann-MARI") for p in led.pending()) or any(
        r["event"]["headline"].startswith("MARI") for r in out["records"]
    )
    out2 = cn.execution(
        db=cn.ReadOnlyDB(make_db()),
        env={},
        ledger=led,
        now=NOW + timedelta(hours=1),
        exec_id="g2",
        vocab=VOCAB,
        signals_for=lambda d, n: ([], {"baseline": "x"}),
        build_pack=fake_pack,
        calendar=None,
        announcement_events=gate,
    )
    assert not out2["summary"]["announcement_gate"]["scanned"] and len(calls) == 1


def test_a_failing_gate_never_stops_the_run(tmp_path):
    def boom(db, now):
        raise RuntimeError("budget")

    led, out = _run(tmp_path, boom)
    g = out["summary"]["announcement_gate"]
    assert g["scanned"] and "RuntimeError" in g["error"] and out["summary"]["headlines_read"] == 5
    assert not led.scan_due("announcements", NOW, 6)


def test_asub_is_used_for_grading():
    assert asub.MATERIAL_LABELS


def test_contradiction_flag():
    assert "council says high" in ae.contradiction("high", "major", "preliminary")
    assert ae.contradiction("high", "major", "definitive") is None
    assert "council says low" in ae.contradiction("low", "major", "definitive")
    assert ae.contradiction(None, "major", "definitive") is None
