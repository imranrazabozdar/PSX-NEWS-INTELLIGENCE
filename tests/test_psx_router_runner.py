"""Safety rules of the document router and the polite node runner (no network access in these tests)."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from engines import document_router as dr
from engines import termux_node_runner as node
from engines.psx_feed_parser import StatutoryAnnouncement


def _ann(title="Board Meeting to consider dividend", doc_id=None, symbol="LUCK"):
    return StatutoryAnnouncement(
        date=date(2026, 11, 11),
        time=time(10, 5),
        symbol=symbol,
        company_name="Lucky Cement Limited",
        category=None,
        title=title,
        doc_id=doc_id,
    )


def test_no_edge_url_is_built_without_a_feed_disclosed_doc_id():
    decision = dr.route(_ann(doc_id=None), ir_registry={})
    assert decision.url is None
    assert decision.source is dr.Source.UNRESOLVED


def test_edge_url_only_for_a_disclosed_doc_id_and_is_polite():
    decision = dr.route(_ann(doc_id=123456), ir_registry={})
    assert decision.url == "https://dps.psx.com.pk/download/document/123456.pdf"
    assert decision.source is dr.Source.EXCHANGE_EDGE
    assert decision.politeness_required is True


def test_heavy_report_goes_to_ir_portal_or_stays_unresolved_never_the_edge():
    heavy = _ann(title="Annual Report 2026", doc_id=999)
    assert dr.route(heavy, ir_registry={}).source is dr.Source.UNRESOLVED
    assert dr.route(heavy, ir_registry={}).url is None
    ok = dr.route(heavy, ir_registry={"LUCK": "https://example-ir.invalid/investors"})
    assert ok.source is dr.Source.CORPORATE_IR


def test_build_url_refuses_invented_ids():
    for bad in (0, -1, "123", True, False, None, 1.5):
        with pytest.raises(ValueError):
            dr.build_exchange_document_url(bad)


def test_mirror_resolver_never_returns_a_psx_edge_link(tmp_path):
    cfg = node.Config(
        feed_url="https://feed.example.invalid/a.zip",
        cloud_endpoint="https://ingest.example.invalid/x",
        state_db=str(tmp_path / "s.sqlite3"),
        mirror_api_url=None,
    )
    resolver = node.TelegramMirrorResolver(cfg, session=None)
    resolver._index = {("LUCK", "2026-11-11"): {"pdf_url": "https://dps.psx.com.pk/download/document/1.pdf"}}
    assert resolver(_ann()) is None


def test_runner_refuses_non_http_urls():
    with pytest.raises(ValueError):
        node._require_http("file:///etc/passwd")
    node._require_http("https://example.invalid/feed")


def test_seen_store_dedups_and_keys_without_doc_id(tmp_path):
    store = node.SeenStore(str(tmp_path / "seen.sqlite3"))
    try:
        a = _ann()
        assert store.is_new(a)
        store.mark(a)
        assert not store.is_new(a)
        assert store.key_for(a).startswith("txt:")
        assert store.key_for(_ann(doc_id=42)) == "doc:42"
    finally:
        store.conn.close()


def test_trading_hours_gate():
    pkt = ZoneInfo("Asia/Karachi")
    assert node.within_trading_hours(datetime(2026, 11, 11, 10, 0, tzinfo=pkt))  # Wednesday
    assert not node.within_trading_hours(datetime(2026, 11, 11, 17, 0, tzinfo=pkt))  # after close
    assert not node.within_trading_hours(datetime(2026, 11, 14, 10, 0, tzinfo=pkt))  # Saturday


def test_a_boolean_is_never_a_document_id():
    """bool is a subclass of int; True must not become document/1.pdf or document/True.pdf."""
    with pytest.raises(ValueError):
        dr.build_exchange_document_url(True)
    with pytest.raises(ValueError):
        StatutoryAnnouncement(
            date=date(2026, 11, 11),
            time=None,
            symbol="LUCK",
            company_name=None,
            category=None,
            title="x",
            doc_id=True,
        )
