# ruff: noqa: S311 - seeded RNGs in tests make the jitter deterministic; not cryptography
"""Source fetcher: permission gate, per-host timing, 429 backoff, content checks, atomic dedup and dispatch.

Everything here is offline: the HTTP opener, clock, sleep, RNG and the intake runner are
scripted. No network, no real endpoint, no database. The PDF bodies are tiny synthetic byte strings.
"""

from __future__ import annotations

import hashlib
import json
import random
import threading
from pathlib import Path

import pytest

from engines import document_intake as di
from engines import source_registry as owner
from services import source_fetcher as sf

PDF = b"%PDF-1.4\nsynthetic test document\n%%EOF\n"
URL = "https://filings.example.invalid/ubl/annual.pdf"
URL2 = "https://filings.example.invalid/ubl/interim.pdf"


def owner_permitting(symbol="UBL", pattern="https://filings.example.invalid/ubl/{year}.pdf"):
    """An owner-registry entry that permits automated fetching of the symbol's annual reports."""
    return [
        owner.Source(
            source_id=f"owner_{symbol.lower()}",
            symbol=symbol,
            company="Test company",
            category="annual_report",
            financial_year=None,
            url_pattern=pattern,
            permission_status="permitted",
            auth_env_var=None,
            enabled=True,
            notes="synthetic test entry",
        )
    ]


OWNER = owner_permitting()


class FakeResp:
    def __init__(self, status=200, headers=None, body=b"", chunk=7):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._chunk = chunk
        self.closed = False

    def read(self, n=-1):
        if not self._body:
            return b""
        out, self._body = self._body[: self._chunk], self._body[self._chunk :]
        return out

    def close(self):
        self.closed = True


def pdf_resp(body=PDF, **kw):
    headers = {"Content-Type": "application/pdf", **kw.pop("headers", {})}
    return FakeResp(200, headers, body, **kw)


class Script:
    """A scripted opener: returns the next response, records each request and its headers."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.lock_held_during_call = []

    def __call__(self, req):
        self.requests.append(req)
        return self.responses.pop(0)


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(s)
        self.now += s


def source(url=URL, perm="permitted", interval=5, intake=None, symbol="UBL", framework="bank"):
    return sf.Source(symbol, 1, url, perm, framework, interval, "0 2 * * *", intake)


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    v.mkdir()
    return v


def policy_for(clock):
    return sf.HostPolicy(clock=clock, sleep=clock.sleep)


# ------------------------------------------------------------------ fail-closed permission gate


def test_a_paused_source_makes_no_request(vault):
    script, clock = Script(), Clock()
    res = sf.fetch_source(
        source(perm="paused"), vault, policy=policy_for(clock), owner_sources=OWNER, opener=script
    )
    assert res.status == "SKIPPED_NOT_PERMITTED" and script.requests == []


def test_unknown_permission_and_missing_url_are_refused_at_registry_load():
    base = {"symbol": "UBL", "expected_framework": "bank", "polling_schedule": "0 2 * * *"}
    with pytest.raises(sf.RegistryError, match="permission_status"):
        sf.parse_registry({"sources": [{**base, "permission_status": "allowed", "endpoint_url": URL}]})
    with pytest.raises(sf.RegistryError, match="needs an endpoint_url"):
        sf.parse_registry({"sources": [{**base, "permission_status": "permitted", "endpoint_url": None}]})


def test_registry_rejects_short_intervals_and_plain_http():
    base = {
        "symbol": "UBL",
        "expected_framework": "bank",
        "polling_schedule": "0 2 * * *",
        "permission_status": "paused",
    }
    with pytest.raises(sf.RegistryError, match="min_request_interval"):
        sf.parse_registry({"sources": [{**base, "endpoint_url": None, "min_request_interval_seconds": 2}]})
    with pytest.raises(sf.RegistryError, match="https"):
        sf.parse_registry({"sources": [{**base, "endpoint_url": "http://x.example.invalid/a.pdf"}]})


def test_the_shipped_registry_is_valid_and_fully_paused():
    sources = sf.load_registry(sf.REGISTRY_PATH)
    assert {s.symbol for s in sources} == {"UBL", "OGDC", "LUCK"}
    assert all(s.permission_status == "paused" and s.endpoint_url is None for s in sources)


# ------------------------------------------------------------------ rate limiting and concurrency


def test_consecutive_requests_to_one_host_wait_the_minimum_interval(vault):
    clock = Clock()
    pol = policy_for(clock)
    sc = Script(pdf_resp(), pdf_resp(body=b"%PDF-1.4 second"))
    sf.fetch_source(source(url=URL), vault, policy=pol, opener=sc, owner_sources=OWNER)
    sf.fetch_source(source(url=URL2), vault, policy=pol, opener=sc, owner_sources=OWNER)
    assert clock.sleeps == [pytest.approx(5.0)]  # the second hit waited the full 5 s


def test_a_host_is_not_throttled_by_a_request_long_ago(vault):
    clock = Clock()
    pol = policy_for(clock)
    pol.wait("h.example.invalid", 5)
    clock.now += 60
    assert pol.wait("h.example.invalid", 5) == 0.0 and clock.sleeps == []


def test_only_one_active_connection_per_host(vault):
    clock = Clock()
    pol = policy_for(clock)
    seen = []

    def opener(req):
        seen.append(pol.lock("filings.example.invalid").locked())  # held while the request is in flight
        return pdf_resp()

    sf.fetch_source(source(), vault, policy=pol, opener=opener, owner_sources=OWNER)
    assert seen == [True]
    assert pol.lock("filings.example.invalid") is pol.lock("filings.example.invalid")
    assert isinstance(pol.lock("filings.example.invalid"), type(threading.Lock()))


# ---------------------------------------------- 429: Retry-After, exponential backoff, jitter


def test_429_with_retry_after_waits_that_long_plus_jitter_then_stores(vault):
    clock = Clock()
    sc = Script(FakeResp(429, {"Retry-After": "7"}), pdf_resp())
    res = sf.fetch_source(
        source(), vault, policy=policy_for(clock), owner_sources=OWNER, opener=sc, rng=random.Random(1)
    )
    assert res.status == "STORED"
    waits = [s for s in clock.sleeps if s >= 7]
    assert waits and 7 <= waits[0] <= 7 * 1.25  # Retry-After honoured, jitter at most 25 %


def test_429_without_retry_after_backs_off_exponentially_with_jitter(vault):
    clock = Clock()
    sc = Script(FakeResp(429), FakeResp(429), pdf_resp())
    res = sf.fetch_source(
        source(), vault, policy=policy_for(clock), owner_sources=OWNER, opener=sc, rng=random.Random(2)
    )
    assert res.status == "STORED"
    d0 = sf.backoff_delay(0, None, random.Random(0))
    d1 = sf.backoff_delay(1, None, random.Random(0))
    assert d1 > d0 * 1.5  # exponential: the second wait is about twice the first
    assert sf.BACKOFF_BASE <= d0 <= sf.BACKOFF_BASE * 1.25


def test_repeated_429_gives_up_after_bounded_attempts(vault):
    clock = Clock()
    sc = Script(*[FakeResp(429) for _ in range(sf.MAX_ATTEMPTS)])
    res = sf.fetch_source(
        source(), vault, policy=policy_for(clock), owner_sources=OWNER, opener=sc, rng=random.Random(3)
    )
    assert res.status == "RATE_LIMITED_GIVE_UP" and len(sc.requests) == sf.MAX_ATTEMPTS
    assert not list(vault.glob("*.pdf"))


def test_backoff_is_capped():
    assert sf.backoff_delay(20, None, random.Random(0)) <= sf.BACKOFF_CAP


# ------------------------------------------------------------------ content checks: only PDFs are kept


def test_an_html_error_page_is_discarded_and_nothing_is_stored(vault):
    clock = Clock()
    html = FakeResp(200, {"Content-Type": "text/html; charset=utf-8"}, b"<html>not found</html>")
    res = sf.fetch_source(source(), vault, policy=policy_for(clock), owner_sources=OWNER, opener=Script(html))
    assert res.status == "REJECTED_NOT_PDF" and not list(vault.iterdir())


def test_a_404_or_500_is_not_stored_as_a_document(vault):
    clock = Clock()
    res = sf.fetch_source(
        source(),
        vault,
        policy=policy_for(clock),
        owner_sources=OWNER,
        opener=Script(FakeResp(404, {}, b"no")),
    )
    assert res.status == "ERROR_HTTP" and not list(vault.iterdir())


def test_a_pdf_content_type_with_a_non_pdf_body_is_rejected(vault):
    clock = Clock()
    res = sf.fetch_source(
        source(),
        vault,
        policy=policy_for(clock),
        owner_sources=OWNER,
        opener=Script(pdf_resp(body=b"<!doctype html>fake")),
    )
    assert res.status == "REJECTED_NOT_PDF_CONTENT"
    assert not list(vault.glob("*.pdf")) and not list(vault.glob("*.tmp"))


# ------------------------------------------------------------------ conditional requests


def test_conditional_headers_are_sent_from_the_last_response_and_304_skips_the_download(vault):
    clock = Clock()
    state = {URL: {"etag": '"abc"', "last_modified": "Wed, 01 Jul 2026 00:00:00 GMT", "last_sha256": "x"}}
    sc = Script(FakeResp(304))
    res = sf.fetch_source(
        source(), vault, policy=policy_for(clock), owner_sources=OWNER, opener=sc, state=state
    )
    assert res.status == "NOT_MODIFIED"
    req_headers = {k.lower(): v for k, v in sc.requests[0].headers.items()}
    assert req_headers["if-none-match"] == '"abc"'
    assert req_headers["if-modified-since"] == "Wed, 01 Jul 2026 00:00:00 GMT"


def test_the_etag_of_a_stored_document_is_remembered(vault):
    clock = Clock()
    state = {}
    res = sf.fetch_source(
        source(),
        vault,
        policy=policy_for(clock),
        owner_sources=OWNER,
        opener=Script(pdf_resp(headers={"ETag": '"v2"'})),
        state=state,
    )
    assert res.status == "STORED" and state[URL]["etag"] == '"v2"'
    assert json.loads((vault / sf.STATE_FILE).read_text())[URL]["etag"] == '"v2"'


# ------------------------------------------------------------------ atomic vault storage and duplicates


def test_a_new_pdf_is_stored_under_its_sha256_name_and_no_tmp_is_left(vault):
    clock = Clock()
    res = sf.fetch_source(
        source(), vault, policy=policy_for(clock), owner_sources=OWNER, opener=Script(pdf_resp())
    )
    sha = hashlib.sha256(PDF).hexdigest()
    assert res.status == "STORED" and res.sha256 == sha
    assert (vault / f"{sha}.pdf").read_bytes() == PDF
    assert not list(vault.glob("*.tmp"))


def test_a_duplicate_is_detected_by_sha256_and_never_overwrites(vault):
    clock = Clock()
    sha = hashlib.sha256(PDF).hexdigest()
    existing = vault / f"{sha}.pdf"
    existing.write_bytes(PDF)
    before = (existing.stat().st_mtime_ns, existing.read_bytes())
    res = sf.fetch_source(
        source(), vault, policy=policy_for(clock), owner_sources=OWNER, opener=Script(pdf_resp())
    )
    assert res.status == "SKIPPED_DUPLICATE" and res.sha256 == sha
    assert (existing.stat().st_mtime_ns, existing.read_bytes()) == before
    assert not list(vault.glob("*.tmp"))


def test_a_stream_that_is_not_pdf_at_its_start_leaves_no_partial_file(vault):
    clock = Clock()
    res = sf.fetch_source(
        source(),
        vault,
        policy=policy_for(clock),
        owner_sources=OWNER,
        opener=Script(pdf_resp(body=b"HTML STUFF" * 50)),
    )
    assert res.status == "REJECTED_NOT_PDF_CONTENT"
    assert list(vault.iterdir()) == []


# ------------------------------------------------------------------ dispatch to the diagnostic intake


class Runner:
    def __init__(self, stdout, code=0):
        self.stdout, self.code = stdout, code
        self.cmds = []

    def __call__(self, cmd, **kw):
        self.cmds.append(cmd)

        class P:
            pass

        p = P()
        p.stdout, p.returncode = self.stdout, self.code
        return p


def test_a_stored_pdf_is_diagnosed_with_text_and_never_with_archive(vault):
    clock = Clock()
    prof = {
        "period_end": "2025-12-31",
        "columns": ["2025-12-31", "2024-12-31"],
        "unit_scale": 1000,
        "consolidation": "unconsolidated",
        "currency": "PKR",
        "page_map": None,
    }
    runner = Runner("...\nReconciliation: balance sheet RECONCILED, overall RECONCILED\n")
    rows = sf.run_once(
        [source(intake=prof)],
        vault,
        policy=policy_for(clock),
        owner_sources=OWNER,
        opener=Script(pdf_resp()),
        rng=random.Random(0),
        runner=runner,
    )
    cmd = runner.cmds[0]
    assert "--text" in cmd and "--archive" not in cmd and "scripts.financial_intake" in cmd
    assert rows[0]["reconciliation_status"] == "RECONCILED"


def test_each_stored_document_is_logged_with_timestamp_symbol_sha_and_status(vault):
    clock = Clock()
    prof = {"period_end": "2025-12-31", "columns": ["2025-12-31", "2024-12-31"]}
    sf.run_once(
        [source(intake=prof)],
        vault,
        policy=policy_for(clock),
        owner_sources=OWNER,
        opener=Script(pdf_resp()),
        rng=random.Random(0),
        runner=Runner("Reconciliation: overall UNRECONCILED"),
    )
    log = json.loads((vault / sf.LOG_FILE).read_text())
    assert len(log) == 1
    assert set(log[0]) >= {"timestamp", "symbol", "sha256", "reconciliation_status"}
    assert log[0]["symbol"] == "UBL" and log[0]["reconciliation_status"] == "UNRECONCILED"
    assert log[0]["sha256"] == hashlib.sha256(PDF).hexdigest()


def test_a_source_without_an_intake_profile_is_stored_but_not_dispatched(vault):
    clock = Clock()
    runner = Runner("")
    sf.run_once(
        [source()],
        vault,
        policy=policy_for(clock),
        owner_sources=OWNER,
        opener=Script(pdf_resp()),
        rng=random.Random(0),
        runner=runner,
    )
    assert runner.cmds == []
    assert json.loads((vault / sf.LOG_FILE).read_text())[0]["reconciliation_status"] == "NOT_DISPATCHED"


def test_a_failed_intake_is_logged_as_failed_not_as_reconciled(vault):
    clock = Clock()
    prof = {"period_end": "2025-12-31", "columns": ["2025-12-31"]}
    sf.run_once(
        [source(intake=prof)],
        vault,
        policy=policy_for(clock),
        owner_sources=OWNER,
        opener=Script(pdf_resp()),
        rng=random.Random(0),
        runner=Runner("traceback", code=1),
    )
    assert json.loads((vault / sf.LOG_FILE).read_text())[0]["reconciliation_status"] == "INTAKE_FAILED"


def test_a_pass_can_be_restricted_to_one_symbol(vault):
    clock = Clock()
    s1 = source(symbol="UBL", perm="paused")
    s2 = source(symbol="OGDC", perm="paused", url=URL2)
    rows = sf.run_once(
        [s1, s2], vault, policy=policy_for(clock), owner_sources=OWNER, opener=Script(), only="OGDC"
    )
    assert [r["symbol"] for r in rows] == ["OGDC"]


# ------------------------------------------------------------------ the owner's registry must also permit it


def test_an_empty_owner_registry_permits_nothing_even_when_the_target_is_permitted(vault):
    clock = Clock()
    script = Script()
    res = sf.fetch_source(source(), vault, policy=policy_for(clock), opener=script, owner_sources=[])
    assert res.status == "SKIPPED_NOT_PERMITTED" and script.requests == []


def test_an_owner_entry_for_another_url_does_not_permit_this_one(vault):
    clock = Clock()
    script = Script()
    other = owner_permitting(pattern="https://elsewhere.example.invalid/{year}.pdf")
    res = sf.fetch_source(source(), vault, policy=policy_for(clock), opener=script, owner_sources=other)
    assert res.status == "SKIPPED_NOT_PERMITTED" and script.requests == []


def test_the_shipped_owner_registry_is_empty_so_nothing_is_permitted():
    assert owner.load(sf.OWNER_REGISTRY_PATH) == []


def test_the_vault_must_be_configured_outside_the_repository(monkeypatch):
    monkeypatch.delenv(di.VAULT_ENV, raising=False)
    with pytest.raises(di.IntakeError):
        di.vault_dir()
    assert isinstance(Path(sf.REGISTRY_PATH), Path)
