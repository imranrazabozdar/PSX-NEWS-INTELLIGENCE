"""Company universe and liquidity qualification (master plan M1; policy in MASTER_ARCHITECTURE.md §3).

Two independent lists, never merged:
* The PRIORITY list is the owner's manually curated stocks (`user_watchlist`, item_type 'ticker'). Only the
  owner adds or disables entries. Liquidity, storage budgets or missing data never remove a priority stock.
* LIQUIDITY qualification is computed per symbol from stored SCS daily bars over the latest 20 trading
  sessions: average daily volume against the initial 100,000-share threshold, with average traded value
  (close x volume, an approximation labelled as such) and session coverage reported alongside.

Liquidity gates only market analytics (and, by owner decision U7, the intraday universe). News, fundamentals,
macro and event monitoring use the whole company master regardless of liquidity.

States: qualified | below_threshold | insufficient_data (fewer than 20 stored sessions; no ADV is stated) |
no_market_data. Missing sessions are never treated as zero volume.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

SESSIONS = 20
ADV_THRESHOLD_SHARES = 100_000  # initial policy value; owner may revise under U9
TRADED_VALUE_THRESHOLD_PKR = None  # not set (U9): reported, not used as a gate


@dataclass
class Liquidity:
    symbol: str
    state: str
    sessions: int
    adv_shares: float | None = None
    avg_traded_value_pkr_approx: float | None = None
    first_session: str | None = None
    last_session: str | None = None
    reasons: list[str] = field(default_factory=list)


def priority_list(db) -> list[str]:
    return [r["value"] for r in db.execute(
        "SELECT value FROM user_watchlist WHERE item_type = 'ticker' AND enabled = 1 ORDER BY value")]


def add_priority(db, tickers: list[str]) -> dict:
    """Add owner-supplied tickers. Never deletes or disables anything; re-adding is a no-op."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    added = []
    for t in tickers:
        t = t.strip().upper()
        if not t or not t.isalnum():
            raise ValueError(f"invalid ticker {t!r}")
        if not db.execute("SELECT 1 FROM user_watchlist WHERE item_type = 'ticker' AND value = ?", (t,)):
            db.execute("INSERT INTO user_watchlist(item_type, value, enabled, created_at_utc) "
                       "VALUES ('ticker', ?, 1, ?)", (t, now))
            added.append(t)
    return {"added": added, "priority_count": len(priority_list(db))}


def liquidity(db, symbol: str, *, as_of: str | None = None, source_id: str = "scs_chart") -> Liquidity:
    rows = db.execute(
        "SELECT session_date_pkt, close, volume FROM market_bars_current WHERE source_id = ? AND symbol = ? "
        "AND timeframe = '1d' AND (? IS NULL OR session_date_pkt <= ?) "
        "ORDER BY session_date_pkt DESC LIMIT ?",
        (source_id, symbol, as_of, as_of, SESSIONS),
    )
    if not rows:
        return Liquidity(symbol, "no_market_data", 0, reasons=["no stored daily bars"])
    out = Liquidity(symbol, "insufficient_data", len(rows), first_session=rows[-1]["session_date_pkt"],
                    last_session=rows[0]["session_date_pkt"])
    if len(rows) < SESSIONS:
        out.reasons.append(f"{len(rows)} of {SESSIONS} sessions stored; ADV not stated")
        return out
    out.adv_shares = sum(r["volume"] for r in rows) / SESSIONS
    out.avg_traded_value_pkr_approx = sum(r["volume"] * r["close"] for r in rows) / SESSIONS
    out.state = "qualified" if out.adv_shares >= ADV_THRESHOLD_SHARES else "below_threshold"
    out.reasons.append(f"ADV {out.adv_shares:,.0f} vs threshold {ADV_THRESHOLD_SHARES:,}")
    return out


def universe(db, *, as_of: str | None = None, source_id: str = "scs_chart") -> list[dict]:
    """Every listed company plus every priority ticker, with both memberships shown separately."""
    priority = set(priority_list(db))
    master = {r["ticker"]: r for r in db.execute(
        "SELECT ci.value AS ticker, c.company_id, c.legal_name FROM company_identifiers ci "
        "JOIN companies c USING(company_id) WHERE ci.id_type = 'psx_ticker' AND ci.valid_to IS NULL")}
    out = []
    for t in sorted(priority | set(master)):
        liq = liquidity(db, t, as_of=as_of, source_id=source_id)
        out.append({
            "ticker": t,
            "company_id": master[t]["company_id"] if t in master else None,
            "in_company_master": t in master,
            "priority": t in priority,
            "liquidity_state": liq.state,
            "adv_shares": liq.adv_shares,
            "avg_traded_value_pkr_approx": liq.avg_traded_value_pkr_approx,
            "sessions": liq.sessions,
            "broad_monitoring": True,  # news / fundamentals / macro / events are never liquidity-filtered
            "market_analytics_eligible": t in priority or liq.state == "qualified",
        })
    return out
