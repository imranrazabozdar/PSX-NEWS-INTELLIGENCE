"""Turn the technical engine's rows (read through the ADR-0008 link) into dated facts. No model, no network.

* Price moves are computed from stored daily bars and labelled `fact`.
* Wyckoff and chart-pattern outputs are the technical engine's heuristic scores, labelled `analyst_view`, and
  always carry the engine's own scan date. They are scores, never probabilities, and never an instruction:
  action words (buy, sell, wait, short, long) are never stored.
* Missing values stay unknown: a row that lacks what a fact needs produces no fact.
"""

from __future__ import annotations

import re
from typing import Any

PRICE_SOURCE = "Technical engine daily bars (read-only link; SCS chart feed)"
SIGNAL_SOURCE = "Technical engine scans (read-only link)"
MOVE_PCT = 5.0  # a day's close-to-close move at or beyond this is notable
VOLUME_X = 3.0  # volume at or beyond this multiple of the previous 20-session average is notable
_ACTION = re.compile(r"\b(buy|sell|wait|short|long|entry|target|stop)\b", re.I)


def clean_label(text: Any) -> str:
    """A signal or pattern name, with anything that reads as an instruction replaced."""
    raw = str(text or "").strip().replace("_", " ").lower()
    if not raw:
        return "unlabelled"
    return "unlabelled" if _ACTION.search(raw) else raw


def valid_bar(b: dict[str, Any]) -> bool:
    try:
        o, h, lo, c, v = (float(b[k]) for k in ("open", "high", "low", "close", "volume"))
    except (KeyError, TypeError, ValueError):
        return False
    ok = lo > 0 and h >= lo and h >= o and h >= c and lo <= o and lo <= c and v >= 0
    return ok and bool(b.get("trade_date"))


def price_move_facts(symbol: str, bars: list[dict[str, Any]], since: str, stamp: str) -> list[dict[str, Any]]:
    """Notable days (big move or heavy volume) on or after `since`, from bars sorted by date."""
    bars = sorted((b for b in bars if valid_bar(b)), key=lambda b: b["trade_date"])
    out: list[dict[str, Any]] = []
    for i in range(20, len(bars)):
        b, prev = bars[i], bars[i - 1]
        if b["trade_date"] < since:
            continue
        move = (float(b["close"]) / float(prev["close"]) - 1) * 100
        base = sum(float(x["volume"]) for x in bars[i - 20 : i]) / 20
        ratio = float(b["volume"]) / base if base > 0 else None
        if abs(move) < MOVE_PCT and not (ratio is not None and ratio >= VOLUME_X):
            continue
        direction = "up" if move > 0 else "down" if move < 0 else "unchanged"
        text = (f"{symbol} closed at {float(b['close']):g} on {b['trade_date']}, "
                f"{direction} {abs(move):.1f}% on the day")
        if ratio is not None:
            text += f"; volume {ratio:.1f}x its previous 20-session average"
        out.append({
            "company": symbol, "topic": "price.move", "fact_text": text[:300], "value": round(move, 2),
            "unit": "% close-to-close", "period": b["trade_date"], "source_name": PRICE_SOURCE,
            "source_url": None, "source_date": b["trade_date"], "as_of": b["trade_date"],
            "confidence": "fact", "created_at": stamp,
        })
    return out


def wyckoff_fact(row: dict[str, Any], stamp: str) -> dict[str, Any] | None:
    sym, day, score = row.get("symbol"), row.get("scan_date"), row.get("accumulation_score")
    label = clean_label(row.get("signal_type"))
    if not sym or not day or score is None or str(row.get("signal_type") or "").upper() == "NO_SIGNAL":
        return None
    text = (f"{sym} Wyckoff accumulation scan on {day}: score {int(score)}/100, class {label} "
            "(engine heuristic, not a probability)")
    return {"company": sym, "topic": "technical.wyckoff", "fact_text": text[:300], "value": float(score),
            "unit": "score 0-100", "period": str(day), "source_name": SIGNAL_SOURCE, "source_url": None,
            "source_date": str(day), "as_of": str(day), "confidence": "analyst_view", "created_at": stamp}


def pattern_fact(row: dict[str, Any], stamp: str) -> dict[str, Any] | None:
    sym, day, conf = row.get("symbol"), row.get("signal_date"), row.get("confidence_score")
    if not sym or not day or conf is None:
        return None
    label = clean_label(row.get("pattern_type"))
    text = (f"{sym} chart pattern '{label}' detected on {day}, pattern confidence {float(conf):.2f} "
            "(technical engine heuristic, not a probability)")
    return {"company": sym, "topic": "technical.pattern", "fact_text": text[:300], "value": float(conf),
            "unit": "pattern confidence 0-1", "period": str(day), "source_name": SIGNAL_SOURCE,
            "source_url": None, "source_date": str(day), "as_of": str(day), "confidence": "analyst_view",
            "created_at": stamp}
