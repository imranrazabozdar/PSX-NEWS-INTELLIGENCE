"""PSX OHLCV collection (1m / 1h / 4h / 1d) from an owner-authorised chart data provider.

Provider: SCS (Standard Capital Securities) chart datafeed at https://chart.scstrade.com, a
TradingView-style "UDF" interface (/history?symbol=&resolution=&from=&to=). The owner authorised its use
on 2026-11-08 on the condition that requests are honest. This module therefore sends the project's own
identifying User-Agent (collectors.http.HttpClient), no spoofed browser headers and no Referer, and
respects robots.txt. If the provider refuses honest requests, collection fails visibly; it is never
worked around.

Rules:
* Only an ACTIVE source is collected for real (collectors.engine.authorise, the same gate as news).
  Dry runs fetch and validate without writing.
* Incremental: each (symbol, timeframe) resumes from its last stored bar, with a small overlap so the
  provider's correction of a recent bar is seen. The first run backfills a bounded window.
* Bars are append-only (migration 0010). A changed value is stored as a correction; nothing is
  overwritten. Invalid or misaligned bars are rejected and counted, never repaired or invented.
* The per-run database budget (database.connection) is respected. When it is reached, the run stops as
  'partial' and the next run resumes from what was stored.
* Timestamps: the provider's epoch seconds are UTC. session_date_pkt is the Pakistan (UTC+5) date;
  daily bars start at 00:00 UTC on the session date.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from collectors.engine import CollectionRefused, _kill_switch_on, authorise, load_source
from collectors.http import FetchError, HttpClient
from database.canonical import now_utc
from database.connection import Database, DatabaseBudgetError

SOURCE_ID = "scs_chart"
PKT = timedelta(hours=5)
# timeframe -> (provider resolution, bar seconds, first-run backfill days)
TIMEFRAMES: dict[str, tuple[str, int, int]] = {
    "1m": ("1", 60, 5),
    "1h": ("60", 3600, 90),
    "4h": ("240", 14400, 365),
    "1d": ("D", 86400, 5 * 365),
}
OVERLAP_BARS = 3
CHUNK = 200
DEFAULT_SYMBOLS = ("OGDC", "HBL", "LUCK", "ENGROH", "PSO")


@dataclass
class SeriesResult:
    symbol: str
    timeframe: str
    fetched: int = 0
    inserted: int = 0
    unchanged: int = 0
    corrected: int = 0
    rejected: int = 0
    first_bar_utc: str | None = None
    last_bar_utc: str | None = None
    error: str | None = None


@dataclass
class MarketRun:
    source_id: str
    dry_run: bool
    status: str = "running"
    run_id: int | None = None
    http_requests: int = 0
    series: list[SeriesResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "dry_run": self.dry_run,
            "status": self.status,
            "run_id": self.run_id,
            "http_requests": self.http_requests,
            "errors": self.errors,
            "series": [vars(s) for s in self.series],
        }


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _aligned(epoch: int, timeframe: str) -> bool:
    if timeframe == "1d":
        return epoch % 86400 == 0
    if timeframe in ("1h", "4h"):
        return epoch % 3600 == 0
    return epoch % 60 == 0


def parse_udf(payload: dict, timeframe: str) -> tuple[list[dict], int]:
    """UDF /history JSON -> (valid bars, rejected count). 'no_data' -> ([], 0). Never repairs a bar."""
    status = payload.get("s")
    if status == "no_data":
        return [], 0
    if status != "ok":
        raise ValueError(f"provider status {status!r}: {payload.get('errmsg', '')}"[:200])
    cols = [payload.get(k) for k in ("t", "o", "h", "l", "c", "v")]
    if not all(isinstance(x, list) for x in cols) or len({len(x) for x in cols}) != 1:
        raise ValueError("malformed UDF payload: missing or unequal arrays")
    bars, rejected = [], 0
    for t, o, h, lo, c, v in zip(*cols, strict=True):
        try:
            t, o, h, lo, c, v = int(t), float(o), float(h), float(lo), float(c), float(v)
        except (TypeError, ValueError):
            rejected += 1
            continue
        ok = (
            all(math.isfinite(x) for x in (o, h, lo, c, v))
            and lo > 0
            and v >= 0
            and h >= max(o, c, lo)
            and lo <= min(o, c)
            and _aligned(t, timeframe)
        )
        if not ok:
            rejected += 1
            continue
        start = datetime.fromtimestamp(t, UTC)
        bars.append(
            {
                "bar_start_utc": _iso(t),
                "session_date_pkt": (start + PKT).strftime("%Y-%m-%d"),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": v,
            }
        )
    bars.sort(key=lambda b: b["bar_start_utc"])
    dedup = {b["bar_start_utc"]: b for b in bars}  # provider duplicates: keep one
    rejected += len(bars) - len(dedup)
    return list(dedup.values()), rejected


def _last_bar(db: Database, source_id: str, symbol: str, timeframe: str) -> str | None:
    rows = db.execute(
        "SELECT MAX(bar_start_utc) AS m FROM market_bars WHERE source_id = ? AND symbol = ? "
        "AND timeframe = ?",
        (source_id, symbol, timeframe),
    )
    return rows[0]["m"] if rows else None


def _window(last: str | None, timeframe: str, now: datetime) -> tuple[int, int]:
    _, secs, backfill_days = TIMEFRAMES[timeframe]
    end = int(now.timestamp())
    if last is None:
        return end - backfill_days * 86400, end
    start = int(datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())
    return start - OVERLAP_BARS * secs, end


def fetch_series(client: HttpClient, base_url: str, symbol: str, timeframe: str, frm: int, to: int) -> dict:
    res = TIMEFRAMES[timeframe][0]
    url = f"{base_url.rstrip('/')}/history?symbol={symbol}&resolution={res}&from={frm}&to={to}"
    resp = client.get(url)
    try:
        return json.loads(resp.body)
    except ValueError as exc:
        raise ValueError(f"provider returned non-JSON for {symbol} {timeframe}") from exc


def _store(
    db: Database,
    source_id: str,
    symbol: str,
    timeframe: str,
    bars: list[dict],
    run_id: int | None,
    out: SeriesResult,
) -> None:
    if not bars:
        return
    existing = {
        r["bar_start_utc"]: r
        for r in db.execute(
            "SELECT bar_start_utc, open, high, low, close, volume FROM market_bars_current "
            "WHERE source_id = ? "
            "AND symbol = ? AND timeframe = ? AND bar_start_utc >= ?",
            (source_id, symbol, timeframe, bars[0]["bar_start_utc"]),
        )
    }
    now = now_utc()
    stmts = []
    for b in bars:
        cur = existing.get(b["bar_start_utc"])
        vals = (b["open"], b["high"], b["low"], b["close"], b["volume"])
        if cur is None:
            stmts.append(
                (
                    "INSERT INTO market_bars(source_id, symbol, timeframe, bar_start_utc, session_date_pkt, "
                    "open, high, low, close, volume, retrieved_at_utc, collection_run_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        source_id,
                        symbol,
                        timeframe,
                        b["bar_start_utc"],
                        b["session_date_pkt"],
                        *vals,
                        now,
                        run_id,
                    ),
                )
            )
            out.inserted += 1
        elif tuple(float(cur[k]) for k in ("open", "high", "low", "close", "volume")) != vals:
            stmts.append(
                (
                    "INSERT INTO market_bar_corrections(source_id, symbol, timeframe, bar_start_utc, open, "
                    "high, low, close, volume, retrieved_at_utc, collection_run_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (source_id, symbol, timeframe, b["bar_start_utc"], *vals, now, run_id),
                )
            )
            out.corrected += 1
        else:
            out.unchanged += 1
    for i in range(0, len(stmts), CHUNK):
        db.batch(stmts[i : i + CHUNK])


def collect_market(
    db: Database,
    *,
    symbols: list[str] | tuple[str, ...] = DEFAULT_SYMBOLS,
    timeframes: list[str] | tuple[str, ...] = tuple(TIMEFRAMES),
    source_id: str = SOURCE_ID,
    dry_run: bool = False,
    client: HttpClient | None = None,
    now: datetime | None = None,
    pause_seconds: float = 0.5,
) -> MarketRun:
    if _kill_switch_on():
        raise CollectionRefused("PSXNI_KILL_SWITCH is on: no collection")
    bad = [t for t in timeframes if t not in TIMEFRAMES]
    if bad:
        raise CollectionRefused(f"unsupported timeframe(s): {bad}")
    source = load_source(db, source_id)
    authorise(source, dry_run=dry_run)
    if not source.get("feed_url"):
        raise CollectionRefused(f"source '{source_id}' has no endpoint configured")
    client = client or HttpClient()
    now = now or datetime.now(UTC)
    run = MarketRun(source_id=source_id, dry_run=dry_run)
    if not dry_run:
        rows = db.batch(
            [
                (
                    "INSERT INTO collector_runs(job, source_id, started_at_utc, status) "
                    "VALUES ('market_ohlcv', ?, ?, 'running')",
                    (source_id, now_utc()),
                ),
                ("SELECT last_insert_rowid() AS id", ()),
            ]
        )
        run.run_id = rows[1][0]["id"]
    try:
        for symbol in symbols:
            for tf in timeframes:
                out = SeriesResult(symbol=symbol, timeframe=tf)
                run.series.append(out)
                try:
                    frm, to = _window(None if dry_run else _last_bar(db, source_id, symbol, tf), tf, now)
                    run.http_requests += 1
                    bars, out.rejected = parse_udf(
                        fetch_series(client, source["feed_url"], symbol, tf, frm, to), tf
                    )
                    out.fetched = len(bars)
                    if bars:
                        out.first_bar_utc, out.last_bar_utc = (
                            bars[0]["bar_start_utc"],
                            bars[-1]["bar_start_utc"],
                        )
                    if not dry_run:
                        _store(db, source_id, symbol, tf, bars, run.run_id, out)
                except DatabaseBudgetError:
                    raise
                except (FetchError, ValueError) as exc:
                    out.error = str(exc)[:300]
                    run.errors.append(f"{symbol} {tf}: {out.error}")
                if pause_seconds:
                    time.sleep(pause_seconds)
        failed = [s for s in run.series if s.error]
        run.status = (
            "dry_run"
            if dry_run
            else "failed"
            if len(failed) == len(run.series)
            else "partial"
            if failed
            else "succeeded"
        )
    except DatabaseBudgetError as exc:
        run.status = "partial"
        run.errors.append(f"database budget reached: {exc}")
    finally:
        if not dry_run and run.run_id is not None:
            if run.status == "running":
                run.status = "failed"
            fetched = sum(s.fetched for s in run.series)
            accepted = sum(s.inserted + s.corrected for s in run.series)
            rejected = sum(s.rejected for s in run.series)
            stmts = [
                (
                    "UPDATE collector_runs SET finished_at_utc = ?, status = ?, items_fetched = ?, "
                    "items_accepted = ?, items_rejected = ?, http_requests = ?, errors = ? WHERE run_id = ?",
                    (
                        now_utc(),
                        run.status,
                        fetched,
                        accepted,
                        rejected,
                        run.http_requests,
                        "\n".join(run.errors)[:2000] or None,
                        run.run_id,
                    ),
                )
            ]
            if run.status == "failed":
                stmts.append(
                    (
                        "UPDATE sources SET last_attempt_at_utc = ?, last_error = ?, failure_count = "
                        "failure_count + 1, consecutive_failures = consecutive_failures + 1 "
                        "WHERE source_id = ?",
                        (now_utc(), (run.errors or ["failed"])[-1][:500], source_id),
                    )
                )
            else:
                newest = max((s.last_bar_utc for s in run.series if s.last_bar_utc), default=None)
                stmts.append(
                    (
                        "UPDATE sources SET last_attempt_at_utc = ?, last_success_at_utc = ?, "
                        "last_error = ?, consecutive_failures = 0, "
                        "newest_item_at_utc = COALESCE(?, newest_item_at_utc) WHERE source_id = ?",
                        (
                            now_utc(),
                            now_utc(),
                            (run.errors[-1][:500] if run.errors else None),
                            newest,
                            source_id,
                        ),
                    )
                )
            try:
                db.batch(stmts)
            except DatabaseBudgetError:
                pass
    return run


def market_due(db: Database, source_id: str = SOURCE_ID, now: str | None = None) -> bool:
    """True when the ACTIVE market source's collection interval has elapsed."""
    rows = db.execute(
        """SELECT 1 FROM sources WHERE source_id = ? AND lifecycle_status = 'ACTIVE' AND enabled = 1
           AND (last_attempt_at_utc IS NULL OR strftime('%s', ?) - strftime('%s', last_attempt_at_utc)
                >= 60 * COALESCE(collection_frequency_minutes, 60))""",
        (source_id, now or now_utc()),
    )
    return bool(rows)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    from database.connection import connect

    ap = argparse.ArgumentParser(description="Collect PSX OHLCV bars (1m/1h/4h/1d)")
    ap.add_argument("--symbols", default=os.environ.get("PSXNI_MARKET_SYMBOLS", ",".join(DEFAULT_SYMBOLS)))
    ap.add_argument("--timeframes", default=",".join(TIMEFRAMES))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--due", action="store_true", help="only run if the source's interval has elapsed")
    args = ap.parse_args(argv)
    db = connect()
    if args.due and not market_due(db):
        print(json.dumps({"skipped": "market source not ACTIVE or not due"}))
        return 0
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    try:
        run = collect_market(
            db,
            symbols=symbols,
            timeframes=[t.strip() for t in args.timeframes.split(",")],
            dry_run=args.dry_run,
        )
    except CollectionRefused as exc:
        print(json.dumps({"refused": str(exc)}))
        return 2
    print(json.dumps(run.as_dict(), indent=1))
    return 1 if run.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
