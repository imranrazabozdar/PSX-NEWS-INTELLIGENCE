"""Portfolio, theses and alerts (master plan M8). Monitoring only: no orders, no execution, no advice.

* Lives in a SEPARATE database (`database/portfolio_migrations`, credentials PSXNI_PORTFOLIO_DATABASE_URL /
  PSXNI_PORTFOLIO_AUTH_TOKEN). `connect_portfolio` refuses the research database URL. The research database
  is only read (prices, assessments, events); nothing about holdings is written to it.
* Every read and write is scoped by owner_id; one owner's data is never returned to another. Whether the
  platform is single- or multi-user, and how owners authenticate, is owner decision U8: until then this is
  used single-owner from the CLI / tests only, and no dashboard page exposes it.
* Thesis conditions use owner-set thresholds only (none is defaulted, U9). A condition whose data is missing
  is `not_evaluable`, never assumed to hold.
"""

from __future__ import annotations

import json
import operator
import os
from datetime import UTC, datetime
from pathlib import Path

from database.connection import DatabaseConfigError, connect
from database.migrate import migrate

PORTFOLIO_MIGRATIONS = Path(__file__).resolve().parents[1] / "database" / "portfolio_migrations"
OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, "!=": operator.ne}


class PortfolioError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect_portfolio(url: str | None = None, auth_token: str | None = None):
    url = url if url is not None else os.environ.get("PSXNI_PORTFOLIO_DATABASE_URL", "")
    if not url:
        raise DatabaseConfigError("PSXNI_PORTFOLIO_DATABASE_URL is not set")
    research = os.environ.get("PSXNI_TURSO_DATABASE_URL", "")
    if research and url.rstrip("/") == research.rstrip("/") and "memory" not in url:
        raise DatabaseConfigError("the portfolio database must be separate from the research database")
    token = auth_token if auth_token is not None else os.environ.get("PSXNI_PORTFOLIO_AUTH_TOKEN", "")
    return connect(url, token)


def migrate_portfolio(pdb) -> list[str]:
    return migrate(pdb, directory=PORTFOLIO_MIGRATIONS)


def create_portfolio(pdb, owner_id: str, name: str) -> int:
    if not owner_id.strip():
        raise PortfolioError("owner_id is required")
    pdb.execute("INSERT INTO portfolios(owner_id, name, created_at_utc) VALUES (?,?,?) ON CONFLICT DO "
                "NOTHING",
                (owner_id, name, _now()))
    return pdb.execute("SELECT portfolio_id FROM portfolios WHERE owner_id = ? AND name = ?",
                       (owner_id, name))[0]["portfolio_id"]


def _own(pdb, owner_id: str, portfolio_id: int) -> None:
    if not pdb.execute("SELECT 1 FROM portfolios WHERE portfolio_id = ? AND owner_id = ?",
                       (portfolio_id, owner_id)):
        raise PortfolioError("portfolio not found for this owner")


def add_transaction(pdb, owner_id: str, portfolio_id: int, *, ticker: str, trade_date: str, side: str,
                    quantity: float, price: float | None = None, fees: float = 0.0,
                    note: str | None = None) -> int:
    _own(pdb, owner_id, portfolio_id)
    if side == "sell":
        held = holdings(pdb, owner_id, portfolio_id).get(ticker, {}).get("quantity", 0.0)
        if quantity > held + 1e-9:
            raise PortfolioError(f"sell of {quantity} exceeds holding of {held} {ticker}")
    pdb.execute("INSERT INTO transactions(portfolio_id, owner_id, ticker, trade_date, side, quantity, "
                "price, fees, "
                "note, recorded_at_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (portfolio_id, owner_id, ticker, trade_date, side, quantity, price, fees, note, _now()))
    return pdb.execute("SELECT MAX(txn_id) AS t FROM transactions WHERE owner_id = ?", (owner_id,))[0]["t"]


def holdings(pdb, owner_id: str, portfolio_id: int) -> dict[str, dict]:
    """Quantity and average cost per ticker (average-cost method; fees capitalised on buys)."""
    _own(pdb, owner_id, portfolio_id)
    out: dict[str, dict] = {}
    for t in pdb.execute("SELECT * FROM transactions WHERE owner_id = ? AND portfolio_id = ? "
                         "ORDER BY trade_date, txn_id", (owner_id, portfolio_id)):
        h = out.setdefault(t["ticker"], {"quantity": 0.0, "cost": 0.0, "realised": 0.0, "dividends": 0.0})
        if t["side"] in ("buy", "rights_in"):
            h["cost"] += t["quantity"] * t["price"] + t["fees"]
            h["quantity"] += t["quantity"]
        elif t["side"] == "bonus_in":
            h["quantity"] += t["quantity"]
        elif t["side"] == "sell":
            avg = h["cost"] / h["quantity"] if h["quantity"] else 0.0
            h["realised"] += t["quantity"] * (t["price"] - avg) - t["fees"]
            h["cost"] -= avg * t["quantity"]
            h["quantity"] -= t["quantity"]
        elif t["side"] == "dividend":
            h["dividends"] += t["quantity"] * (t["price"] or 0.0)
    for h in out.values():
        h["avg_cost"] = h["cost"] / h["quantity"] if h["quantity"] > 1e-9 else None
    return out


def valuation(pdb, rdb, owner_id: str, portfolio_id: int, *, as_of: str) -> dict:
    """Mark holdings to the latest stored SCS close (read-only from the research database)."""
    rows, total, missing = [], 0.0, []
    for tk, h in holdings(pdb, owner_id, portfolio_id).items():
        if h["quantity"] <= 1e-9:
            continue
        px = rdb.execute("SELECT session_date_pkt, close FROM market_bars_current WHERE source_id = "
                         "'scs_chart' "
                         "AND symbol = ? AND timeframe = '1d' AND session_date_pkt <= ? "
                         "ORDER BY session_date_pkt DESC LIMIT 1", (tk, as_of))
        sector = rdb.execute(
            "SELECT s.name FROM company_identifiers ci JOIN company_classifications cc USING(company_id) "
            "JOIN sectors s USING(sector_id) WHERE ci.id_type = 'psx_ticker' AND ci.value = ? "
            "AND ci.valid_to IS NULL AND cc.valid_to IS NULL", (tk,))
        r = {"ticker": tk, **h, "sector": sector[0]["name"] if sector else None}
        if not px:
            r.update(state="no_price", market_value=None)
            missing.append(tk)
        else:
            mv = h["quantity"] * px[0]["close"]
            r.update(state="ok", price=px[0]["close"], price_date=px[0]["session_date_pkt"], market_value=mv,
                     unrealised=mv - h["cost"])
            total += mv
        rows.append(r)
    by_sector: dict[str, float] = {}
    for r in rows:
        if r["market_value"] is not None:
            by_sector[r["sector"] or "unclassified"] = by_sector.get(r["sector"] or "unclassified", 0.0) + \
                r["market_value"]
    return {"positions": rows, "market_value_priced": total, "unpriced": missing,
            "sector_weights": {k: v / total for k, v in by_sector.items()} if total else {},
            "note": "weights cover priced positions only" if missing else None}


def add_thesis(pdb, owner_id: str, *, ticker: str, title: str, statement: str, conditions: list[dict]) -> int:
    for c in conditions:
        if c["kind"] in ("ratio", "dimension_state", "liquidity_state") and (
                c.get("threshold") in (None, "") or (c["kind"] == "ratio" and c.get("operator") not in OPS)):
            raise PortfolioError(f"condition {c} needs an owner-set operator and threshold")
    pdb.execute("INSERT INTO theses(owner_id, ticker, title, statement, created_at_utc) VALUES (?,?,?,?,?)",
                (owner_id, ticker, title, statement, _now()))
    tid = pdb.execute("SELECT MAX(thesis_id) AS t FROM theses WHERE owner_id = ?", (owner_id,))[0]["t"]
    for c in conditions:
        pdb.execute("INSERT INTO thesis_conditions(thesis_id, owner_id, kind, subject, operator, threshold, "
                    "description) VALUES (?,?,?,?,?,?,?)",
                    (tid, owner_id, c["kind"], c["subject"], c.get("operator"), c.get("threshold"),
                     c.get("description", "")))
    return tid


def _company(rdb, ticker: str) -> str | None:
    r = rdb.execute("SELECT company_id FROM company_identifiers WHERE id_type = 'psx_ticker' AND value = ? "
                    "AND valid_to IS NULL", (ticker,))
    return r[0]["company_id"] if r else None


def _check(rdb, c: dict, ticker: str, cid: str | None, since: str, as_of: str) -> dict:
    from engines import fundamentals, universe

    res = {"condition_id": c["condition_id"], "kind": c["kind"], "description": c["description"]}
    if cid is None:
        return {**res, "state": "not_evaluable", "reason": "ticker not in the company master"}
    if c["kind"] == "ratio":
        fy = rdb.execute("SELECT MAX(period_end) AS p FROM financial_metrics WHERE company_id = ? AND "
                         "period_type = 'FY' AND period_end <= ?", (cid, as_of))[0]["p"]
        if not fy:
            return {**res, "state": "not_evaluable", "reason": "no reported fiscal-year metrics"}
        r = fundamentals.analyse(rdb, cid, period_end=fy)["ratios"].get(c["subject"])
        if not r or r["state"] != "ok":
            return {**res, "state": "not_evaluable", "reason": f"ratio state {r and r['state']}",
                    "period_end": fy}
        ok = OPS[c["operator"]](r["value"], float(c["threshold"]))
        return {**res, "state": "holds" if ok else "broken", "value": r["value"], "period_end": fy}
    if c["kind"] == "dimension_state":
        r = rdb.execute("SELECT data_state, as_of_date FROM dimension_assessments WHERE company_id = ? AND "
                        "dimension = ? AND as_of_date <= ? ORDER BY as_of_date DESC, assessment_id DESC "
                        "LIMIT 1",
                        (cid, c["subject"], as_of))
        if not r:
            return {**res, "state": "not_evaluable", "reason": "no assessment"}
        return {**res, "state": "holds" if r[0]["data_state"] == c["threshold"] else "broken",
                "value": r[0]["data_state"]}
    if c["kind"] == "liquidity_state":
        st = universe.liquidity(rdb, ticker, as_of=as_of).state
        if st in ("insufficient_data", "no_market_data"):
            return {**res, "state": "not_evaluable", "value": st}
        return {**res, "state": "holds" if st == c["threshold"] else "broken", "value": st}
    ev = rdb.execute(
        "SELECT DISTINCT ia.event_id FROM impact_assessments ia WHERE ia.company_id = ? AND "
        "ia.direction = 'negative' AND ia.created_at_utc >= ?", (cid, since))
    return {**res, "state": "needs_review" if ev else "holds",
            "events": [e["event_id"] for e in ev],
            "note": "negative impact hypotheses since the thesis was created (scenario-level, unverified)"}


def check_theses(pdb, rdb, owner_id: str, *, as_of: str) -> list[dict]:
    out = []
    for t in pdb.execute("SELECT * FROM theses WHERE owner_id = ? AND status = 'active'", (owner_id,)):
        cid = _company(rdb, t["ticker"])
        conds = pdb.execute("SELECT * FROM thesis_conditions WHERE thesis_id = ? AND owner_id = ?",
                            (t["thesis_id"], owner_id))
        res = [_check(rdb, dict(c), t["ticker"], cid, t["created_at_utc"], as_of) for c in conds]
        overall = ("broken" if any(r["state"] == "broken" for r in res) else
                   "needs_review" if any(r["state"] in ("needs_review", "not_evaluable") for r in res)
                   else "holds")
        out.append({"thesis_id": t["thesis_id"], "ticker": t["ticker"], "title": t["title"], "state": overall,
                    "conditions": res})
    return out


def add_alert_rule(pdb, owner_id: str, *, kind: str, ticker: str | None = None) -> int:
    pdb.execute("INSERT INTO alert_rules(owner_id, kind, ticker, created_at_utc) VALUES (?,?,?,?)",
                (owner_id, kind, ticker, _now()))
    return pdb.execute("SELECT MAX(rule_id) AS r FROM alert_rules WHERE owner_id = ?", (owner_id,))[0]["r"]


def run_alerts(pdb, rdb, owner_id: str, *, as_of: str) -> list[dict]:
    """Create alert rows for new matches; each match alerts once (dedupe key)."""
    from engines import universe

    new = []

    def emit(rule, key, msg, ev):
        before = pdb.execute("SELECT 1 FROM alert_events WHERE rule_id = ? AND dedupe_key = ?", (rule, key))
        if not before:
            pdb.execute("INSERT INTO alert_events(rule_id, owner_id, dedupe_key, message, evidence_json, "
                        "created_at_utc) VALUES (?,?,?,?,?,?)",
                        (rule, owner_id, key, msg, json.dumps(ev), _now()))
            new.append({"rule_id": rule, "message": msg, "evidence": ev})

    for r in pdb.execute("SELECT * FROM alert_rules WHERE owner_id = ? AND enabled = 1", (owner_id,)):
        cid = _company(rdb, r["ticker"]) if r["ticker"] else None
        if r["kind"] == "new_event" and cid:
            for e in rdb.execute(
                "SELECT DISTINCT e.event_id, e.headline, e.verification_state FROM exposure_candidates x "
                "JOIN events e USING(event_id) WHERE x.company_id = ?", (cid,)):
                emit(r["rule_id"], f"event:{e['event_id']}",
                     f"{r['ticker']}: {e['headline']} ({e['verification_state']})", dict(e))
        elif r["kind"] == "liquidity_change" and r["ticker"]:
            st = universe.liquidity(rdb, r["ticker"], as_of=as_of).state
            last = pdb.execute("SELECT dedupe_key FROM alert_events WHERE rule_id = ? ORDER BY alert_id DESC "
                               "LIMIT 1", (r["rule_id"],))
            if not last or not last[0]["dedupe_key"].startswith(f"liq:{st}:"):
                emit(r["rule_id"], f"liq:{st}:{as_of}", f"{r['ticker']} liquidity state is now {st}",
                     {"state": st, "as_of": as_of})
        elif r["kind"] == "thesis_condition":
            for t in check_theses(pdb, rdb, owner_id, as_of=as_of):
                if t["state"] == "broken" and (r["ticker"] in (None, t["ticker"])):
                    emit(r["rule_id"], f"thesis:{t['thesis_id']}:{as_of}",
                         f"thesis '{t['title']}' ({t['ticker']}) has a broken condition", t)
    return new
