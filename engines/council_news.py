"""PSX News Intelligence Council V1, DRY-RUN stage.

Reads stored headlines from psx-library (read only), finds the events that matter
(engines/news_importance.py), queues
them under the run caps (engines/council_ledger.py), and runs the existing three-lens council on the ones
it may run.
Every result is a structured record printed to the Actions log. NOTHING is written to the production
database in this
stage: the connection is wrapped so any statement other than SELECT raises, and the budget, queue and
call log live in
the council ledger file.

Models: the lenses use the free-tier accounts already configured for the council (Groq, Gemini,
OpenRouter). There is
no paid fallback; with no key the council is simply not connected and the record says so. A model is
reported as
connected only when it actually answered a call in that run.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from engines import analyst_council as council
from engines import council_ledger as cl
from engines import llm, llm_quota, market_calendar
from engines import news_facts as nf
from engines import news_importance as ni
from engines import news_rollup as nr

SOURCE_LABEL = {**nf.OUTLETS, "investify": "Investify (investify.pk) announcement"}
MAX_MEMBERS_IN_PACK = 6
MIN_HISTORY_DAYS = (
    nr.BASELINE_MIN_DAYS + 7
)  # a share needs 14 days of baseline before the week it is compared with
EXPECTED_TABLES = {"news_item", "news_progress", "research_fact"}
FORBIDDEN_TABLES = {"market_bars", "market_ohlcv", "ohlcv", "technical_signals", "daily_bars"}
RECORD_SCHEMA = "council_news_dryrun_v1"
SLEEP = time.sleep  # the gateway's retry back-off; tests replace it so retries run instantly


class IdentityError(RuntimeError):
    """The database is not recognisably psx-library; fail closed."""


class ReadOnlyViolation(RuntimeError):
    """The dry run tried to write to the database."""


class ReadOnlyDB:
    """Passes SELECT (and WITH ... SELECT) through; refuses everything else, including batches."""

    def __init__(self, db: Any):
        self._db = db

    def execute(self, sql: str, params: tuple = ()) -> list[Any]:
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        if head not in ("SELECT", "WITH"):
            raise ReadOnlyViolation(f"dry run refused a non-read statement: {sql.strip()[:60]!r}")
        return self._db.execute(sql, params)

    def batch(self, *_a: Any, **_k: Any) -> Any:
        raise ReadOnlyViolation("dry run refused a write batch")

    def usage(self) -> dict[str, int]:
        return self._db.usage()


def assert_library_identity(db: Any) -> None:
    """psx-library holds the news and research tables; a database with price-archive tables is not it."""
    names = {str(r["name"]) for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = EXPECTED_TABLES - names
    if missing:
        raise IdentityError(f"not psx-library: missing {sorted(missing)}")
    mixed = FORBIDDEN_TABLES & names
    if mixed:
        raise IdentityError(
            f"refusing: this database also holds {sorted(mixed)} (a technical or archive store)"
        )


# --- models: free tier only, every attempt recorded -------------------------------------------------------


class LedgerQuotaTracker(llm_quota.QuotaTracker):
    """Quota windows computed from the ledger's call records. Calls are recorded once, by TrackedLeaf,
    for every
    attempt (so a failed attempt still counts against a vendor account), not again by the guard."""

    def __init__(self, ledger: cl.Ledger, clock: Callable[[], datetime]):
        self.db = None
        self._memory: list[Any] = []
        self._ledger, self._clock = ledger, clock

    def record(self, vendor: str, account: int) -> None:
        return None

    def calls_since(self, vendor: str, account: int, seconds: int) -> int:
        return self._ledger.calls_since(vendor, account, self._clock() - timedelta(seconds=seconds))

    def prune(self) -> None:
        return None


def _reported(out: Any, field_name: str) -> int | None:
    """A token count the vendor actually reported. A count of 0 means the vendor sent no usage figure, which
    is UNKNOWN (None), not zero tokens."""
    value = getattr(out, field_name, None) if out is not None else None
    return value if isinstance(value, int) and value > 0 else None


class TrackedLeaf:
    """One vendor account. Records every call attempt: vendor, account, model, outcome, time taken, tokens."""

    def __init__(self, provider: Any, ledger: cl.Ledger, ctx: dict[str, Any], clock: Callable[[], datetime]):
        self._p, self._ledger, self._ctx, self._clock = provider, ledger, ctx, clock
        self.name, self.model, self.account = provider.name, provider.model, getattr(provider, "account", 0)

    def _log(self, outcome: str, started: float, out: Any = None, err: str = "") -> None:
        self._ledger.record_call(
            {
                "ts": cl.stamp(self._clock()),
                "vendor": self.name,
                "account": self.account,
                "model": getattr(out, "model", None) or self.model,
                "outcome": outcome,
                "ms": int((time.monotonic() - started) * 1000),
                "input_tokens": _reported(out, "input_tokens"),
                "output_tokens": _reported(out, "output_tokens"),
                "error": err[:200] or None,
                "event": self._ctx.get("event"),
                "role": self._ctx.get("role"),
                "exec": self._ctx.get("exec"),
            }
        )

    def complete(self, **kw: Any) -> Any:
        started = time.monotonic()
        try:
            out = self._p.complete(**kw)
        except llm.ProviderNotConnected as exc:
            self._log("not_connected", started, err=str(exc))
            raise
        except llm.TransientProviderError as exc:
            self._log("transient_error", started, err=str(exc))
            raise
        except llm.LLMError as exc:
            self._log("error", started, err=str(exc))
            raise
        self._log("ok", started, out)
        return out


# Independence (owner-approved 2026-11-19, free tier only): each analyst is pinned to a DIFFERENT model
# family,
# so agreement or disagreement means something. The pinned family may rotate over its own accounts, but there
# is NO silent fallback to another family: when the pinned model cannot answer the analyst is recorded as
# unavailable, and the record says so. Set PSXNI_COUNCIL_INDEPENDENT_MODELS=off to return to the older chain.
INDEPENDENT_MODELS: dict[str, tuple[tuple[str, str], ...]] = {
    "news": (("groq", llm.DEFAULT_GROQ_MODEL),),
    "financial": (("groq", "qwen/qwen3.8-27b"),),
    # NVIDIA family first (a family no other analyst uses); Google Gemini only as the fallback. Gemma is NOT
    # used: it is a Google model and would not be independent of Gemini.
    "macro": (("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"), ("gemini", llm.DEFAULT_GEMINI_MODEL)),
}
# The model family behind each model id (a "different model" from the same lab is not independent).
FAMILIES: dict[str, str] = {
    llm.DEFAULT_GROQ_MODEL: "OpenAI",
    "qwen/qwen3.8-27b": "Alibaba Qwen",
    "nvidia/nemotron-3-ultra-550b-a55b:free": "NVIDIA",
    llm.DEFAULT_GEMINI_MODEL: "Google",
    "google/gemma-4-31b-it:free": "Google",
}


def family_of(model: str) -> str:
    """The family of a model id; unknown ids are reported as unknown, never assumed independent."""
    return FAMILIES.get(model, "unknown")


def build_chain(
    role: str, env: Any, ledger: cl.Ledger, ctx: dict[str, Any], clock: Callable[[], datetime]
) -> tuple[Any | None, list[str]]:
    """Free-tier chain for one lens: its own account first, then the others, then the other vendors; each
    account
    quota-guarded from the ledger. Returns (provider or None, notes). None means no free-tier key is
    configured: the
    council is not connected, and there is deliberately no paid fallback."""
    notes: list[str] = []
    offset = council.ROLES.index(role)
    chain: list[Any] = []
    switch = str(env.get("PSXNI_COUNCIL_INDEPENDENT_MODELS", "on"))
    pinned = INDEPENDENT_MODELS.get(role) if switch != "off" else None
    if pinned:
        names = " then ".join(f"{v} {m}" for v, m in pinned)
        notes.append(f"{role}: pinned to {names}; no fallback to another analyst's family")
    vendors = (
        (llm.GroqProvider, llm.GROQ_MODEL_VAR),
        (llm.GeminiProvider, llm.GEMINI_MODEL_VAR),
        (llm.OpenRouterProvider, llm.OPENROUTER_MODEL_VAR),
    )
    if pinned:  # the analyst's own order: primary first, its permitted fallback after
        by_name = {c.name: (c, v) for c, v in vendors}
        vendors = tuple(by_name[v] for v, _m in pinned if v in by_name)
    for cls, model_var in vendors:
        pin_model = next((m for v, m in pinned if v == cls.name), None) if pinned else None
        keys = llm.keys_from_env(cls.key_var, env)
        if not keys:
            continue
        model = pin_model or (str(env.get(model_var, "") or "").strip() or None)
        if cls is llm.OpenRouterProvider and not (model or llm.DEFAULT_OPENROUTER_MODEL).endswith(":free"):
            notes.append("openrouter skipped: only ':free' models are allowed (no paid fallback)")
            continue
        start = offset % len(keys)
        numbered = list(enumerate(keys, start=1))
        ordered = numbered[start:] + numbered[:start]
        leaves = [TrackedLeaf(cls(api_key=k, model=model, account=n), ledger, ctx, clock) for n, k in ordered]
        chain.append(leaves[0] if len(leaves) == 1 else llm.RotatingProvider(leaves))
    if not chain:
        why = "no free-tier model key is configured"
        if pinned:
            why = f"no free-tier key for the pinned {' or '.join(v for v, _m in pinned)} model"
        return None, notes + [why]
    provider = chain[0] if len(chain) == 1 else llm.FallbackProvider(chain)
    return llm_quota.guard(provider, LedgerQuotaTracker(ledger, clock), env), notes


def configured_accounts(env: Any) -> dict[str, int]:
    """How many keys are CONFIGURED per vendor. Configured is not connected: only a successful call
    proves that."""
    return {
        cls.name: len(llm.keys_from_env(cls.key_var, env))
        for cls in (llm.GroqProvider, llm.GeminiProvider, llm.OpenRouterProvider)
    }


class _CtxGateway:
    """Sets the call context (which lens, which phase) before each model call, so the ledger records it."""

    def __init__(self, inner: llm.LLMGateway, ctx: dict[str, Any], role: str):
        self._inner, self._ctx, self._role = inner, ctx, role
        self.provider = inner.provider

    def complete(self, prompt: Any, user: str, schema: dict) -> Any:
        phase = "synthesis" if "synthesis" in prompt.prompt_id else "lens"
        self._ctx["role"] = f"{self._role}:{phase}"
        return self._inner.complete(prompt, user, schema)


# --- reading the news (read only) -------------------------------------------------------------------------


def load_headlines(db: Any, since: datetime, until: datetime) -> list[ni.Headline]:
    rows = db.execute(
        "SELECT source, url, title, published_at, section, snippet FROM news_item "
        "WHERE published_at >= ? AND published_at <= ? ORDER BY published_at",
        (cl.stamp(since), cl.stamp(until)),
    )
    return [
        ni.Headline(r["source"], r["url"], r["title"], r["published_at"], r["snippet"], r["section"])
        for r in rows
    ]


def baseline_signals(
    db: Any, now: datetime, build: Callable[..., Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rules 3 and 6 input: entities whose share of the news stands out against their own history. When
    there is not
    enough history the baseline is UNKNOWN, not zero, and no signal is made."""
    facts, n_items, _ = build(db, 60)
    rows = nr.rollup(facts)
    days = sorted(r["day"] for r in rows if r["entity"] == nr.ALL)
    today = now.astimezone(UTC).date()
    history = (today - date.fromisoformat(days[0])).days if days else None
    status = {"headlines_in_window": n_items, "history_days": history}
    if history is None or history < MIN_HISTORY_DAYS:
        status["baseline"] = "unknown: not enough history yet"
        return [], status
    status["baseline"] = "available"
    return nr.signals(rows, today, cl.stamp(now)), status


# --- one council run --------------------------------------------------------------------------------------


@dataclass
class Candidate:
    """A queued event brought back to life from its payload."""

    key: str
    event_id: str
    version: str
    priority: float
    payload: dict[str, Any]


def pack_for(payload: dict[str, Any], db: Any, build_pack: Callable[..., Any]) -> council.EvidencePack:
    """The evidence pack: outlet-attributed news items first, then what the brain already knows (facts for the
    named companies and sectors, always the Pakistan macro backdrop), built in Python by the existing
    builder."""
    members = payload["members"][-MAX_MEMBERS_IN_PACK:]
    companies = [c for c in payload["companies"] if ":" not in c]
    sectors = [s.split(":", 1)[1] for s in payload["sectors"] if s.startswith("SECTOR:")]
    pack = build_pack(payload["title"], companies, db, news=[], sectors=sectors)
    pack.items = [i for i in pack.items if i.source_name != "Owner-supplied event text"]
    news = []
    for n, m in enumerate(members, start=1):
        text = m["title"] + (f" {m['snippet']}" if m.get("snippet") else "")
        news.append(
            council.Evidence(
                f"n{n}",
                "news",
                text[:500],
                SOURCE_LABEL.get(m["source"], m["source"]),
                m["published_at"][:10],
                companies[0] if companies else None,
            )
        )
    if not news:  # a signal event: its own stated finding is the item the lenses read
        news.append(
            council.Evidence("n1", "news", payload["title"][:500], "News rollup (computed)", payload["day"])
        )
    pack.items = news + pack.items
    return pack


def _direction_views(verdict_dict: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """company -> {lens: assessment} for every lens that answered; the single source of the structured
    output."""
    by: dict[str, dict[str, Any]] = {}
    for f in verdict_dict["findings"]:
        if f["outcome"] != "ok":
            continue
        for a in f["assessments"]:
            by.setdefault(a["company"], {})[f["role"]] = a
    return by


def structure_assessment(
    verdict_dict: dict[str, Any], pack: council.EvidencePack, sectors: list[str]
) -> dict[str, Any]:
    by = _direction_views(verdict_dict)
    conflicted = {c["company"] for c in verdict_dict["conflicted"]}

    def entry(name: str, views: dict[str, Any]) -> dict[str, Any]:
        dirs = {v["direction"] for v in views.values()}
        if name in conflicted:
            consensus = "mixed"
        elif len(dirs) == 1:
            consensus = next(iter(dirs))
        else:
            consensus = "partial: " + "/".join(sorted(dirs))
        return {
            "entity": name,
            "consensus": consensus,
            "lenses": {
                lens: {
                    "direction": v["direction"],
                    "magnitude": v["magnitude"],
                    "timing": v["timing"],
                    "confidence": v["confidence"],
                    "reason": v["reason"],
                    "evidence_ids": v["evidence_ids"],
                }
                for lens, v in sorted(views.items())
            },
        }

    companies = [entry(n, v) for n, v in sorted(by.items()) if not n.startswith("SECTOR:")]
    sector_rows = [entry(n, v) for n, v in sorted(by.items()) if n.startswith("SECTOR:")]
    assessed = {e["entity"] for e in sector_rows}
    for s in sectors:  # a sector the event touches that no lens addressed is UNKNOWN, not neutral
        if f"SECTOR:{s}" not in assessed:
            sector_rows.append({"entity": f"SECTOR:{s}", "consensus": "unknown", "lenses": {}})
    pack_only = [c for c in pack.companies if c not in by and not c.startswith("SECTOR:")]
    return {
        "affected_companies": companies,
        "companies_in_pack_not_assessed": pack_only,
        "sector_impact": sector_rows,
        "monitor": verdict_dict["monitor"],
    }


def analyst_coverage(verdict_dict: dict[str, Any]) -> dict[str, Any]:
    """Whether all three analysts answered on three different model families. Disagreement between models is
    only meaningful then; otherwise the record says INSUFFICIENT_ANALYST_COVERAGE, no consensus is made up."""
    ok = [f for f in verdict_dict["findings"] if f["outcome"] == "ok"]
    families = {family_of(f["model"] or "") for f in ok}
    full = len(ok) == 3 and len(families) == 3 and "unknown" not in families
    return {
        "status": "full" if full else "INSUFFICIENT_ANALYST_COVERAGE",
        "analysts_answered": [f["role"] for f in ok],
        "families": {f["role"]: family_of(f["model"] or "") for f in ok},
    }


def disagreement(verdict_dict: dict[str, Any]) -> dict[str, Any]:
    by = _direction_views(verdict_dict)
    spread = {
        c: sorted({v["direction"] for v in views.values()}) for c, views in by.items() if len(views) > 1
    }
    return {
        "conflicts": verdict_dict["conflicted"],
        "companies_with_differing_views": {c: d for c, d in spread.items() if len(d) > 1},
        "lenses_that_failed": [f["role"] for f in verdict_dict["findings"] if f["outcome"] != "ok"],
        "assessments_dropped": {
            f["role"]: len(f["dropped"]) for f in verdict_dict["findings"] if f["dropped"]
        },
        "disagreement_found": bool(verdict_dict["conflicted"]) or any(len(d) > 1 for d in spread.values()),
        "coverage": analyst_coverage(verdict_dict),
    }


def _dis_text(d: dict[str, Any]) -> str:
    if d.get("disagreement_found") is None:
        return "not assessed (insufficient analyst coverage)"
    return "YES" if d["disagreement_found"] else "no"


def run_council(
    pack: council.EvidencePack,
    env: Any,
    ledger: cl.Ledger,
    ctx: dict[str, Any],
    clock: Callable[[], datetime],
    chain_for: Callable[..., Any] = build_chain,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Run the three lenses and the synthesis. Returns (verdict dict or None, models report). The models
    report lists
    what was CONFIGURED and what actually ANSWERED; only the second is a claim of connection."""
    notes: list[str] = []
    gateways: dict[str, Any] = {}

    def gateway_for(role: str) -> Any:
        if role not in gateways:
            provider, n = chain_for(role, env, ledger, ctx, clock)
            notes.extend(n)
            if provider is None:
                raise council.CouncilError("not connected: " + "; ".join(sorted(set(notes))))
            inner = llm.LLMGateway(
                provider=provider,
                pricing=llm.Pricing(0.0, 0.0),
                limits=llm.Limits.from_env(),
                sleep=lambda seconds: SLEEP(seconds),
            )
            gateways[role] = _CtxGateway(inner, ctx, role)
        return gateways[role]

    models: dict[str, Any] = {"configured": configured_accounts(env), "notes": notes}
    try:
        verdict = council.deliberate(pack, gateway_for)
    except council.CouncilError as exc:
        models["answered"] = []
        models["error"] = str(exc)[:300]
        return None, models
    d = verdict.to_dict()
    answered = sorted(
        {f"{f['provider']}|{f['model']}" for f in d["findings"] if f["outcome"] == "ok" and f["model"]}
    )
    models["answered"] = answered
    models["distinct_models_verified"] = len({a.split("|")[1] for a in answered})
    models["lenses"] = {
        f["role"]: {
            "outcome": f["outcome"],
            "provider": f["provider"] or None,
            "model": f["model"] or None,
            "prompt": f"{f['prompt_id']}@{f['prompt_version']}",
            "error": f["error"],
        }
        for f in d["findings"]
    }
    models["claim"] = (
        f"{sum(1 for f in d['findings'] if f['outcome'] == 'ok')} of 3 lenses answered, on "
        f"{models['distinct_models_verified']} distinct verified model(s)"
    )
    return d, models


def time_tags(now: datetime, calendar: Any | None) -> dict[str, Any]:
    local = now.astimezone(ni.PKT)
    day = local.strftime("%Y-%m-%d")
    minute = local.hour * 60 + local.minute
    if calendar is None:
        return {
            "pkt_day": day,
            "weekend": local.weekday() >= 5,
            "holiday": "unknown",
            "after_hours": "unknown",
        }
    dt = calendar.day_type(day)
    return {
        "pkt_day": day,
        "pkt_time": local.strftime("%H:%M"),
        "day_type": dt,
        "weekend": dt == market_calendar.WEEKEND,
        "holiday": dt
        == market_calendar.HOLIDAY,  # only holidays recorded in config/psx_calendar.json are known
        "after_hours": not calendar.in_open_session(day, minute),
    }


def execute_item(
    item: dict[str, Any],
    *,
    db: Any,
    env: Any,
    ledger: cl.Ledger,
    clock: Callable[[], datetime],
    build_pack: Callable[..., Any],
    calendar: Any | None,
    exec_id: str,
    mode: str,
    chain_for: Callable[..., Any] = build_chain,
    pack_db: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Run the council for one reserved queue item and return its dry-run record. Never writes to the
    database."""
    started = clock()
    payload = item["payload"]
    ctx: dict[str, Any] = {"event": item["key"], "exec": exec_id, "role": None}
    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA,
        "mode": mode,
        "execution_id": exec_id,
        "started_at_utc": cl.stamp(started),
        "time": time_tags(started, calendar),
        "event": {
            "key": item["key"],
            "event_id": item["event_id"],
            "version": item["version"],
            "kind": payload["kind"],
            "headline": payload["title"],
            "queued_at_utc": item.get("flagged_at"),
            "attempt": item.get("attempts"),
            "distinct_outlets": len({m["source"] for m in payload["members"] if m["source"] != "rollup"}),
            "single_source": len({m["source"] for m in payload["members"]}) <= 1,
            "provenance": [
                {
                    "source": m["source"],
                    "url": m["url"],
                    "published_at": m["published_at"],
                    "reliability": ni.reliability(m["source"]),
                }
                for m in payload["members"]
            ],
        },
        "classification": {
            "priority": item["priority"],
            "rules": [
                {"rule": h["rule"], "name": ni.RULE_NAMES[h["rule"]], "detail": h["detail"]}
                for h in payload["hits"]
            ],
            "companies": payload["companies"],
            "sectors": payload["sectors"],
            "macro": payload["macro"],
        },
        "errors": [],
    }
    verdict, models = None, {}
    try:
        pack = pack_for(payload, pack_db() if pack_db else db, build_pack)
        record["pack"] = {
            "items": len(pack.items),
            "companies": list(pack.companies),
            "evidence_ids": sorted(pack.ids),
        }
        verdict, models = run_council(pack, env, ledger, ctx, clock, chain_for)
        if verdict is None:
            record["errors"].append(models.get("error", "the council did not answer"))
    except (ReadOnlyViolation, IdentityError):
        raise
    except Exception as exc:  # noqa: BLE001 - one event's failure must not stop the others; it is recorded
        record["errors"].append(f"{type(exc).__name__}: {str(exc)[:200]}")
    record["models"] = models
    if verdict is not None:
        record["assessment"] = structure_assessment(
            verdict, pack, [s.split(":", 1)[1] for s in payload["sectors"]]
        )
        record["model_disagreement"] = disagreement(verdict)
        if record["model_disagreement"]["coverage"]["status"] != "full":
            # fewer than three analysts on three families: the spread between the ones that answered is
            # reported but not counted as a disagreement finding, and no consensus is claimed
            record["model_disagreement"]["disagreement_found"] = None
            record["model_disagreement"]["note"] = "not assessed: INSUFFICIENT_ANALYST_COVERAGE"
        record["narrative"] = verdict.get("narrative")
        record["narrative_error"] = verdict.get("narrative_error")
    else:
        record["assessment"] = None  # unknown, not zero
    ended = clock()
    calls = [
        c for c in ledger.snapshot()["calls"] if c.get("event") == item["key"] and c.get("exec") == exec_id
    ]
    tin = [c["input_tokens"] for c in calls if c["outcome"] == "ok"]
    tout = [c["output_tokens"] for c in calls if c["outcome"] == "ok"]
    record["cost"] = {
        "llm_calls": len(calls),
        "calls_by_outcome": {
            o: sum(1 for c in calls if c["outcome"] == o) for o in sorted({c["outcome"] for c in calls})
        },
        "calls_by_account": {
            a: sum(1 for c in calls if f"{c['vendor']}#{c['account']}" == a)
            for a in sorted({f"{c['vendor']}#{c['account']}" for c in calls})
        },
        "input_tokens": sum(tin) if tin and all(t is not None for t in tin) else None,
        "output_tokens": sum(tout) if tout and all(t is not None for t in tout) else None,
        "usd": None,
        "usd_basis": "not metered: free-tier accounts only, no paid fallback",
        "model_time_ms": sum(c["ms"] for c in calls) if calls else None,
    }
    record["ended_at_utc"] = cl.stamp(ended)
    record["duration_s"] = round((ended - started).total_seconds(), 1)
    record["outcome"] = "assessed" if verdict is not None else "failed"
    return record


def run_summary(record: dict[str, Any]) -> dict[str, Any]:
    """The compact line kept in the ledger for the seven-day report."""
    dis = record.get("model_disagreement") or {}
    return {
        "ts": record["started_at_utc"],
        "mode": record["mode"],
        "key": record["event"]["key"],
        "kind": record["event"]["kind"],
        "rules": [r["rule"] for r in record["classification"]["rules"]],
        "outcome": record["outcome"],
        "time": record["time"],
        "lenses_ok": sum(1 for v in (record["models"].get("lenses") or {}).values() if v["outcome"] == "ok"),
        "disagreement": dis.get("disagreement_found"),
        "calls": record["cost"]["llm_calls"],
        "errors": record["errors"][:3],
        "duration_s": record["duration_s"],
    }


def window_start(now: datetime, cursor: str | None) -> datetime:
    """Far enough back to cover the whole Pakistan-local day (rule 4 counts distinct events per day) and
    a short
    overlap before the last execution's cursor."""
    local_midnight = now.astimezone(ni.PKT).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    base = (
        datetime.strptime(cursor, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) - timedelta(hours=6)
        if cursor
        else now - timedelta(hours=48)
    )
    return min(base, local_midnight)


ANNOUNCEMENT_SCAN_HOURS = 6


def execution(
    *,
    db: Any,
    env: Any,
    ledger: cl.Ledger,
    now: datetime,
    exec_id: str,
    vocab: nf.Vocabulary,
    signals_for: Callable[[Any, datetime], tuple[list[dict[str, Any]], dict[str, Any]]],
    build_pack: Callable[..., Any],
    calendar: Any | None,
    chain_for: Callable[..., Any] = build_chain,
    pack_db: Callable[[], Any] | None = None,
    announcement_events: Callable[[Any, datetime], list[ni.Event]] | None = None,
) -> dict[str, Any]:
    """One automatic dry-run execution (one per collector run). Returns {'records': [...], 'summary':
    {...}}."""
    assert_library_identity(db)
    since = window_start(now, ledger.cursor())
    headlines = load_headlines(db, since, now)
    events = ni.cluster(headlines, ledger.known_events(), vocab)
    ni.classify(vocab, events)
    signals, baseline = signals_for(db, now)
    extra = ni.concentration_events(events) + ni.signal_events(signals, ni.local_day(now))
    gate: dict[str, Any] = {"scanned": False, "events": 0, "error": None}
    if announcement_events is not None and ledger.scan_due("announcements", now, ANNOUNCEMENT_SCAN_HOURS):
        gate["scanned"] = True
        try:
            found = announcement_events(db, now)
            extra += found
            gate["events"] = len(found)
        except Exception as exc:  # noqa: BLE001 - a gate failure must never stop the news run
            gate["error"] = f"{type(exc).__name__}: {exc}"[:200]
        ledger.mark_scan("announcements", now)
    ledger.register_events(events)
    queued = {"queued": 0, "already_queued": 0, "already_assessed": 0}
    for e in ni.prioritised(events + extra, now):
        queued[ledger.enqueue(e, ni.priority(e, now), now)] += 1
    day = ni.local_day(now)
    items = ledger.reserve_batch(exec_id, now, day)
    records = []
    for item in items:
        rec = execute_item(
            item,
            db=db,
            env=env,
            ledger=ledger,
            clock=lambda: datetime.now(UTC),
            build_pack=build_pack,
            calendar=calendar,
            exec_id=exec_id,
            mode="auto",
            chain_for=chain_for,
            pack_db=pack_db,
        )
        ledger.finish(
            item["key"],
            rec["outcome"] if rec["outcome"] == "assessed" else "; ".join(rec["errors"]) or "failed",
            datetime.now(UTC),
            ok=rec["outcome"] == "assessed",
        )
        ledger.log_run(run_summary(rec))
        records.append(rec)
    if headlines:
        ledger.set_cursor(max(h.published_at for h in headlines))
    pending = ledger.pending()
    summary = {
        "exec_id": exec_id,
        "ts": cl.stamp(now),
        "time": time_tags(now, calendar),
        "headlines_read": len(headlines),
        "events": len(events),
        "flagged": len(ni.flagged(events + extra)),
        "queue_changes": queued,
        "ran": len(records),
        "runs_today": ledger.runs_on(day),
        "cap_day": cl.CAP_PER_DAY,
        "cap_exec": cl.CAP_PER_EXECUTION,
        "pending_after": len(pending),
        "needs_review": sum(1 for p in pending if p["state"] == "needs_review"),
        "baseline": baseline,
        "announcement_gate": gate,
        "db_usage": db.usage(),
    }
    ledger.log_execution(summary)
    return {"records": records, "summary": summary}


# --- the 10-headline review -------------------------------------------------------------------------------


def pick_ten(events: list[ni.Event], now: datetime, count: int = 10) -> list[tuple[ni.Event, str]]:
    """Up to `count` real events for the owner to review: the best flagged event for each rule that
    fired, then the
    next highest-priority flagged events, then up to three unflagged CONTROLS that name a company (to
    show what the
    rules leave out). Each is labelled 'flagged' or 'control'."""
    ranked = ni.prioritised(events, now)
    plain = [e for e in events if not e.hits and e.companies and e.kind == "headline"]
    plain.sort(key=lambda e: e.first_seen, reverse=True)
    room = count - min(3, len(plain))
    chosen: list[ni.Event] = []
    for rule in (7, 1, 2, 5, 3, 6, 4):  # the best event for each rule that fired
        best = next((e for e in ranked if any(h.rule == rule for h in e.hits) and e not in chosen), None)
        if best and len(chosen) < room:
            chosen.append(best)
    for e in ranked:  # then the next highest priority
        if len(chosen) >= room:
            break
        if e not in chosen:
            chosen.append(e)
    out = [(e, "flagged") for e in chosen]
    out += [(e, "control") for e in plain[: count - len(out)]]
    return out[:count]


def pick_focus(
    events: list[ni.Event], now: datetime, symbols: set[str], count: int = 3
) -> list[tuple[ni.Event, str]]:
    """Real events naming one of the chosen companies, best-corroborated and newest first, labelled 'focus'.

    Unlike pick_ten this does not require a rule to have fired: the owner chose the company, so its
    headlines are assessed whether or not the importance rules flagged them. Concentration and signal
    events are included only when they name the company."""
    named = [e for e in events if symbols & set(e.companies)]
    named.sort(key=lambda e: e.first_seen, reverse=True)  # newest first, then the most-corroborated first
    named.sort(key=lambda e: -len({m.source for m in e.members}))
    return [(e, "focus") for e in named[:count]]


def payload_for(e: ni.Event) -> dict[str, Any]:
    return cl.event_payload(e)


def review_markdown(records: list[dict[str, Any]], labels: dict[str, str]) -> str:
    lines = [
        "# Council dry run: 10 real headlines for review",
        "",
        "No analytical result was stored anywhere.",
        "",
    ]
    for i, r in enumerate(records, start=1):
        e, c = r["event"], r["classification"]
        a = r.get("assessment")
        lines += [
            f"## {i}. {e['headline']}",
            f"- **{labels.get(e['key'], '')}** | outlets: {e['distinct_outlets']} "
            f"({', '.join(sorted({p['source'] for p in e['provenance']}))}) | priority {c['priority']}",
            "- rules: "
            + ("; ".join(f"{x['rule']} {x['name']} ({x['detail']})" for x in c["rules"]) or "none (control)"),
            f"- companies: {', '.join(c['companies']) or 'none'} | "
            f"sectors: {', '.join(c['sectors']) or 'none'}",
            f"- models: {r['models'].get('claim') or r['models'].get('error') or 'not connected'}",
        ]
        if a:
            for co in a["affected_companies"]:
                views = ", ".join(
                    f"{k}: {v['direction']} ({v['confidence']})" for k, v in co["lenses"].items()
                )
                lines.append(f"- {co['entity']}: **{co['consensus']}** | {views}")
            for s in a["sector_impact"]:
                lines.append(f"- {s['entity']}: {s['consensus']}")
            d = r["model_disagreement"]
            lines.append(
                f"- disagreement: {_dis_text(d)} {d['conflicts'] or ''}"
            )
        lines += [
            f"- calls: {r['cost']['llm_calls']} ({r['cost']['calls_by_outcome']}), "
            f"tokens in/out: {r['cost']['input_tokens']}/{r['cost']['output_tokens']}, {r['duration_s']}s",
            f"- errors: {r['errors'] or 'none'}",
            "",
        ]
    return "\n".join(lines)


def jsonl(records: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records)


def ledger_path(env: Any = None) -> Path:
    env = os.environ if env is None else env
    return Path(str(env.get("PSXNI_COUNCIL_LEDGER") or ".council_dryrun/ledger.json"))


# --- the seven-day report ---------------------------------------------------------------------------


def model_availability(calls: list[dict[str, Any]]) -> list[str]:
    """One row per analyst and model actually called: family, successful and failed calls, rate limits, and
    whether it was the primary or a fallback."""
    roles = {"news": "news", "financial": "financial", "macro": "macro"}
    rows = [
        "| analyst | provider | model | family | primary or fallback | ok | rate-limited (429) | "
        "other failed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    seen: dict[tuple[str, str, str], dict[str, int]] = {}
    for c in calls:
        role = str(c.get("role", "")).split(":")[0]
        if role not in roles:
            continue
        key = (role, c["vendor"], c.get("model") or "unknown")
        s = seen.setdefault(key, {"ok": 0, "rl": 0, "bad": 0})
        if c["outcome"] == "ok":
            s["ok"] += 1
        elif "429" in str(c.get("error") or ""):
            s["rl"] += 1
        else:
            s["bad"] += 1
    for (role, vendor, model), s in sorted(seen.items()):
        pins = INDEPENDENT_MODELS.get(role, ())
        order = next((i for i, (_v, m) in enumerate(pins) if m == model), None)
        kind = "unpinned (older chain)" if order is None else ("primary" if order == 0 else "fallback")
        rows.append(
            f"| {role} | {vendor} | {model} | {family_of(model)} | {kind} | "
            f"{s['ok']} | {s['rl']} | {s['bad']} |"
        )
    if len(rows) == 2:
        rows.append("| none | | | | | | | |")
    return rows


def seven_day_report(snapshot: dict[str, Any], now: datetime, days: int = 7) -> str:
    """What the seven consecutive dry-run days show, from the ledger: coverage (weekends, holidays, after
    hours), runs against the caps, outcomes, model disagreement, calls and errors. Missing stays 'unknown'."""
    wanted = [
        (now.astimezone(ni.PKT) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days - 1, -1, -1)
    ]
    ex_by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in wanted}
    for e in snapshot["execution_log"]:
        ex_by_day.setdefault(e["time"]["pkt_day"], []).append(e)
    runs_by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in wanted}
    for r in snapshot["runs"]:
        if r.get("mode") == "auto":
            runs_by_day.setdefault(r["time"]["pkt_day"], []).append(r)
    head = (
        "| Pakistan day | type | collection executions | events seen (max in one execution) | flagged | "
        "council runs | assessed | failed | disagreement | after |"
    )
    lines = [
        f"# Council dry run: {days}-day report (to {now.astimezone(ni.PKT):%Y-%m-%d %H:%M} PKT)",
        "",
        head,
    ]
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    streak = best = weekends = holidays = 0
    for d in wanted:
        ex, rs = ex_by_day[d], runs_by_day[d]
        tags = ex[0]["time"] if ex else {}
        weekends += 1 if tags.get("weekend") else 0
        holidays += 1 if tags.get("holiday") is True else 0
        flagged = max((e["flagged"] for e in ex), default=None)
        seen = max((e["events"] for e in ex if "events" in e), default=None)
        assessed = sum(1 for r in rs if r["outcome"] == "assessed")
        dis = sum(1 for r in rs if r.get("disagreement"))
        after = sum(1 for r in rs if r["time"].get("after_hours") is True)
        lines.append(
            f"| {d} | {tags.get('day_type') or 'no executions'} | {len(ex)} | "
            f"{'unknown' if seen is None else seen} | "
            f"{'unknown' if flagged is None else flagged} | {len(rs)} | {assessed} | {len(rs) - assessed} | "
            f"{dis} | {after} |"
        )
        streak = streak + 1 if ex else 0
        best = max(best, streak)
    calls = [c for c in snapshot["calls"] if c["ts"] >= cl.stamp(now - timedelta(days=days))]
    by_out: dict[str, int] = {}
    by_acct: dict[str, int] = {}
    for c in calls:
        by_out[c["outcome"]] = by_out.get(c["outcome"], 0) + 1
        key = f"{c['vendor']}#{c['account']}"
        by_acct[key] = by_acct.get(key, 0) + 1
    all_runs = [r for rs in runs_by_day.values() for r in rs]
    pend = [q for q in snapshot["queue"] if q["state"] in ("pending", "reserved", "needs_review")]
    review = sum(1 for q in pend if q["state"] == "needs_review")
    errors = sorted({e for r in all_runs for e in r["errors"]})[:10]
    short = sum(1 for r in all_runs if isinstance(r["lenses_ok"], int) and r["lenses_ok"] < 3)
    answering = sorted({r["lenses_ok"] for r in all_runs}) or "unknown"
    lines += ["", "Model availability per analyst (calls in the window):", ""]
    lines += model_availability(calls)
    lines += [
        "",
        f"- consecutive days with at least one execution: **{best}** of {days}",
        f"- weekend days covered: {weekends}; recorded holidays covered: {holidays} "
        "(only holidays recorded in config/psx_calendar.json are known)",
        f"- council runs: {len(all_runs)} (cap {cl.CAP_PER_DAY} a day, {cl.CAP_PER_EXECUTION} an execution); "
        f"lenses answering per run: {answering}",
        f"- LLM calls: {len(calls)} {by_out or ''}; by account: {by_acct or 'none'}",
        f"- queue now: {len(pend)} waiting, {review} needing review; by state: "
        f"{dict(sorted(Counter(q['state'] for q in snapshot['queue']).items()))} "
        "(covered = a similar story was assessed within 36 hours; nothing is deleted)",
        f"- analysts unavailable in a run (fewer than 3 lenses answered): {short} of {len(all_runs)}",
        f"- distinct errors: {errors or 'none'}",
    ]
    return "\n".join(lines)
