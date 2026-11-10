"""Synthetic, reproducible extraction-quality evaluation (see engines/evaluation.py). No model calls."""

from __future__ import annotations

import json
import pathlib

import pytest

from database import seed_loader
from database.connection import SQLiteDatabase
from database.migrate import migrate
from engines import evaluation as ev
from engines.similarity import Doc

SAMPLE_PATH = pathlib.Path(__file__).parent / "fixtures" / "eval_news_sample.json"
SAMPLE = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def db():
    d = SQLiteDatabase()
    migrate(d)
    seed_loader.load(d)
    yield d
    d.close()


def _known(db):
    return {r["value"] for r in db.execute(
        "SELECT value FROM company_identifiers WHERE id_type = 'psx_ticker' AND valid_to IS NULL")}


def test_precision_and_recall_are_none_when_undefined_never_zero():
    assert ev.pr(0, 0, 0) == {"tp": 0, "fp": 0, "fn": 0, "precision": None, "recall": None}
    assert ev.pr(0, 2, 0)["precision"] == 0.0 and ev.pr(0, 2, 0)["recall"] is None
    assert ev.pr(3, 1, 1) == {"tp": 3, "fp": 1, "fn": 1, "precision": 0.75, "recall": 0.75}


def test_quote_grounding_is_verbatim_after_whitespace_and_case_normalisation():
    for case in SAMPLE["quotes"]:
        got = ev.quote_grounding([case["quote"]], case["source"])
        assert (got["grounded"] == 1) is case["expect_grounded"], case


def test_an_invented_number_in_a_quote_is_ungrounded():
    source = "OGDC announces final cash dividend of Rs 5 per share"
    result = ev.quote_grounding(["dividend of Rs 9 per share"], source)
    assert result == {"quotes": 1, "grounded": 0, "ungrounded": 1, "rate": 0.0}


def test_empty_quotes_have_no_rate():
    assert ev.quote_grounding([], "anything")["rate"] is None


def test_invented_tickers_are_flagged_against_the_master(db):
    assert ev.invented_tickers(["OGDC", "XYZQ"], _known(db)) == ["XYZQ"]
    assert ev.invented_tickers([], _known(db)) == []


def test_entity_matching_reports_precision_recall_and_invented_tickers(db):
    result = ev.entity_eval(SAMPLE["entities"], lambda t: ev.direct_companies_in_text(db, t), _known(db))
    assert result["cases"] == len(SAMPLE["entities"])
    assert result["disagreements"] == []                 # every hand label is matched
    assert result["precision"] == 1.0 and result["recall"] == 1.0
    assert result["invented_tickers"] == []


def test_a_wrong_resolver_is_measured_not_hidden(db):
    """The harness must report disagreements. A resolver that always returns OGDC gets penalised."""
    result = ev.entity_eval(SAMPLE["entities"], lambda t: {"OGDC"}, _known(db))
    assert result["precision"] < 1.0 and result["fp"] > 0
    assert result["disagreements"]


def test_near_duplicate_detection_matches_the_labelled_pairs_only(db):
    docs = [Doc(item_id=i["id"], title=i["title"], text=i["text"]) for i in SAMPLE["dedup"]["items"]]
    expected = {frozenset(p) for p in SAMPLE["dedup"]["expected_duplicate_pairs"]}
    result = ev.dedup_eval(docs, expected)
    assert result["precision"] == 1.0 and result["recall"] == 1.0
    assert result["false_positive_pairs"] == [] and result["missed_pairs"] == []


def test_usefulness_needs_a_grounded_quote_and_a_match():
    result = ev.usefulness_rate(SAMPLE["usefulness"])
    assert result["records"] == 4
    assert result["useful"] == 2          # the 1st (quote + direct) and the 3rd (quote + sector) only
    assert result["useful_rate"] == 0.5


def test_usefulness_with_no_records_has_no_rate():
    assert ev.usefulness_rate([])["useful_rate"] is None


def test_the_evaluation_is_deterministic(db):
    def run():
        return ev.entity_eval(SAMPLE["entities"], lambda t: ev.direct_companies_in_text(db, t), _known(db))
    assert run() == run()


def test_controlled_report_combines_every_measure_and_changes_nothing(db):
    before = db.execute("SELECT COUNT(*) AS n FROM company_identifiers")[0]["n"]
    report = ev.controlled_report(db, SAMPLE)
    assert report["eval_version"] == ev.VERSION
    assert report["entities"]["invented_tickers"] == []
    assert report["dedup"]["precision"] == 1.0
    assert report["quotes"]["quotes"] == 3
    assert report["usefulness"]["records"] == 4
    assert report["changed_records"] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM company_identifiers")[0]["n"] == before
