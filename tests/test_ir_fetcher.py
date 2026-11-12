"""IR report fetcher: fiscal-aware classification, extraction, scope, dedup, provenance, politeness, the
manual
import path, the registry, and vault-only storage.

Fully offline. Every network call goes through a fake transport. Fixtures are point-in-time excerpts of real
company pages (see the headers in tests/fixtures/ir/) and one clearly labelled synthetic page.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from engines import ir_fetcher as f
from engines.document_intake import IntakeError, vault_dir
from tests.pdf_fixture_builder import write_pdf

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "tests" / "fixtures" / "ir"
TODAY = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
PDF = b"%PDF-1.4\n% synthetic test document\n%%EOF\n"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the IR fetcher must not open a socket in tests")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


class FakeClock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class FakeTransport:
    """Serves queued responses per URL, or a default; records every call with its headers."""

    def __init__(self, routes=None, default=(404, {}, b"")):
        self.routes = {k: list(v) for k, v in (routes or {}).items()}
        self.default = default
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers):
        self.calls.append((url, dict(headers)))
        queue = self.routes.get(url)
        if queue:
            return queue.pop(0) if len(queue) > 1 else queue[0]
        return self.default

    def urls(self):
        return [u for u, _ in self.calls]


def robots(text=b"User-agent: *\nAllow: /\n"):
    return (200, {"content-type": "text/plain"}, text)


def html(name):
    return (FX / name).read_bytes()


def page_route(url, body, robots_text=None):
    host = "https://" + url.split("/")[2]
    return {f"{host}/robots.txt": [robots(robots_text) if robots_text else robots()], url: [(200, {}, body)]}


def entry_for(
    symbol="HUBC", url="https://hubpower.com/investors/", hosts=("hubpower.com",), fye="06-30", **kw
):
    return f.IrEntry(
        symbol=symbol,
        name=symbol,
        url=url,
        status=kw.pop("status", "live"),
        fye=fye,
        allowed_hosts=hosts,
        **kw,
    )


def client_for(transport, clock=None):
    clock = clock or FakeClock()
    return f.PoliteClient(transport=transport, clock=clock, sleep=clock.sleep, min_interval_s=10.0)


# ================================================================== registry


def test_the_registry_statuses_match_the_reachability_results():
    reg = f.load_registry()
    assert set(reg) == {"OGDC", "UBL", "POL", "NRL", "ATRL", "PPL", "HUBC", "PSO", "LUCK"}
    assert reg["NRL"].status == "needs_manual"  # shadow-corrupted text layer; figures keyed by hand
    assert reg["HUBC"].status == "live"  # annual PDF has a text layer; quarterly periods are needs_OCR
    assert reg["PSO"].status == "needs_OCR"  # no text layer (vector-outline)
    assert reg["LUCK"].status == "needs_manual"  # report host robots-disallowed
    assert reg["ATRL"].status == "todo_unverified"
    assert reg["POL"].status == "todo_unreachable"  # the TLS chain failed locally: an environment limit
    assert reg["PPL"].status == "blocked_by_site"  # Cloudflare challenge
    assert reg["OGDC"].status == "manual_import" and reg["UBL"].status == "manual_import"


def test_each_entry_has_its_fiscal_year_end_and_manual_entries_may_omit_a_url():
    reg = f.load_registry()
    assert reg["OGDC"].fye == "06-30" and reg["PSO"].fye == "06-30"
    assert reg["UBL"].fye == "12-31" and reg["UBL"].url is None
    assert all(e.url is None or e.url.startswith("https://") for e in reg.values())


def test_financials_psx_is_recorded_as_a_candidate_not_a_company():
    import json as _json

    data = _json.loads((ROOT / "config" / "ir_registry.json").read_text(encoding="utf-8"))
    assert "financials.psx.com.pk" in data["fallback_candidates"]
    assert "financials.psx.com.pk" not in data["companies"]


def test_a_non_fetchable_entry_is_never_fetched(tmp_path):
    t = FakeTransport()
    res = f.run_company(
        entry_for(status="blocked_by_site"),
        now=TODAY,
        client=client_for(t),
        vault=tmp_path,
        manifest=f.Manifest(tmp_path),
    )
    assert res.status == "skipped" and t.calls == []


def test_the_registry_rejects_bad_statuses_urls_and_year_ends(tmp_path):
    bad = tmp_path / "r.json"
    bad.write_text(
        json.dumps({"companies": {"X": {"ir_reports_url": "https://x.example/", "status": "maybe"}}})
    )
    with pytest.raises(ValueError, match="unknown status"):
        f.load_registry(bad)
    bad.write_text(
        json.dumps({"companies": {"X": {"ir_reports_url": "http://x.example/", "status": "live"}}})
    )
    with pytest.raises(ValueError, match="https"):
        f.load_registry(bad)
    bad.write_text(
        json.dumps(
            {"companies": {"X": {"ir_reports_url": "https://x.example/", "status": "live", "fye": "02-30"}}}
        )
    )
    with pytest.raises(ValueError):
        f.load_registry(bad)
    bad.write_text(json.dumps({"companies": {"X": {"ir_reports_url": None, "status": "live"}}}))
    with pytest.raises(ValueError, match="manual_import"):
        f.load_registry(bad)


# ================================================================== classification (fiscal-aware)


@pytest.mark.parametrize(
    "text,fye,expected",
    [
        ("Annual Report 2026", "06-30", ("annual_report", date(2026, 6, 30), "FY2026", 2026)),
        (
            "HUBCO-Integrated-Annual-Report-2026.pdf",
            "06-30",
            ("annual_report", date(2026, 6, 30), "FY2026", 2026),
        ),
        ("1st Quarterly Report 2027", "06-30", ("quarterly", date(2026, 9, 30), "Q1 FY2027", 2027)),
        ("Q3-FY26.pdf", "06-30", ("quarterly", date(2026, 3, 31), "Q3 FY2026", 2026)),
        (
            "Third_Quarter_Report_March_31_2026_57af.pdf",
            "06-30",
            ("quarterly", date(2026, 3, 31), "Q3 FY2026", 2026),
        ),
        ("Nine Months Report 2026", "06-30", ("quarterly", date(2026, 3, 31), "Q3 FY2026", 2026)),
        (
            "Condensed Interim Financial Statements 9MFY24",
            "06-30",
            ("quarterly", date(2024, 3, 31), "Q3 FY2024", 2024),
        ),
        ("Half Yearly Report 2025", "06-30", ("half_year", date(2024, 12, 31), "H1 FY2025", 2025)),
        ("Financial Statements 2025", "06-30", ("financial_statements", date(2025, 6, 30), "FY2025", 2025)),
        # the task's example: a Dec-31 half-year for a June year-end company is H1 FY2026
        (
            "Half Yearly Report for the Period Ended December 31, 2025",
            "06-30",
            ("half_year", date(2025, 12, 31), "H1 FY2026", 2026),
        ),
        # a December year-end company: the same calendar date is the full year
        ("Annual Report 2025", "12-31", ("annual_report", date(2025, 12, 31), "FY2025", 2025)),
        # refused, not guessed
        ("June2022.pdf", "06-30", None),
        ("HUBCO-AR-Final-Low-Res.pdf", "06-30", None),
        ("Quarterly report", "06-30", None),
        ("Half Yearly Report December 31 2025", "12-31", None),  # 31 Dec is the year end here, not a half
    ],
)
def test_classification_derives_the_period_end_and_fiscal_label(text, fye, expected):
    assert f.classify(text, fye) == expected


def test_an_explicit_period_end_outranks_the_printed_year():
    assert f.classify("Quarterly Report 2026 for the quarter ended 30 September 2025", "06-30") == (
        "quarterly",
        date(2025, 9, 30),
        "Q1 FY2026",
        2026,
    )


# ================================================================== extraction from the real fixtures


def test_hub_power_fixture_yields_its_annual_reports_and_no_guesses():
    e = entry_for()
    cands = f.extract_candidates(html("hubc_investors_excerpt.html").decode(), e.url, e.allowed_hosts, e.fye)
    got = {(c.report_type, c.period_end, c.fiscal_label) for c in cands}
    assert ("annual_report", "2026-06-30", "FY2026") in got
    assert ("annual_report", "2025-06-30", "FY2025") in got
    assert len(cands) == 2
    assert [c.fiscal_label for c in f.scoped(cands, e, today=TODAY)] == ["FY2026"]


def test_psx_listed_pso_fixture_classifies_quarters_and_annuals_and_drops_summaries():
    e = entry_for("PSO", "https://www.psopk.com/en/investors/financial", ("psopk.com",))
    cands = f.extract_candidates(html("pso_financial_excerpt.html").decode(), e.url, e.allowed_hosts, e.fye)
    kept = {(c.fiscal_label, c.pdf_url.rsplit("/", 1)[-1]) for c in f.scoped(cands, e, today=TODAY)}
    assert ("Q1 FY2027", "Q1FY27.pdf") in kept
    assert ("Q3 FY2026", "Q3-FY26.pdf") in kept
    assert ("Q2 FY2026", "Q2-FY26.pdf") in kept
    assert ("Q1 FY2026", "Q1-FY26.pdf") in kept
    assert len(kept) == 4
    assert not any("Summary" in name for _, name in kept)  # the summary is excluded
    assert not any(label.endswith(("2025", "2024", "2019")) for label, _ in kept)  # outside the fiscal window


def test_lucky_fixture_finds_the_pdfs_embedded_in_the_page_data():
    e = entry_for(
        "LUCK",
        "https://www.lucky-cement.com/en/corporate/investor-relations/financial-reports",
        ("lucky-cement.com",),
    )
    cands = f.extract_candidates(html("luck_reports_excerpt.html").decode(), e.url, e.allowed_hosts, e.fye)
    assert all(c.pdf_url.startswith("https://assets.lucky-cement.com/") for c in cands)
    kept = {c.fiscal_label for c in f.scoped(cands, e, today=TODAY)}
    assert kept == {"Q3 FY2026", "Q1 FY2026", "H1 FY2026"}  # the half-year to 31 Dec 2025 is H1 FY2026


# ================================================================== synthetic edge cases

SYN = entry_for("SYN", "https://issuer.example/reports", ("issuer.example",))


def _syn_candidates(entry=SYN):
    return f.extract_candidates(
        html("synthetic_company_reports.html").decode(), entry.url, entry.allowed_hosts, entry.fye
    )


def test_synthetic_page_edge_cases_are_handled():
    cands = _syn_candidates()
    urls = [c.pdf_url for c in cands]
    assert (
        urls.count("https://issuer.example/reports/AR2026.pdf") == 1
    )  # duplicate anchor and JSON: one entry
    assert not any("cdn.other.example" in u for u in urls)  # off-host links are ignored
    assert not any(u.endswith(".html") for u in urls)  # non-PDF links are ignored
    assert "https://issuer.example/reports/q1.pdf?v=2" in urls  # the query string is part of the URL
    kept = {(c.report_type, c.fiscal_label) for c in f.scoped(cands, SYN, today=TODAY)}
    assert kept == {
        ("annual_report", "FY2026"),
        ("half_year", "H1 FY2026"),
        ("quarterly", "Q1 FY2026"),
        ("quarterly", "Q3 FY2026"),
    }


def test_the_summary_notice_undated_and_old_items_are_out_of_scope():
    kept_urls = {c.pdf_url for c in f.scoped(_syn_candidates(), SYN, today=TODAY)}
    assert "https://issuer.example/reports/ar26-summary.pdf" not in kept_urls
    assert "https://issuer.example/reports/ar-old.pdf" not in kept_urls  # FY2019
    assert "https://issuer.example/reports/AR2023.pdf" not in kept_urls  # FY2023 is outside the window
    assert "https://issuer.example/reports/undated.pdf" not in kept_urls
    assert "https://issuer.example/reports/fs25.pdf" not in kept_urls  # FY2025 is before FY2026


def test_the_scope_window_and_the_type_filter_are_configurable():
    cands = _syn_candidates()
    one_year = {c.fiscal_label for c in f.scoped(cands, SYN, today=TODAY, years_back=1)}
    assert "FY2026" not in one_year and one_year <= {
        "FY2027",
        "FY2028",
    }  # only the current fiscal year onward
    annual_only = entry_for(
        "SYN", "https://issuer.example/reports", ("issuer.example",), report_types=("annual_report",)
    )
    assert {c.report_type for c in f.scoped(cands, annual_only, today=TODAY)} == {"annual_report"}


# ================================================================== the run: dedup, provenance, storage


def _hub_transport():
    routes = page_route("https://hubpower.com/investors/", html("hubc_investors_excerpt.html"))
    routes["https://hubpower.com/wp-content/uploads/2026/09/HUBCO-Integrated-Annual-Report-2026.pdf"] = [
        (200, {}, PDF)
    ]
    return FakeTransport(routes)


def _run(transport, vault, *, manifest=None, entry=None, max_downloads=10):
    e = entry or entry_for()
    m = manifest or f.Manifest(vault)
    return (
        f.run_company(
            e, now=TODAY, client=client_for(transport), vault=vault, manifest=m, max_downloads=max_downloads
        ),
        m,
    )


def test_pdfs_are_stored_in_the_vault_with_full_provenance(tmp_path):
    res, m = _run(_hub_transport(), tmp_path)
    assert res.status == "ok" and len(res.stored) == 1
    row = m.rows[0]
    assert row["symbol"] == "HUBC" and row["report_type"] == "annual_report"
    assert row["period_end"] == "2026-06-30" and row["fiscal_label"] == "FY2026"
    assert row["fiscal_year"] == 2026 and row["fiscal_year_end"] == "06-30" and row["source"] == "ir_fetch"
    assert row["source_page_url"] == "https://hubpower.com/investors/"
    assert row["pdf_url"].endswith("HUBCO-Integrated-Annual-Report-2026.pdf")
    assert row["sha256"] == hashlib.sha256(PDF).hexdigest() and row["bytes"] == len(PDF)
    assert row["retrieved_at"] == "2026-11-12T12:00:00Z"
    stored = tmp_path / row["vault_path"]
    assert stored.read_bytes() == PDF and stored.parent.name == "HUBC"
    assert stored.name == "annual_report_2026-06-30.pdf"  # keyed by the stated period-end date


def test_an_existing_vault_file_is_never_downloaded_again(tmp_path):
    _run(_hub_transport(), tmp_path)
    t2 = _hub_transport()
    res2, _ = _run(t2, tmp_path)  # a fresh manifest object reads the manifest from disk
    assert res2.stored == [] and res2.duplicates == 1
    assert not any(u.endswith(".pdf") for u in t2.urls())  # no PDF request the second time


def test_a_pdf_with_a_known_hash_under_a_new_url_is_not_stored_twice(tmp_path):
    _, m = _run(_hub_transport(), tmp_path)
    before = len(list(tmp_path.rglob("*.pdf")))
    routes = page_route("https://hubpower.com/investors/", html("hubc_investors_excerpt.html"))
    routes["https://hubpower.com/wp-content/uploads/2026/09/HUBCO-Integrated-Annual-Report-2026.pdf"] = [
        (200, {}, PDF)
    ]
    res, _ = _run(FakeTransport(routes), tmp_path, manifest=f.Manifest(tmp_path))
    assert len(list(tmp_path.rglob("*.pdf"))) == before and res.duplicates >= 1


def test_a_response_that_is_not_a_pdf_is_rejected(tmp_path):
    routes = page_route("https://hubpower.com/investors/", html("hubc_investors_excerpt.html"))
    routes["https://hubpower.com/wp-content/uploads/2026/09/HUBCO-Integrated-Annual-Report-2026.pdf"] = [
        (200, {"content-type": "text/html"}, b"<html>not a pdf</html>")
    ]
    res, _ = _run(FakeTransport(routes), tmp_path)
    assert len(res.rejected) == 1 and "not a PDF" in res.rejected[0]
    assert list(tmp_path.rglob("*.pdf")) == []


def test_a_name_clash_keeps_both_documents(tmp_path):
    # two different PDFs both labelled Q1 FY2026 (the same period end): the second keeps a hash-suffixed name
    routes = page_route("https://issuer.example/reports", html("synthetic_company_reports.html"))
    routes["https://issuer.example/reports/q1.pdf?v=2"] = [(200, {}, PDF + b"a")]
    routes["https://issuer.example/reports/q1-2026.pdf"] = [(200, {}, PDF + b"b")]
    _run(FakeTransport(routes), tmp_path, entry=SYN)
    names = sorted(p.name for p in (tmp_path / "SYN").glob("*.pdf"))
    assert len(names) == 2  # the other in-scope links have no route here, so they are rejected, not stored
    assert "quarterly_2025-09-30.pdf" in names
    assert any(n.startswith("quarterly_2025-09-30_") for n in names)


def test_the_number_of_downloads_per_run_is_capped(tmp_path):
    res, _ = _run(_hub_transport(), tmp_path, max_downloads=0)
    assert res.stored == []


# ================================================================== politeness


def test_every_request_carries_the_same_honest_identity_with_a_contact(tmp_path):
    t = _hub_transport()
    _run(t, tmp_path)
    assert {h["User-Agent"] for _, h in t.calls} == {f.USER_AGENT}
    ua = f.USER_AGENT
    assert "contact: https://" in ua and "public investor-relations" in ua
    for spoof in ("Mozilla", "Chrome", "Safari", "AppleWebKit", "Firefox", "Edg/"):
        assert spoof not in ua


def test_robots_txt_is_fetched_first_and_its_rules_are_respected(tmp_path):
    routes = page_route(
        "https://hubpower.com/investors/",
        html("hubc_investors_excerpt.html"),
        robots_text=b"User-agent: *\nDisallow: /wp-content/\n",
    )
    t = FakeTransport(routes)
    res, _ = _run(t, tmp_path)
    assert t.urls()[0] == "https://hubpower.com/robots.txt"
    assert not any("/wp-content/" in u for u in t.urls())  # disallowed PDFs are never requested
    assert res.stored == [] and len(res.rejected) == 1
    assert "robots.txt disallows" in res.rejected[0]


def test_a_missing_robots_file_allows_and_an_unreadable_one_denies(tmp_path):
    t = FakeTransport(
        {
            "https://hubpower.com/robots.txt": [(404, {}, b"")],
            "https://hubpower.com/investors/": [(200, {}, html("hubc_investors_excerpt.html"))],
        }
    )
    res, _ = _run(t, tmp_path)
    assert res.status == "ok" and res.in_scope == 1
    t2 = FakeTransport({"https://hubpower.com/robots.txt": [(500, {}, b"")]})
    res2, _ = _run(t2, tmp_path / "v2", manifest=None)
    assert res2.status == "failed" and t2.urls() == ["https://hubpower.com/robots.txt"]


def test_the_per_host_minimum_interval_is_enforced(tmp_path):
    clock = FakeClock()
    t = _hub_transport()
    client = client_for(t, clock)
    sent_at: list[float] = []
    original = t.__call__

    def timed(url, headers):
        sent_at.append(clock.now)
        return original(url, headers)

    client.transport = timed
    f.run_company(entry_for(), now=TODAY, client=client, vault=tmp_path, manifest=f.Manifest(tmp_path))
    assert len(sent_at) >= 3  # robots, page and PDF
    gaps = [b - a for a, b in zip(sent_at, sent_at[1:], strict=False)]
    assert all(g >= 10.0 for g in gaps)


def test_a_429_stops_the_host_with_no_retry_and_honours_retry_after(tmp_path):
    clock = FakeClock()
    t = FakeTransport(
        {
            "https://hubpower.com/robots.txt": [robots()],
            "https://hubpower.com/investors/": [(429, {"retry-after": "900"}, b"")],
        }
    )
    client = client_for(t, clock)
    res = f.run_company(entry_for(), now=TODAY, client=client, vault=tmp_path, manifest=f.Manifest(tmp_path))
    assert res.status == "failed" and "HTTP 429" in res.reason
    assert t.urls().count("https://hubpower.com/investors/") == 1  # no same-window retry
    with pytest.raises(f.HostUnavailable, match="paused"):
        client.get("https://hubpower.com/investors/")
    assert len(t.calls) == 2  # the second get never reached the transport


def test_a_503_is_not_retried(tmp_path):
    t = FakeTransport(
        {
            "https://hubpower.com/robots.txt": [robots()],
            "https://hubpower.com/investors/": [(503, {}, b"")],
        }
    )
    res = f.run_company(
        entry_for(), now=TODAY, client=client_for(t), vault=tmp_path, manifest=f.Manifest(tmp_path)
    )
    assert res.status == "failed" and t.urls().count("https://hubpower.com/investors/") == 1


def test_a_403_stops_without_any_bypass_attempt(tmp_path):
    t = FakeTransport(
        {
            "https://hubpower.com/robots.txt": [robots()],
            "https://hubpower.com/investors/": [
                (403, {"content-type": "text/html"}, b"<title>Just a moment...</title>")
            ],
        }
    )
    res = f.run_company(
        entry_for(), now=TODAY, client=client_for(t), vault=tmp_path, manifest=f.Manifest(tmp_path)
    )
    assert res.status == "failed" and "no bypass attempted" in res.reason
    assert len(t.urls()) == 2  # robots and the one page: nothing else


def test_the_second_consecutive_refusal_stops_the_host_for_the_run(tmp_path):
    clock = FakeClock()
    t = FakeTransport(
        {
            "https://hubpower.com/robots.txt": [robots()],
            "https://hubpower.com/investors/": [(429, {}, b"")],
        }
    )
    client = client_for(t, clock)
    with pytest.raises(f.HostUnavailable):
        client.get("https://hubpower.com/investors/")
    clock.now += 10_000
    with pytest.raises(f.HostUnavailable):
        client.get("https://hubpower.com/investors/")
    clock.now += 10_000
    with pytest.raises(f.HostUnavailable, match="paused"):
        client.get("https://hubpower.com/investors/")


def test_single_flight_refuses_a_second_request_to_a_host_while_one_is_in_flight(tmp_path):
    clock = FakeClock()
    holder: dict = {}

    def reentrant(url, headers):
        if url.endswith("/robots.txt"):
            return robots()
        holder["client"].get("https://hubpower.com/another")  # a second request while the first is in flight
        return (200, {}, b"")

    client = client_for(reentrant, clock)
    holder["client"] = client
    with pytest.raises(AssertionError, match="single-flight"):
        client.get("https://hubpower.com/investors/")


def test_only_https_is_fetched():
    with pytest.raises(ValueError, match="https"):
        client_for(FakeTransport()).get("http://hubpower.com/investors/")


def test_a_network_error_is_not_retried_in_the_same_cycle(tmp_path):
    import urllib.error

    calls = {"n": 0}

    def flaky(url, headers):
        if url.endswith("/robots.txt"):
            return robots()
        calls["n"] += 1
        raise urllib.error.URLError("unreachable")

    res = f.run_company(
        entry_for(), now=TODAY, client=client_for(flaky), vault=tmp_path, manifest=f.Manifest(tmp_path)
    )
    assert res.status == "failed" and "network error" in res.reason and calls["n"] == 1


# ================================================================== the manual-import path


def _manifest_row_count(vault):
    return len(f.Manifest(vault).rows)


def test_a_manual_import_is_verified_stored_and_recorded_with_full_provenance(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    pdf = write_pdf(tmp_path / "ogdc_h1.pdf", [["SYNTHETIC half-year report"]])
    m = f.Manifest(vault)
    out = f.import_manual(
        pdf,
        symbol="OGDC",
        report_type="half_year",
        period_end="2025-12-31",
        fye="06-30",
        vault=vault,
        manifest=m,
        imported_at=datetime(2026, 11, 12, 9, 0, tzinfo=UTC),
    )
    assert out["status"] == "stored" and out["fiscal_label"] == "H1 FY2026"
    row = m.rows[0]
    assert row["source"] == "manual" and row["symbol"] == "OGDC" and row["report_type"] == "half_year"
    assert row["period_end"] == "2025-12-31" and row["fiscal_label"] == "H1 FY2026"
    assert row["fiscal_year"] == 2026 and row["fiscal_year_end"] == "06-30"
    assert row["imported_at"] == "2026-11-12T09:00:00Z" and row["original_filename"] == "ogdc_h1.pdf"
    assert row["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert (vault / row["vault_path"]).read_bytes() == pdf.read_bytes()


def test_a_second_import_of_the_same_bytes_adds_no_row(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    pdf = write_pdf(tmp_path / "ogdc.pdf", [["SYNTHETIC annual report"]])
    kwargs = dict(
        symbol="OGDC",
        report_type="annual_report",
        period_end="2026-06-30",
        fye="06-30",
        vault=vault,
        imported_at=TODAY,
    )
    f.import_manual(pdf, manifest=f.Manifest(vault), **kwargs)
    again = f.import_manual(pdf, manifest=f.Manifest(vault), **kwargs)
    assert again["status"] == "duplicate" and _manifest_row_count(vault) == 1


def test_a_mismatched_period_end_is_refused_before_anything_is_stored(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    pdf = write_pdf(tmp_path / "ubl.pdf", [["SYNTHETIC annual report"]])
    with pytest.raises(ValueError, match="fiscal year-end"):
        f.import_manual(
            pdf,
            symbol="OGDC",
            report_type="annual_report",
            period_end="2025-12-31",
            fye="06-30",
            vault=vault,
            manifest=f.Manifest(vault),
            imported_at=TODAY,
        )
    assert list(vault.iterdir()) == []  # nothing was written


def test_a_file_that_is_not_a_readable_pdf_is_refused(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    bogus = tmp_path / "notes.pdf"
    bogus.write_text("this is not a PDF")
    with pytest.raises((ValueError, IntakeError)):
        f.import_manual(
            bogus,
            symbol="UBL",
            report_type="annual_report",
            period_end="2025-12-31",
            fye="12-31",
            vault=vault,
            manifest=f.Manifest(vault),
            imported_at=TODAY,
        )
    assert _manifest_row_count(vault) == 0


def test_the_manual_import_command_refuses_a_vault_inside_the_repository(tmp_path):
    pdf = write_pdf(tmp_path / "x.pdf", [["SYNTHETIC"]])
    with pytest.raises(IntakeError, match="outside the Git repository"):
        vault_dir(ROOT / "a-vault-inside-the-repo")
    assert pdf.exists()


# ================================================================== vault only, no database, nothing in Git


def test_the_vault_must_be_absolute_and_outside_the_repository(tmp_path):
    with pytest.raises(IntakeError, match="absolute"):
        vault_dir("relative/vault")
    with pytest.raises(IntakeError, match="outside the Git repository"):
        vault_dir(ROOT / "vault-inside-repo")
    assert vault_dir(tmp_path) == tmp_path.resolve()


def test_the_fetcher_has_no_database_access():
    src = Path(f.__file__).read_text(encoding="utf-8")
    assert "from database" not in src and "import database" not in src
    assert "connect(" not in src and "turso" not in src.lower()


def test_pdfs_are_ignored_by_git_and_none_are_tracked():
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "*.pdf" in gitignore.splitlines()
    try:
        tracked = subprocess.run(
            ["git", "ls-files"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    assert not [p for p in tracked.splitlines() if p.lower().endswith(".pdf")]
