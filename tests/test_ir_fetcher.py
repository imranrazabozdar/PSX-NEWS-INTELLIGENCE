"""IR report fetcher: extraction, classification, scope, dedup, provenance, politeness, vault-only storage.

Fully offline. Every network call goes through a fake transport. Fixtures are point-in-time excerpts of
real company
pages (see the headers in tests/fixtures/ir/) and one clearly labelled synthetic page.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from engines import ir_fetcher as f
from engines.document_intake import IntakeError, vault_dir

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "tests" / "fixtures" / "ir"
TODAY = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
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


def entry_for(symbol="HUBC", url="https://hubpower.com/investors/", hosts=("hubpower.com",), **kw):
    return f.IrEntry(
        symbol=symbol, name=symbol, url=url, status=kw.pop("status", "live"), allowed_hosts=hosts, **kw
    )


def client_for(transport, clock=None):
    clock = clock or FakeClock()
    return f.PoliteClient(transport=transport, clock=clock, sleep=clock.sleep, min_interval_s=10.0)


# ================================================================== registry


def test_the_starter_registry_has_the_five_companies_and_honest_statuses():
    reg = f.load_registry()
    assert set(reg) == {"OGDC", "LUCK", "UBL", "HUBC", "PSO"}
    assert reg["OGDC"].status == "blocked_by_site"
    assert reg["UBL"].status == "todo_unreachable"
    assert reg["LUCK"].status == "live" and reg["HUBC"].status == "live" and reg["PSO"].status == "live"
    assert all(e.url.startswith("https://") for e in reg.values())


def test_a_non_live_entry_is_never_fetched(tmp_path):
    t = FakeTransport()
    res = f.run_company(
        entry_for(status="blocked_by_site"),
        now=TODAY,
        client=client_for(t),
        vault=tmp_path,
        manifest=f.Manifest(tmp_path),
    )
    assert res.status == "skipped" and t.calls == []


def test_the_registry_rejects_an_unknown_status_or_an_http_url(tmp_path):
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


# ================================================================== classification


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Annual Report 2026", ("annual_report", "2026", 2026)),
        ("HUBCO-Integrated-Annual-Report-2026.pdf", ("annual_report", "2026", 2026)),
        ("1st Quarterly Report 2027", ("quarterly", "Q1-2027", 2027)),
        ("Q3-FY26.pdf", ("quarterly", "Q3-2026", 2026)),
        ("Third_Quarter_Report_March_31_2026_57af.pdf", ("quarterly", "Q3-2026", 2026)),
        ("Nine Months Report 2026", ("quarterly", "Q3-2026", 2026)),
        ("Condensed Interim Financial Statements 9MFY24", ("quarterly", "Q3-2024", 2024)),
        ("Half Yearly Report 2025", ("half_year", "H1-2025", 2025)),
        ("Financial Statements 2025", ("financial_statements", "2025", 2025)),
        ("June2022.pdf", None),  # no report type, no year: not guessed
        ("HUBCO-AR-Final-Low-Res.pdf", None),  # no year: not guessed
        ("Quarterly report", None),  # a quarterly report with no quarter number: not guessed
    ],
)
def test_classification_states_the_type_and_period_only_when_clear(text, expected):
    assert f.classify(text) == expected


# ================================================================== extraction from the real fixtures


def test_hub_power_fixture_yields_its_annual_reports_and_no_guesses():
    e = entry_for()
    cands = f.extract_candidates(html("hubc_investors_excerpt.html").decode(), e.url, e.allowed_hosts)
    got = {(c.report_type, c.period) for c in cands}
    assert got == {("annual_report", "2026"), ("annual_report", "2025")}
    assert all(c.pdf_url.startswith("https://hubpower.com/") for c in cands)
    assert len(f.scoped(cands, e, today=TODAY)) == 2


def test_psx_listed_pso_fixture_classifies_quarters_and_annuals_and_drops_summaries():
    e = entry_for("PSO", "https://www.psopk.com/en/investors/financial", ("psopk.com",))
    cands = f.extract_candidates(html("pso_financial_excerpt.html").decode(), e.url, e.allowed_hosts)
    kept = {(c.report_type, c.period, c.pdf_url.rsplit("/", 1)[-1]) for c in f.scoped(cands, e, today=TODAY)}
    assert ("quarterly", "Q1-2027", "Q1FY27.pdf") in kept
    assert ("quarterly", "Q3-2026", "Q3-FY26.pdf") in kept
    assert ("annual_report", "2025", "PSO-Annual-Report-2025.pdf") in kept
    assert not any("Summary" in name for _, _, name in kept)  # the summary is excluded
    assert not any(
        period.endswith("2024") or period.endswith("2019") for _, period, _ in kept
    )  # out of window
    assert len(kept) == 8


def test_lucky_fixture_finds_the_pdfs_embedded_in_the_page_data():
    e = entry_for(
        "LUCK",
        "https://www.lucky-cement.com/en/corporate/investor-relations/financial-reports",
        ("lucky-cement.com",),
    )
    cands = f.extract_candidates(html("luck_reports_excerpt.html").decode(), e.url, e.allowed_hosts)
    assert any(c.report_type == "annual_report" and c.period == "2025" for c in cands)
    assert any(c.report_type == "half_year" and c.period == "H1-2025" for c in cands)
    assert all(c.pdf_url.startswith("https://assets.lucky-cement.com/") for c in cands)
    assert len(f.scoped(cands, e, today=TODAY)) == 5


# ================================================================== synthetic edge cases

SYN = entry_for("SYN", "https://issuer.example/reports", ("issuer.example",))


def _syn_candidates():
    return f.extract_candidates(html("synthetic_company_reports.html").decode(), SYN.url, SYN.allowed_hosts)


def test_synthetic_page_edge_cases_are_handled():
    cands = _syn_candidates()
    urls = [c.pdf_url for c in cands]
    assert (
        urls.count("https://issuer.example/reports/AR2026.pdf") == 1
    )  # duplicate anchor and JSON: one entry
    assert not any("cdn.other.example" in u for u in urls)  # off-host links are ignored
    assert not any(u.endswith(".html") for u in urls)  # non-PDF links are ignored
    assert "https://issuer.example/reports/q1.pdf?v=2" in urls  # the query string is kept as part of the URL
    kept = {(c.report_type, c.period) for c in f.scoped(cands, SYN, today=TODAY)}
    assert kept == {
        ("annual_report", "2026"),
        ("half_year", "H1-2026"),
        ("financial_statements", "2025"),
        ("quarterly", "Q1-2026"),
        ("quarterly", "Q3-2026"),
    }


def test_the_summary_notice_undated_and_old_items_are_out_of_scope():
    kept_urls = {c.pdf_url for c in f.scoped(_syn_candidates(), SYN, today=TODAY)}
    assert "https://issuer.example/reports/ar26-summary.pdf" not in kept_urls
    assert "https://issuer.example/reports/ar-old.pdf" not in kept_urls  # 2019
    assert "https://issuer.example/reports/AR2023.pdf" not in kept_urls  # 2023 is outside the two-year window
    assert "https://issuer.example/reports/undated.pdf" not in kept_urls


def test_the_scope_window_and_the_type_filter_are_configurable():
    cands = _syn_candidates()
    one_year = {c.period for c in f.scoped(cands, SYN, today=TODAY, years_back=1)}
    assert "2025" not in one_year and "2026" in one_year  # only the current year
    annual_only = entry_for(
        "SYN", "https://issuer.example/reports", ("issuer.example",), report_types=("annual_report",)
    )
    assert {c.report_type for c in f.scoped(cands, annual_only, today=TODAY)} == {"annual_report"}


# ================================================================== the run: dedup, provenance, storage


def _run(transport, vault, *, manifest=None, entry=None, max_downloads=10):
    e = entry or entry_for()
    m = manifest or f.Manifest(vault)
    return f.run_company(
        e, now=TODAY, client=client_for(transport), vault=vault, manifest=m, max_downloads=max_downloads
    ), m


def _hub_transport():
    page = "https://hubpower.com/investors/"
    routes = page_route(page, html("hubc_investors_excerpt.html"))
    routes["https://hubpower.com/wp-content/uploads/2026/09/HUBCO-Integrated-Annual-Report-2026.pdf"] = [
        (200, {}, PDF)
    ]
    routes["https://hubpower.com/wp-content/uploads/2025/09/HUBCO-Integrated-Annual-Report-2025.pdf"] = [
        (200, {}, PDF + b"2025")
    ]
    return FakeTransport(routes)


def test_pdfs_are_stored_in_the_vault_with_full_provenance(tmp_path):
    t = _hub_transport()
    res, m = _run(t, tmp_path)
    assert res.status == "ok" and len(res.stored) == 2
    row = next(r for r in m.rows if r["period"] == "2026")
    assert row["symbol"] == "HUBC" and row["report_type"] == "annual_report"
    assert row["source_page_url"] == "https://hubpower.com/investors/"
    assert row["pdf_url"].endswith("HUBCO-Integrated-Annual-Report-2026.pdf")
    assert row["sha256"] == hashlib.sha256(PDF).hexdigest() and row["bytes"] == len(PDF)
    assert row["retrieved_at"] == "2026-11-11T12:00:00Z"
    stored = tmp_path / row["vault_path"]
    assert stored.read_bytes() == PDF and stored.parent.name == "HUBC"
    assert stored.name == "annual_report_2026.pdf"


def test_an_existing_vault_file_is_never_downloaded_again(tmp_path):
    first, m = _run(_hub_transport(), tmp_path)
    t2 = _hub_transport()
    res2, _ = _run(t2, tmp_path)  # a fresh manifest object reads the manifest from disk
    assert res2.stored == [] and res2.duplicates == 2
    assert not any(u.endswith(".pdf") for u in t2.urls())  # no PDF request at all the second time


def test_a_pdf_with_a_known_hash_under_a_new_url_is_not_stored_twice(tmp_path):
    t = _hub_transport()
    _, m = _run(t, tmp_path)
    before = len(list(tmp_path.rglob("*.pdf")))
    # the same bytes now appear under a different URL: the hash matches, so nothing new is written
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
    routes["https://hubpower.com/wp-content/uploads/2025/09/HUBCO-Integrated-Annual-Report-2025.pdf"] = [
        (200, {}, PDF)
    ]
    res, _ = _run(FakeTransport(routes), tmp_path)
    assert len(res.rejected) == 1 and "not a PDF" in res.rejected[0]
    assert [r.name for r in tmp_path.rglob("*.pdf")] == ["annual_report_2025.pdf"]


def test_a_name_clash_keeps_both_documents(tmp_path):
    # two different PDFs both labelled as the same quarter: the second is kept under a hash-suffixed name
    e = entry_for("SYN", "https://issuer.example/reports", ("issuer.example",))
    routes = page_route("https://issuer.example/reports", html("synthetic_company_reports.html"))
    routes["https://issuer.example/reports/q1.pdf?v=2"] = [(200, {}, PDF + b"a")]
    routes["https://issuer.example/reports/q1-2026.pdf"] = [(200, {}, PDF + b"b")]
    res, m = _run(FakeTransport(routes), tmp_path, entry=e)
    names = sorted(p.name for p in (tmp_path / "SYN").glob("*.pdf"))
    assert len(names) == len({n for n in names}) == 2 and "quarterly_Q1-2026.pdf" in names
    assert any(n.startswith("quarterly_Q1-2026_") for n in names)


def test_the_number_of_downloads_per_run_is_capped(tmp_path):
    t = _hub_transport()
    res, _ = _run(t, tmp_path, max_downloads=1)
    assert len(res.stored) == 1


# ================================================================== politeness


def test_every_request_carries_the_same_honest_identity_with_a_contact(tmp_path):
    t = _hub_transport()
    _run(t, tmp_path)
    agents = {h["User-Agent"] for _, h in t.calls}
    assert agents == {f.USER_AGENT}  # one identity, never rotated
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
    assert res.stored == [] and len(res.rejected) == 2


def test_a_missing_robots_file_allows_and_an_unreadable_one_denies(tmp_path):
    t = FakeTransport(
        {
            "https://hubpower.com/robots.txt": [(404, {}, b"")],
            "https://hubpower.com/investors/": [(200, {}, html("hubc_investors_excerpt.html"))],
        }
    )
    res, _ = _run(t, tmp_path)
    assert res.status == "ok" and res.in_scope == 2
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
    assert len(sent_at) >= 3  # robots, page and PDFs
    gaps = [b - a for a, b in zip(sent_at, sent_at[1:], strict=False)]
    assert all(g >= 10.0 for g in gaps)  # never closer than the per-host minimum interval


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
        {"https://hubpower.com/robots.txt": [robots()], "https://hubpower.com/investors/": [(503, {}, b"")]}
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
    assert t.urls().count("https://hubpower.com/investors/") == 1
    assert len(t.urls()) == 2  # robots and the one page: nothing else


def test_the_second_consecutive_refusal_stops_the_host_for_the_run(tmp_path):
    clock = FakeClock()
    t = FakeTransport(
        {
            "https://hubpower.com/robots.txt": [robots()],
            "https://hubpower.com/investors/": [(429, {}, b"")],
            "https://hubpower.com/a.pdf": [(429, {}, b"")],
        }
    )
    client = client_for(t, clock)
    with pytest.raises(f.HostUnavailable):
        client.get("https://hubpower.com/investors/")
    clock.now += 10_000  # long after any backoff
    with pytest.raises(f.HostUnavailable):
        client.get("https://hubpower.com/investors/")  # second refusal: the host is now stopped for the run
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
        # a fixed command, not user input
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
