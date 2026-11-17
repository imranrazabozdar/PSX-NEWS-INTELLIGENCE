"""Material announcements as council events (rule 8). Deterministic, read only, no model.

The numbers engine (engines/announcement_substance.py) reads each recent announcement's text and grades its
size and stage. This module turns the ones worth a second opinion into events for the council's existing
queue, so the council's daily and per-execution caps, its quota tracking and its "never discard" queue apply
to them exactly as they do to news. An announcement becomes an event when EITHER:

  * the numbers engine grades it major or significant (a stated stake or amount that is large against the
    company's own size), OR
  * it is a material announcement and the stock reacted: volume of at least REACTION_VOLUME_X its previous
    20-session average, or a close-to-close move of at least REACTION_MOVE percent, on the announcement day
    or the next session.

Everything else stays with the numbers engine alone. The scan reads recent facts only (the company/date
index) and is meant to run at most a few times a day; the caller decides when.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

from engines import announcement_substance as asub
from engines import company_names
from engines import news_importance as ni
from engines import research_facts as rf

COLS = "company, topic, fact_text, value, unit, period, source_name, source_url, source_date"
LOOKBACK_DAYS = 2  # announcements dated within this many days (Pakistan calendar) are considered
READ_DAYS = LOOKBACK_DAYS + 2  # the facts' own dates can lag the announcement date by the load time
GATE_TIERS = ("major", "significant")
REACTION_VOLUME_X = 5.0
REACTION_MOVE = 4.0
MAX_EVENTS = 12  # a scan never queues more than this many; the rest are seen again next scan, never lost


def reaction(bars: list[dict[str, Any]], day: str) -> dict[str, float] | None:
    """The stock's reaction on `day` and the next session: volume against the previous 20 sessions and the
    close-to-close move, whichever session shows the larger volume. None when there are too few sessions
    to say (unknown, never zero)."""
    rows = sorted(bars, key=lambda b: str(b["trade_date"]))
    first = [i for i, b in enumerate(rows) if str(b["trade_date"]) >= day][:2]
    best: dict[str, float] | None = None
    for i in first:
        if i < 20:
            continue
        base = statistics.fmean(float(x["volume"]) for x in rows[i - 20 : i])
        prev = float(rows[i - 1]["close"])
        if base <= 0 or prev <= 0:
            continue
        cand = {
            "volume_x": float(rows[i]["volume"]) / base,
            "move": (float(rows[i]["close"]) / prev - 1) * 100,
        }
        if best is None or cand["volume_x"] > best["volume_x"]:
            best = cand
    return best


def gate(result: dict[str, Any], react: dict[str, float] | None) -> str | None:
    """Why this announcement goes to the council, in plain words, or None to leave it with the numbers."""
    if result["tier"] in GATE_TIERS:
        return f"size graded {result['tier']}"
    if result["tier"] == "routine":
        return None
    if react and (react["volume_x"] >= REACTION_VOLUME_X or abs(react["move"]) >= REACTION_MOVE):
        return f"the stock reacted (volume {react['volume_x']:.1f}x, move {react['move']:+.1f}%)"
    return None


def to_event(symbol: str, day: str, title: str, why: str, detail: str, url: str) -> ni.Event:
    key = asub.title_key(title)
    member = ni.Headline("investify", url, f"{title}", f"{day}T00:00:00Z")
    return ni.Event(
        event_id=f"ann-{symbol}-{key}",
        anchor=frozenset({f"announcement:{symbol}:{key}"}),
        members=[member],
        kind="announcement",
        title=f"{symbol}: {title}",
        hits=[ni.RuleHit(8, f"{why}; {detail}", (symbol,))],
        companies=[symbol],
        day=day,
    )


def build(
    db: Any,
    now: datetime,
    symbols: Iterable[str] | None = None,
    *,
    max_events: int = MAX_EVENTS,
) -> list[ni.Event]:
    """Events for the recent material announcements that pass the gate, best first. Raises on a database
    error: the caller decides whether that stops the execution (it does not)."""
    today = now.date()
    since = (today - timedelta(days=READ_DAYS)).isoformat()
    floor = (today - timedelta(days=LOOKBACK_DAYS)).isoformat()
    universe = sorted(set(symbols) if symbols is not None else _listed())
    by_company: dict[str, list[dict[str, Any]]] = {}
    for r in rf.facts_for(db, universe, COLS, since=since):
        f = dict(r)
        if str(f["topic"]).startswith("announcements.") or f["topic"] == asub.HIGHLIGHTS_TOPIC:
            by_company.setdefault(f["company"], []).append(f)
    candidates = []
    for sym, facts in by_company.items():
        for f in facts:
            label = str(f["topic"])[len("announcements.") :]
            if not str(f["topic"]).startswith("announcements.") or label not in asub.MATERIAL_LABELS:
                continue
            day = str(f.get("period") or f["source_date"])
            if day < floor:
                continue
            candidates.append((sym, day, label, f, facts))
    if not candidates:
        return []
    caps = _market_caps(db, sorted({c[0] for c in candidates}), today)
    bars = _bars(db, sorted({c[0] for c in candidates}), today)
    scored = []
    for sym, day, label, f, facts in candidates:
        title = str(f["fact_text"]).split(": ", 1)[-1]
        high = asub.highlight_text(facts, str(f.get("period")), title)
        result = asub.assess(
            label,
            f["fact_text"],
            company_names=company_names.names_for(sym),
            mcap=caps.get(sym),
            highlights=high,
        )
        react = reaction(bars.get(sym, []), day) if bars.get(sym) else None
        why = gate(result, react)
        if why is None:
            continue
        detail = "; ".join(result["basis"][:2]) or "no size stated"
        url = str(f.get("source_url") or f"https://investify.pk/company/{sym}/announcements")
        scored.append((result["points"], day, to_event(sym, day, title, why, detail, url)))
    scored.sort(key=lambda s: (-s[0], s[1]))  # larger size first, then earliest
    seen: set[str] = set()
    out = []
    for _p, _d, e in scored:
        if e.event_id in seen:
            continue  # the same announcement can appear in two chunks or two loads
        seen.add(e.event_id)
        out.append(e)
    return out[:max_events]


def _listed() -> list[str]:
    return sorted(company_names._index())


def _market_caps(db: Any, symbols: list[str], today: date) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rf.facts_for(
        db, symbols, "company, topic, fact_text, source_date", since=(today - timedelta(days=120)).isoformat()
    ):
        if r["topic"] == "fundamentals.market_cap":
            by.setdefault(r["company"], []).append(dict(r))
    for s in symbols:
        out[s] = asub.market_cap(by.get(s, []))
    return out


def _bars(db: Any, symbols: list[str], today: date) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    since = (today - timedelta(days=45)).isoformat()
    for s in symbols:
        try:
            rows = db.execute(
                "SELECT trade_date, close, volume FROM price_daily WHERE symbol = ? AND trade_date >= ? "
                "ORDER BY trade_date",
                (s, since),
            )
        except Exception as exc:  # noqa: BLE001 - table not there yet: no reaction evidence, never a crash
            if "budget" in str(exc).lower():
                raise
            return {}
        out[s] = [dict(r) for r in rows]
    return out


def contradiction(council_magnitude: str | None, tier: str, stage: str) -> str | None:
    """Flag where the council's reading and the numbers engine disagree, in plain words, else None.
    Shown side by side in the dry-run output; neither one overrides the other."""
    mag = (council_magnitude or "").lower()
    if mag == "high" and (stage == "preliminary" or tier in ("minor", "unquantified", "routine")):
        return f"council says high; the filing grades {tier}, stage {stage}"
    if mag in ("low", "none") and tier == "major" and stage != "preliminary":
        return f"council says {mag}; the filing grades major, stage {stage}"
    return None
