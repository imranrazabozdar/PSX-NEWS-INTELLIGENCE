"""Sync from the technical engine (ADR-0008 read-only link) into psx-library.

* price_daily: the last --days sessions of daily bars, only rows that are new or changed are written.
* a facts capsule (JSON) of notable price moves, Wyckoff scans with a real signal, and chart patterns; load it
  with `python -m scripts.absorb_sector_capsule <capsule> --apply --since-days 200`.
Default is a dry run (nothing written). `--apply` writes price_daily only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engines import library_db
from engines import technical_facts as tf
from engines import technical_link as tl

UPSERT = ("INSERT INTO price_daily (symbol, trade_date, open, high, low, close, volume, source, updated_utc) "
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(symbol, trade_date) "
          "DO UPDATE SET open = excluded.open, "
          "high = excluded.high, low = excluded.low, close = excluded.close, volume = excluded.volume, "
          "source = excluded.source, updated_utc = excluded.updated_utc")
KEY = ("open", "high", "low", "close", "volume")


def _in(symbols: list[str]) -> tuple[str, tuple]:
    return ",".join("?" for _ in symbols), tuple(symbols)


def read_bars(link: tl.TechnicalLink, since: str, symbols: list[str]) -> list[dict]:
    where, params = "trade_date >= ?", (since,)
    if symbols:
        ph, ps = _in(symbols)
        where += f" AND symbol IN ({ph})"
        params += ps
    rows = link.select_from(
        "daily_ohlc",
        f"SELECT symbol, trade_date, open, high, low, close, volume, source FROM daily_ohlc "  # noqa: S608
        f"WHERE {where} ORDER BY symbol, trade_date", params)
    return [dict(r) for r in rows]


def read_signals(link: tl.TechnicalLink, since: str, symbols: list[str]) -> tuple[list[dict], list[dict]]:
    ex, ps = "", ()
    if symbols:
        ph, ps = _in(symbols)
        ex = f" AND symbol IN ({ph})"
    wy = link.select_from(
        "wyckoff_accumulation",
        "SELECT symbol, scan_date, accumulation_score, signal_type FROM wyckoff_accumulation "  # noqa: S608
        f"WHERE scan_date >= ? AND signal_type <> 'NO_SIGNAL'{ex}", (since, *ps))
    pat = link.select_from(
        "chart_patterns",
        "SELECT symbol, pattern_type, signal_date, confidence_score FROM chart_patterns "  # noqa: S608
        f"WHERE signal_date >= ?{ex}", (since, *ps))
    return [dict(r) for r in wy], [dict(r) for r in pat]


def changed_bars(db, bars: list[dict]) -> list[dict]:
    """Bars that are new or differ from price_daily (one indexed range read of the window)."""
    if not bars:
        return []
    first = min(b["trade_date"] for b in bars)
    rows = db.execute("SELECT symbol, trade_date, open, high, low, close, volume FROM price_daily "
                      "WHERE trade_date >= ?", (first,))
    stored = {(r["symbol"], r["trade_date"]): tuple(float(r[k]) for k in KEY) for r in rows}
    return [b for b in bars
            if stored.get((b["symbol"], b["trade_date"])) != tuple(float(b[k]) for k in KEY)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--symbols", default="", help="comma-separated symbols (default: every symbol)")
    ap.add_argument("--days", type=int, default=120)
    ap.add_argument("--out", type=Path, required=True, help="facts capsule (JSON)")
    ap.add_argument("--apply", action="store_true", help="write price_daily (default: dry run)")
    args = ap.parse_args(argv)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    today = datetime.now(UTC).date()
    window_start = (today - timedelta(days=int(args.days * 1.5))).isoformat()
    # 20 sessions of lead-in before the window so the first day's averages exist
    fetch_start = (today - timedelta(days=int(args.days * 1.5) + 40)).isoformat()
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        link = tl.connect(row_cap=400_000)
    except tl.LinkError as exc:
        print(f"refused: {exc}")
        return 1
    bars = [b for b in read_bars(link, fetch_start, symbols) if tf.valid_bar(b)]
    wy, pat = read_signals(link, window_start, symbols)
    by_symbol: dict[str, list[dict]] = {}
    for b in bars:
        by_symbol.setdefault(b["symbol"], []).append(b)
    facts: list[dict] = []
    for sym, rows in by_symbol.items():
        facts += tf.price_move_facts(sym, rows, window_start, stamp)
    facts += [f for f in (tf.wyckoff_fact(r, stamp) for r in wy) if f]
    facts += [f for f in (tf.pattern_fact(r, stamp) for r in pat) if f]
    window = [b for b in bars if b["trade_date"] >= window_start]
    print(f"technical host: {link.host}; symbols: {len(by_symbol)}; bars read: {len(bars)}; "
          f"bars in window: {len(window)}; facts: {len(facts)}")
    for topic in ("price.move", "technical.wyckoff", "technical.pattern"):
        print(f"  {topic}: {sum(1 for f in facts if f['topic'] == topic)}")
    for f in facts[:5]:
        print("  sample:", f["fact_text"])
    args.out.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")

    db = library_db.get_library_connection().db
    known = {r["company"] for r in db.execute("SELECT DISTINCT company FROM research_fact")}
    unknown = sorted(set(by_symbol) - known)
    print(f"symbols with no entity in the library yet: {len(unknown)} {unknown[:20]}")
    try:
        todo = changed_bars(db, window)
    except Exception as exc:  # noqa: BLE001 - table missing: say so plainly
        print(f"price_daily not readable ({exc}); apply migration 0012 first")
        return 0 if not args.apply else 1
    print(f"price_daily: {len(todo)} new or changed bars of {len(window)}")
    if args.apply:
        for i in range(0, len(todo), 200):
            db.batch([(UPSERT, (b["symbol"], b["trade_date"], b["open"], b["high"], b["low"], b["close"],
                                b["volume"], tf.PRICE_SOURCE, stamp)) for b in todo[i : i + 200]],
                     transactional=True)
        print(f"price_daily: wrote {len(todo)} bars; library usage {db.usage()}")
    else:
        print("dry run: nothing written to the library")
    print(f"technical usage: {link.db.usage()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
