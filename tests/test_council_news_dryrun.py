"""Council news dry run: caps, queue, records, model honesty, read-only database, retries. Offline."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta

import pytest

from database.connection import SQLiteDatabase
from engines import analyst_council as council
from engines import council_ledger as cl
from engines import council_news as cn
from engines import llm
from engines import news_facts as nf
from engines import news_importance as ni
from scripts import build_news_capsule as bnc

NOW = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)  # 11:00 in Pakistan, a Tuesday
LISTING = {
    "HUBC": "The Hub Power Company Limited",
    "NBP": "National Bank of Pakistan",
    "LUCK": "Lucky Cement Limited",
    "OGDC": "Oil and Gas Development Company Limited",
}
ALIASES = {"Hub Power": "HUBC", "Lucky Cement": "LUCK"}
VOCAB = nf.build_vocabulary(LISTING, ALIASES, ["CEMENT", "BANKS"])

STORIES = [  # five different flagged stories at 5 different priorities
    ("Hub Power plant shutdown after fire at unit", "mettis"),  # rule 7
    ("NBP profit falls 29% in the third quarter", "profit"),  # rule 1
    ("Lucky Cement announces interim cash dividend of Rs5 per share", "dawn_business"),  # rule 1
    ("SBP holds policy rate at 11% in Pakistan", "brecorder"),  # rule 2
    ("IMF review mission arrives in Pakistan", "tribune_business"),  # rule 5
]


def make_db():
    db = SQLiteDatabase()
    db.execute(
        "CREATE TABLE news_item (source TEXT, url TEXT, title TEXT, published_at TEXT, section TEXT, "
        "snippet TEXT, fetched_at TEXT, PRIMARY KEY (source, url))"
    )
    db.execute("CREATE TABLE news_progress (source TEXT, key TEXT, value TEXT, updated_utc TEXT)")
    db.execute(
        "CREATE TABLE research_fact (id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT, topic TEXT, "
        "fact_text TEXT)"
    )
    for i, (title, source) in enumerate(STORIES):
        at = (NOW - timedelta(minutes=30 + i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.execute(
            "INSERT INTO news_item VALUES (?, ?, ?, ?, NULL, NULL, ?)",
            (source, f"https://x.pk/{i}", title, at, at),
        )
    return db


def counts(db):
    tables = ("news_item", "news_progress", "research_fact")
    return {t: db.execute(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in tables}  # noqa: S608


class FakeProvider:
    """A free-tier-looking vendor that answers each lens from a table. `calls` counts requests made."""

    name = "groq"

    def __init__(self, directions=None, model="fake-model", tokens=(120, 40), fail_first=0):
        self.model, self.account, self.calls, self.fail_first = model, 1, 0, fail_first
        self.directions = directions or {"news": "benefit", "financial": "benefit", "macro": "benefit"}
        self.tokens = tokens

    def complete(self, *, system, user, json_schema, max_output_tokens):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise llm.TransientProviderError("rate limited")
        role = next(
            (
                r
                for r, mark in (("news", "NEWS AND EVENT"), ("financial", "FINANCIAL"), ("macro", "MACRO"))
                if mark in system
            ),
            None,
        )
        if role is None:  # the orchestrator's synthesis
            return llm.Completion(json.dumps({"summary": "explained"}), self.model, *self.tokens)
        ids = re.findall(r'<item id="(\w+)"', user)
        body = {
            "assessments": [
                {
                    "company": "HUBC",
                    "direction": self.directions[role],
                    "magnitude": "medium",
                    "timing": "immediate",
                    "reason": f"{role} reading",
                    "evidence_ids": ids[:1],
                    "confidence": "medium",
                }
            ]
            if ids
            else [],
            "unresolved": [],
        }
        return llm.Completion(json.dumps(body), self.model, *self.tokens)


def fake_pack(title, companies, db, news=None, sectors=None):
    items = [
        council.Evidence(
            "e1", "figure", "HUBC annual EPS Rs38", "Investify fundamentals", "2026-11-16", "HUBC"
        ),
        council.Evidence("m1", "macro", "Policy rate 11%", "Library", "2026-11-10"),
        council.Evidence("a1", "announcement", "Board meeting notice", "PSX", "2026-11-15", "HUBC"),
    ]
    return council.EvidencePack(event=title, items=items)


def chain_with(provider):
    def chain_for(role, env, ledger, ctx, clock):
        return cn.TrackedLeaf(provider, ledger, ctx, clock), []

    return chain_for


def no_models(role, env, ledger, ctx, clock):
    return None, ["no free-tier model key is configured"]


@pytest.fixture(autouse=True)
def instant_retries(monkeypatch):
    monkeypatch.setattr(cn, "SLEEP", lambda seconds: None)


def run(tmp_path, db, chain_for, now=NOW, exec_id="e1", ledger=None):
    led = ledger or cl.Ledger(tmp_path / "ledger.json")
    out = cn.execution(
        db=cn.ReadOnlyDB(db),
        env={},
        ledger=led,
        now=now,
        exec_id=exec_id,
        vocab=VOCAB,
        signals_for=lambda d, n: ([], {"baseline": "unknown: not enough history yet"}),
        build_pack=fake_pack,
        calendar=None,
        chain_for=chain_for,
    )
    return led, out


# --- read-only database and identity ---------------------------------------------------------------


def test_the_connection_refuses_every_write_and_ddl():
    ro = cn.ReadOnlyDB(make_db())
    assert ro.execute("SELECT COUNT(*) AS n FROM news_item")[0]["n"] == 5
    assert ro.execute("WITH x AS (SELECT 1 AS a) SELECT a FROM x")[0]["a"] == 1
    for bad in (
        "INSERT INTO news_item VALUES (1,2,3,4,5,6,7)",
        "UPDATE news_item SET title = 'x'",
        "DELETE FROM news_item",
        "CREATE TABLE t (a)",
        "DROP TABLE news_item",
        "PRAGMA writable_schema=1",
    ):
        with pytest.raises(cn.ReadOnlyViolation):
            ro.execute(bad)
    with pytest.raises(cn.ReadOnlyViolation):
        ro.batch([("SELECT 1", ())])


def test_database_identity_fails_closed():
    cn.assert_library_identity(make_db())
    other = SQLiteDatabase()
    other.execute("CREATE TABLE market_bars (a)")
    with pytest.raises(cn.IdentityError):
        cn.assert_library_identity(other)
    mixed = make_db()
    mixed.execute("CREATE TABLE market_bars (a)")
    with pytest.raises(cn.IdentityError):
        cn.assert_library_identity(mixed)


# --- caps, queue and structured records ------------------------------------------------------------


def test_two_runs_per_execution_six_per_day_and_the_rest_wait_in_the_queue(tmp_path):
    db = make_db()
    before = counts(db)
    led = None
    ran = []
    for k in range(4):
        led, out = run(
            tmp_path, db, chain_with(FakeProvider()), NOW + timedelta(minutes=30 * k), f"e{k}", led
        )
        ran.append(out["summary"]["ran"])
    assert ran == [2, 2, 1, 0]  # five flagged events: two, two, one, then nothing left
    assert led.runs_on(ni.local_day(NOW)) == 5 and led.pending() == []
    assert counts(db) == before  # nothing was written to the database


def test_a_busy_day_leaves_important_events_queued_not_discarded(tmp_path):
    db = make_db()
    for i in range(6):  # six more distinct flagged stories
        at = (NOW - timedelta(minutes=5 + i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.execute(
            "INSERT INTO news_item VALUES (?, ?, ?, ?, NULL, NULL, ?)",
            ("mettis", f"https://y.pk/{i}", f"NBP profit falls {10 + i}% in quarter {i}", at, at),
        )
    led = None
    for k in range(5):
        led, out = run(
            tmp_path, db, chain_with(FakeProvider()), NOW + timedelta(minutes=30 * k), f"e{k}", led
        )
    assert led.runs_on(ni.local_day(NOW)) == cl.CAP_PER_DAY
    waiting = [q for q in led.pending() if q["state"] == "pending"]
    assert waiting and out["summary"]["pending_after"] == len(waiting)  # still queued for tomorrow


def test_each_event_version_is_assessed_once(tmp_path):
    db = make_db()
    led, first = run(tmp_path, db, chain_with(FakeProvider()))
    keys = {r["event"]["key"] for r in first["records"]}
    led, second = run(tmp_path, db, chain_with(FakeProvider()), NOW + timedelta(minutes=30), "e2", led)
    again = {r["event"]["key"] for r in second["records"]}
    assert not (keys & again)


def test_the_record_carries_evidence_classification_assessment_cost_and_timestamps(tmp_path):
    db = make_db()
    _, out = run(tmp_path, db, chain_with(FakeProvider()))
    r = out["records"][0]
    assert r["schema"] == "council_news_dryrun_v1" and r["outcome"] == "assessed" and r["mode"] == "auto"
    assert r["event"]["provenance"] and all(p["url"] and p["published_at"] for p in r["event"]["provenance"])
    assert r["classification"]["rules"] and r["classification"]["priority"] > 0
    a = r["assessment"]
    assert (
        a["affected_companies"][0]["entity"] == "HUBC"
        and a["affected_companies"][0]["consensus"] == "benefit"
    )
    lens = a["affected_companies"][0]["lenses"]["news"]
    assert lens["evidence_ids"] and lens["confidence"] == "medium" and lens["direction"] == "benefit"
    assert r["cost"]["llm_calls"] == 4 and r["cost"]["input_tokens"] == 480 and r["cost"]["usd"] is None
    assert r["started_at_utc"] and r["ended_at_utc"]
    started = datetime.fromisoformat(r["started_at_utc"].replace("Z", "+00:00"))
    assert r["time"]["pkt_day"] == (started + timedelta(hours=5)).date().isoformat()
    assert r["time"]["after_hours"] == "unknown"  # no calendar was given: unknown, not guessed


def test_missing_values_stay_unknown_not_zero(tmp_path):
    db = make_db()
    _, out = run(tmp_path, db, chain_with(FakeProvider(tokens=(0, 0))))
    cost = out["records"][0]["cost"]
    assert cost["input_tokens"] is None and cost["output_tokens"] is None and cost["usd"] is None
    sectors = out["records"][0]["assessment"]["sector_impact"]
    assert all(s["consensus"] == "unknown" for s in sectors)  # a sector no lens addressed is unknown


# --- models: honest, free tier only, disagreement kept ---------------------------------------------


def test_no_key_means_not_connected_and_the_event_stays_queued(tmp_path):
    db = make_db()
    led, out = run(tmp_path, db, no_models)
    for r in out["records"]:
        assert r["outcome"] == "failed" and r["assessment"] is None
        assert r["models"]["answered"] == [] and "claim" not in r["models"]
        assert r["cost"]["llm_calls"] == 0 and r["errors"]
    held = [q for q in led.pending() if q["attempts"] >= 1]
    assert len(held) == 2 and all(q["state"] == "pending" for q in held)  # kept for a later execution


def test_three_lenses_on_one_model_are_not_reported_as_three_models(tmp_path):
    db = make_db()
    _, out = run(tmp_path, db, chain_with(FakeProvider()))
    m = out["records"][0]["models"]
    assert (
        m["distinct_models_verified"] == 1
        and "3 of 3 lenses answered, on 1 distinct verified model" in m["claim"]
    )
    assert set(m["lenses"]) == {"news", "financial", "macro"}


def test_model_disagreement_is_recorded_not_hidden(tmp_path):
    db = make_db()
    split = FakeProvider({"news": "benefit", "financial": "neutral", "macro": "suffer"})
    _, out = run(tmp_path, db, chain_with(split))
    r = out["records"][0]
    assert r["model_disagreement"]["disagreement_found"] is True
    assert r["model_disagreement"]["conflicts"][0]["company"] == "HUBC"
    assert r["assessment"]["affected_companies"][0]["consensus"] == "mixed"


def test_every_attempt_is_a_recorded_call_and_transient_errors_are_retried(tmp_path):
    db = make_db()
    flaky = FakeProvider(fail_first=2)  # the first two requests fail, the third succeeds
    led, out = run(tmp_path, db, chain_with(flaky))
    r = out["records"][0]
    assert r["outcome"] == "assessed"
    outcomes = r["cost"]["calls_by_outcome"]
    assert outcomes["transient_error"] == 2 and outcomes["ok"] == 4 and r["cost"]["llm_calls"] == 6
    calls = led.snapshot()["calls"]
    assert all(
        {"vendor", "account", "model", "outcome", "ts", "ms", "event", "role", "exec"} <= set(c)
        for c in calls
    )
    assert r["cost"]["calls_by_account"] == {"groq#1": 6}


def test_there_is_no_paid_fallback_and_only_free_openrouter_models(tmp_path):
    led = cl.Ledger(tmp_path / "l.json")
    clock = lambda: NOW  # noqa: E731
    provider, notes = cn.build_chain("news", {"PSXNI_ANTHROPIC_API_KEY": "sk-x"}, led, {}, clock)
    assert provider is None and any("no free-tier" in n for n in notes)  # no Claude stub fallback
    legacy = {"PSXNI_COUNCIL_INDEPENDENT_MODELS": "off"}
    paid = {
        **legacy,
        "PSXNI_OPENROUTER_API_KEY": "k",
        "PSXNI_LLM_OPENROUTER_MODEL": "anthropic/claude-3-opus",
    }
    provider, notes = cn.build_chain("news", paid, led, {}, clock)
    assert provider is None and any("':free'" in n for n in notes)
    free = {**legacy, "PSXNI_OPENROUTER_API_KEY": "k"}
    provider, _ = cn.build_chain("news", free, led, {}, clock)
    assert provider is not None
    assert cn.configured_accounts({"PSXNI_GROQ_API_KEY_ONE": "a", "PSXNI_GROQ_API_KEY_TWO": "b"})["groq"] == 2


def test_the_ledger_quota_stops_an_account_before_it_makes_a_request(tmp_path, monkeypatch):
    posts = []

    def fake_post(url, headers, body, timeout):
        posts.append(url)
        return {
            "choices": [{"message": {"content": "{}"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }

    monkeypatch.setattr(llm, "_http_post", fake_post)
    led = cl.Ledger(tmp_path / "l.json")
    env = {"PSXNI_GROQ_API_KEY_ONE": "k1", "PSXNI_LLM_GROQ_RPD": "2", "PSXNI_LLM_GROQ_RPM": "0"}
    provider, _ = cn.build_chain("news", env, led, {"event": "ev"}, lambda: NOW)
    kw = {"system": "s", "user": "u", "json_schema": {}, "max_output_tokens": 10}
    provider.complete(**kw)
    provider.complete(**kw)
    with pytest.raises(llm.TransientProviderError, match="quota"):
        provider.complete(**kw)
    assert len(posts) == 2 and led.calls_since("groq", 1, NOW - timedelta(hours=1)) == 2


# --- time tags, window, report, the ten-headline pick ----------------------------------------------


class Cal:
    def day_type(self, day):
        return {"2026-11-21": "WEEKEND", "2026-11-18": "HOLIDAY"}.get(day, "WEEKDAY")

    def in_open_session(self, day, minute):
        return day == "2026-11-17" and 9 * 60 + 30 <= minute < 15 * 60 + 30


def test_weekend_holiday_and_after_hours_are_tagged_from_the_calendar():
    inside = cn.time_tags(datetime(2026, 11, 17, 6, 0, tzinfo=UTC), Cal())  # 11:00 PKT on a trading day
    after = cn.time_tags(datetime(2026, 11, 17, 13, 0, tzinfo=UTC), Cal())  # 18:00 PKT
    weekend = cn.time_tags(datetime(2026, 11, 21, 6, 0, tzinfo=UTC), Cal())
    holiday = cn.time_tags(datetime(2026, 11, 18, 6, 0, tzinfo=UTC), Cal())
    assert inside["after_hours"] is False and after["after_hours"] is True
    assert weekend["weekend"] is True and holiday["holiday"] is True
    assert cn.time_tags(NOW, None)["holiday"] == "unknown"


def test_the_window_covers_the_whole_pakistan_day_and_the_cursor_overlap():
    start = cn.window_start(NOW, None)
    assert start <= datetime(2026, 11, 16, 19, 0, tzinfo=UTC)  # local midnight is 19:00 UTC the day before
    cursor = cl.stamp(NOW - timedelta(hours=1))
    assert cn.window_start(NOW, cursor) == datetime(2026, 11, 16, 19, 0, tzinfo=UTC)


def test_seven_consecutive_days_including_weekends_show_in_the_report(tmp_path):
    led = cl.Ledger(tmp_path / "l.json")
    for d in range(7):
        day = NOW - timedelta(days=6 - d)
        tags = cn.time_tags(day, None)
        tags["day_type"] = "WEEKEND" if day.weekday() >= 5 else "WEEKDAY"
        led.log_execution({"ts": cl.stamp(day), "time": tags, "flagged": d})
        led.log_run(
            {
                "mode": "auto",
                "outcome": "assessed",
                "time": tags,
                "lenses_ok": 3,
                "errors": [],
                "disagreement": d == 2,
            }
        )
    text = cn.seven_day_report(led.snapshot(), NOW)
    assert "**7** of 7" in text and "weekend days covered: 2" in text and "council runs: 7" in text


def test_ten_headline_pick_is_flagged_events_plus_controls_with_each_rule_first():
    base = [
        ni.Headline("mettis", f"https://m/{i}", t, "2026-11-17T03:00:00Z") for i, (t, _) in enumerate(STORIES)
    ]
    extra = [
        ni.Headline("brecorder", "https://b/1", "Lucky Cement Limited", "2026-11-17T03:00:00Z"),
        ni.Headline("brecorder", "https://b/2", "OGDC signs a routine agreement", "2026-11-17T03:01:00Z"),
    ]
    evs = ni.cluster(base + extra, (), VOCAB)
    ni.classify(VOCAB, evs)
    picked = cn.pick_ten(evs, NOW, 10)
    labels = [lab for _, lab in picked]
    assert len(picked) <= 10 and labels.count("flagged") == 5 and labels.count("control") == 2
    first_rules = {h.rule for e, _ in picked[:4] for h in e.hits}
    assert {7, 1, 2, 5} <= first_rules


# --- real headlines (copied from the live table on 17 Nov 2026), no database writes ----------------


REAL = [
    ("NBP’s profit falls 29% in the third quarter as income shrinks on both fronts", "profit", {1}),
    ("Govt cuts petrol, high-speed diesel price by Rs2", "tribune_business", {2}),
    ("SBP projects 3.5-4.5% GDP growth for FY27", "mettis", {2}),
    ("Oil and gas: FBR asks 13 E&P cos to issue digital ST invoices", "brecorder", {5}),
    ("Punjab Oil Mills cut its costs. Its taxes ate the profit", "profit", {1}),
    (
        "Supreme Court rules in favour of Attock Refinery in sales tax dispute over crude oil processing",
        "profit",
        {9},  # was a documented gap before rule 9 (corporate action or legal decision)
    ),
    ("Kohat Cement Company Limited", "brecorder", set()),
    ("‘PPP lives in the hearts of the people’: Faryal", "brecorder", set()),
]


def test_real_headlines_are_classified_as_expected_without_touching_the_database():
    db = cn.ReadOnlyDB(make_db())
    vocab = bnc.load_vocabulary(db)
    heads = [
        ni.Headline(src, f"https://real/{i}", title, "2026-11-17T03:00:00Z")
        for i, (title, src, _) in enumerate(REAL)
    ]
    evs = ni.cluster(heads, (), vocab)
    ni.classify(vocab, evs)
    got = {e.title: {h.rule for h in e.hits} for e in evs}
    for title, _src, expected in REAL:
        assert expected <= got[title], title
        if not expected:
            assert got[title] == set(), title
    assert got[REAL[4][0]] == {1}  # 'Oil' in the company name and 'taxes' are not policy news


# --- all seven rules reach the council through one execution; retries across executions -----------------


def run_with_signals(tmp_path, db, signals, chain_for, led=None, now=NOW, exec_id="s1"):
    led = led or cl.Ledger(tmp_path / "ledger.json")
    out = cn.execution(
        db=cn.ReadOnlyDB(db),
        env={},
        ledger=led,
        now=now,
        exec_id=exec_id,
        vocab=VOCAB,
        signals_for=lambda d, n: (signals, {"baseline": "available"}),
        build_pack=fake_pack,
        calendar=None,
        chain_for=chain_for,
    )
    return led, out


def test_baseline_signals_and_concentration_become_queued_council_events(tmp_path):
    db = make_db()
    db.execute("DELETE FROM news_item")  # a quiet day apart from three distinct Hub Power stories
    for i, title in enumerate(
        (
            "Hub Power board meets on December 5",
            "Hub Power eyes BYD assembly plant",
            "Hub Power names new CFO",
        )
    ):
        at = (NOW - timedelta(minutes=20 + i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        db.execute(
            "INSERT INTO news_item VALUES (?, ?, ?, ?, NULL, NULL, ?)",
            ("mettis", f"https://h.pk/{i}", title, at, at),
        )
    signals = [
        {
            "company": "LUCK",
            "fact_text": "LUCK: 6 stories in 7 days, 31% of tracked news against 8%",
            "source_url": "https://x/1",
            "value": "6",
        },
        {
            "company": "SECTOR:CEMENT",
            "fact_text": "SECTOR:CEMENT: 9 stories, 22% against 6%",
            "source_url": "https://x/2",
            "value": "9",
        },
    ]
    led, out = run_with_signals(tmp_path, db, signals, chain_with(FakeProvider()))
    queue = led.snapshot()["queue"]
    rules = {q["event_id"]: q["rules"] for q in queue}
    kinds = {q["kind"]: q["rules"] for q in queue}
    assert kinds["concentration"] == [4] and rules["sig-LUCK-2026-11-17"] == [3]
    assert rules["sig-SECTOR:CEMENT-2026-11-17"] == [6]
    assert (
        out["summary"]["flagged"] == 3 and out["summary"]["ran"] == 2
    )  # two now, one waits for the next execution
    assert out["summary"]["baseline"]["baseline"] == "available"


def test_a_failed_run_is_retried_by_a_later_execution_and_counts_against_the_day(tmp_path):
    db = make_db()
    led, first = run(tmp_path, db, no_models)  # nothing answers: two attempts, both failed
    assert [r["outcome"] for r in first["records"]] == ["failed", "failed"]
    led, second = run(tmp_path, db, chain_with(FakeProvider()), NOW + timedelta(minutes=30), "e2", led)
    retried = {r["event"]["key"]: r["event"]["attempt"] for r in second["records"]}
    assert set(retried) == {r["event"]["key"] for r in first["records"]} and set(retried.values()) == {2}
    assert (
        led.runs_on(ni.local_day(NOW)) == 4
    )  # every started run is charged to the daily cap, success or not


def test_focus_picks_only_events_that_name_the_chosen_company_best_corroborated_first():
    from types import SimpleNamespace as NS

    from engines import council_news as cn

    def ev(eid, companies, sources, first):
        members = [NS(source=s, published_at=first) for s in sources]
        return NS(event_id=eid, companies=companies, members=members, first_seen=first)

    events = [
        ev("a", ["MARI"], ["profit"], "2026-11-13T07:08"),
        ev("b", ["OGDC"], ["profit", "dawn_business"], "2026-11-14T07:08"),
        ev("c", ["MARI", "OGDC"], ["profit", "brecorder", "mettis"], "2026-11-12T07:08"),
        ev("d", ["MARI"], ["profit"], "2026-11-16T07:08"),
    ]
    picked = cn.pick_focus(events, None, {"MARI"}, 3)
    assert [e.event_id for e, _ in picked] == ["c", "d", "a"]  # three outlets, then newest first
    assert {label for _, label in picked} == {"focus"}
    assert cn.pick_focus(events, None, {"MARI"}, 1)[0][0].event_id == "c"
    assert cn.pick_focus(events, None, {"ZZZ"}, 3) == []
    assert cn.pick_focus(events, None, set(), 3) == []


def test_mapped_first_keeps_the_pack_slots_for_facts_a_lens_can_weigh():
    from scripts import council_run as cr

    assert cr.kind_for("price.move") is None and cr.kind_for("technical.wyckoff") is None
    assert cr.kind_for("results.quarterly") == "figure" and cr.kind_for("fundamentals.market_cap") == "figure"
    # the owner allowed Investify's Highlights text into the council's pack on 2026-11-17 (private use)
    assert cr.kind_for("announcement_highlights") == "announcement"


def test_recent_highlights_get_reserved_slots_even_when_newer_rows_fill_the_cut():
    from pathlib import Path

    from database.connection import SQLiteDatabase
    from scripts import council_run as cr

    db = SQLiteDatabase(":memory:")
    lib = Path(__file__).resolve().parents[1] / "database" / "library" / "0002_research_fact.sql"
    for stmt in "\n".join(ln.split("--", 1)[0] for ln in lib.read_text("utf-8").splitlines()).split(";"):
        if stmt.strip():
            db.execute(stmt)

    def add(topic, text, day, source="synthetic"):
        db.execute(
            "INSERT INTO research_fact (company, topic, fact_text, value, unit, period, source_name, "
            "source_url, source_date, as_of, confidence, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("MARI", topic, text, None, None, None, source, None, day, day, "fact", "2026-11-17T00:00:00Z"),
        )

    for n in range(60):  # newer rows that fill the 40-row cut
        text = f"metric {n}"
        add(f"fundamentals.m{n}", text, "2026-11-17")
    for n in range(8):  # older Highlights
        text = f"2026-11-13: highlight {n}"
        add(
            "announcement_highlights", text, "2026-11-13", "Investify (investify.pk), announcement highlights"
        )
    pack = cr.build_pack("event", ["MARI"], db, mapped_first=True)
    texts = [str(i.text) for i in pack.items if "announcement highlights" in str(i.source_name)]
    assert len(texts) == cr.RESERVED_HIGHLIGHTS == 6
    assert all("highlight" in t for t in texts)


def test_each_analyst_is_pinned_to_a_different_model_family_with_no_cross_family_fallback(tmp_path):
    led = cl.Ledger(tmp_path / "l.json")
    clock = lambda: NOW  # noqa: E731
    env = {"PSXNI_GROQ_API_KEY_ONE": "g1", "PSXNI_GEMINI_API_KEY_ONE": "m1", "PSXNI_OPENROUTER_API_KEY": "o1"}
    models = {}
    for role in ("news", "financial", "macro"):
        provider, notes = cn.build_chain(role, env, led, {}, clock)
        assert provider is not None and any("no cross-family fallback" in n for n in notes)
        models[role] = cn.INDEPENDENT_MODELS[role]
    assert len({m for _v, m in models.values()}) == 3  # three different models
    assert {v for v, _m in models.values()} == {"groq", "gemini"}
    # a pinned vendor with no key leaves the analyst unavailable instead of borrowing another family
    provider, notes = cn.build_chain("macro", {"PSXNI_GROQ_API_KEY_ONE": "g1"}, led, {}, clock)
    assert provider is None and any("pinned gemini" in n for n in notes)
