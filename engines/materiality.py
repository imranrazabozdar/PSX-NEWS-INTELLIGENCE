"""Materiality scoring and the company radar. Deterministic, no model, no prices predicted.

A score (0-100) orders ATTENTION: how much recent, sourced evidence there is about a company that could
matter to its stock. It is not a forecast and not a recommendation. Every point comes from a named driver
with a date and a source, and anything that cannot be known is listed under `unknown` instead of being
guessed or counted as zero.

Drivers and their caps (the sum is capped at 100):
  results      35  a results/earnings fact in the window, +up to 25 for a like-for-like EPS change
  corporate    20  dividend, bonus, rights, book closure in the window
  price        40  a close-to-close move (and volume vs its previous 20-session average) in the window
  news         15  a news-volume signal against the company's own baseline (news_rollup)
  technical    10  the technical engine's heuristic scores (labelled as heuristics; never a direction call)
"""

from __future__ import annotations

import re
from typing import Any

CAPS = {"results": 60, "corporate": 20, "price": 40, "news": 15, "technical": 10}
RESULT_TOPICS = ("results.", "news.results", "announcements.Financial Result")
CORPORATE_TOPICS = ("corporate_action.", "news.dividend")
EPS_UNITS = {"PKR_per_share", "PKR", "PKR/share"}
_PERIOD_9M = re.compile(r"^(\d)M (\d{4})$")
_PERIOD_ENDED = re.compile(r"^(.*?)\s+ended (\d{4})-(\d{2})-(\d{2})$")
_PERIOD_Q = re.compile(r"^(\d{4}) (\d)Q$|^(\d)Q (\d{4})$")
CONFLICT_TOLERANCE = 0.10  # sources disagreeing by more than this make the comparison unknown


def _ended_kind(label: str, month: str, day: str) -> str:
    """'nine months ended 2026-09-30' -> '9M@09-30': the same period of another year has the same kind."""
    text = label.lower()
    if "quarter" in text:
        name = "Q"
    elif "nine" in text:
        name = "9M"
    elif "half" in text:
        name = "H"
    elif "year" in text:
        name = "FY"
    else:
        name = text.strip().replace(" ", "_")
    return f"{name}@{month}-{day}"


def _end_md(kind: str) -> str:
    """MM-DD the period ends on, so the most recent period of the latest year is compared first."""
    base = kind.split("|", 1)[0]
    if "@" in base:
        return base.split("@", 1)[1]
    if base.endswith("M") and base[:-1].isdigit():
        return f"{int(base[:-1]):02d}-30"
    if base.endswith("Q") and base[:-1].isdigit():
        return f"{int(base[:-1]) * 3:02d}-30"
    return "00-00"


def basis_of(text: Any) -> str:
    """consolidated / unconsolidated, as stated in the fact; EPS must only be compared on the same basis."""
    low = str(text or "").lower()
    return "unconsolidated" if "unconsolidated" in low else "consolidated" if "consolidated" in low else ""


def parse_period(period: Any) -> tuple[str, int] | None:
    """('9M', 2026) or ('3Q', 2026) from the stored period strings; anything else is not comparable."""
    text = str(period or "").strip()
    if m := _PERIOD_ENDED.match(text):
        return _ended_kind(m.group(1), m.group(3), m.group(4)), int(m.group(2))
    if m := _PERIOD_9M.match(text):
        return f"{m.group(1)}M", int(m.group(2))
    if m := _PERIOD_Q.match(text):
        year, quarter = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        return f"{quarter}Q", int(year)
    return None


def eps_history(facts: list[dict[str, Any]]) -> dict[tuple[str, int], float | None]:
    """EPS by (period kind, year). None marks a key whose sources disagree: unknown, never averaged."""
    seen: dict[tuple[str, int], list[float]] = {}
    for f in facts:
        key = parse_period(f.get("period"))
        if key is None or f.get("value") is None or f.get("unit") not in EPS_UNITS:
            continue
        if "eps" not in str(f.get("fact_text", "")).lower():
            continue
        if basis := basis_of(f.get("fact_text")):
            key = (f"{key[0]}|{basis}", key[1])
        seen.setdefault(key, []).append(float(f["value"]))
    out: dict[tuple[str, int], float | None] = {}
    for key, vals in seen.items():
        lo, hi = min(vals), max(vals)
        agree = abs(hi - lo) <= CONFLICT_TOLERANCE * max(abs(hi), abs(lo), 1e-9)
        out[key] = vals[-1] if agree else None
    return out


def eps_change(hist: dict[tuple[str, int], float | None]) -> tuple[dict[str, Any] | None, str | None]:
    """Like-for-like change for the latest year that has the previous year too: (result, why unknown)."""
    years = sorted({(k, y) for (k, y) in hist}, key=lambda t: (t[1], _end_md(t[0])), reverse=True)
    for kind, year in years:
        cur, prev = hist.get((kind, year)), hist.get((kind, year - 1))
        if cur is None or prev is None:
            continue
        shown = kind.replace("|", " ").replace("@", " ")
        label = f"{shown} {year} vs {year - 1}"
        if prev > 0 and cur >= 0:
            return {"label": label, "cur": cur, "prev": prev, "pct": (cur / prev - 1) * 100}, None
        if prev > 0 > cur or prev < 0 <= cur:
            return {"label": label, "cur": cur, "prev": prev, "pct": None, "swing": True}, None
        return None, f"{label}: base is not positive"
    return None, "no like-for-like EPS pair on file"


def _driver(kind: str, points: float, text: str, day: str, source: str) -> dict[str, Any]:
    return {"kind": kind, "points": round(points, 1), "text": text, "date": day, "source": source}


def price_driver(move_pct: float | None, volume_x: float | None, day: str) -> dict[str, Any] | None:
    if move_pct is None:
        return None
    pts = min(30.0, abs(move_pct) * 3) + (min(10.0, (volume_x - 1) * 2) if volume_x and volume_x > 1 else 0.0)
    if pts < 6:
        return None
    text = f"closed {'up' if move_pct > 0 else 'down'} {abs(move_pct):.1f}% on {day}"
    if volume_x:
        text += f"; volume {volume_x:.1f}x its previous 20-session average"
    return _driver("price", pts, text, day, "price_daily")


def score_company(
    symbol: str,
    *,
    window_facts: list[dict[str, Any]],
    history_facts: list[dict[str, Any]],
    price: dict[str, Any] | None,
    news_signal: dict[str, Any] | None,
    has_prices: bool,
) -> dict[str, Any]:
    drivers: list[dict[str, Any]] = []
    unknown: list[str] = []
    results = [f for f in window_facts if str(f["topic"]).startswith(RESULT_TOPICS)]
    if results:
        top = max(results, key=lambda f: f["source_date"])
        drivers.append(_driver("results", 35, top["fact_text"][:200], top["source_date"], top["source_name"]))
        change, why = eps_change(eps_history(history_facts))
        if change and change.get("pct") is not None:
            drivers.append(
                _driver(
                    "results",
                    min(25.0, abs(change["pct"]) / 2),
                    f"EPS {change['label']}: {change['prev']:g} -> {change['cur']:g} ({change['pct']:+.0f}%)",
                    top["source_date"],
                    "stored EPS facts",
                )
            )
        elif change:
            drivers.append(
                _driver(
                    "results",
                    15,
                    f"EPS changed sign, {change['label']}: {change['prev']:g} -> {change['cur']:g}",
                    top["source_date"],
                    "stored EPS facts",
                )
            )
        else:
            unknown.append(f"results size unknown: {why}")
    corp = [f for f in window_facts if str(f["topic"]).startswith(CORPORATE_TOPICS)]
    if corp:
        top = max(corp, key=lambda f: f["source_date"])
        drivers.append(
            _driver("corporate", 20, top["fact_text"][:200], top["source_date"], top["source_name"])
        )
    if price:
        d = price_driver(price.get("move"), price.get("volume_x"), price["day"])
        if d:
            drivers.append(d)
    elif not has_prices:
        unknown.append("no price series for this symbol")
    if news_signal:
        drivers.append(
            _driver(
                "news",
                15,
                news_signal["fact_text"][:200],
                news_signal["source_date"],
                news_signal.get("source_name", "news rollup"),
            )
        )
    tech = [f for f in window_facts if str(f["topic"]).startswith("technical.")]
    if tech:
        top = max(tech, key=lambda f: f["source_date"])
        strong = (top["topic"] == "technical.wyckoff" and (top.get("value") or 0) >= 70) or (
            top["topic"] == "technical.pattern" and (top.get("value") or 0) >= 0.8
        )
        drivers.append(
            _driver(
                "technical",
                10 if strong else 4,
                top["fact_text"][:200],
                top["source_date"],
                top["source_name"],
            )
        )
    total = 0.0
    for kind, cap in CAPS.items():
        total += min(cap, sum(d["points"] for d in drivers if d["kind"] == kind))
    return {"symbol": symbol, "score": round(min(100.0, total), 1), "drivers": drivers, "unknown": unknown}


def rank(scored: list[dict[str, Any]], top: int = 25) -> list[dict[str, Any]]:
    live = [s for s in scored if s["drivers"]]
    return sorted(live, key=lambda s: (-s["score"], s["symbol"]))[:top]


def render_markdown(ranked: list[dict[str, Any]], day: str, universe: int, with_price: int) -> str:
    lines = [
        f"# Company radar for {day}",
        "",
        "Scores order attention only: recent, sourced evidence that could matter. They are not forecasts, "
        "not "
        "probabilities and not recommendations.",
        "",
        f"{len(ranked)} companies shown of {universe} checked; {with_price} have a price series.",
        "",
    ]
    for i, s in enumerate(ranked, 1):
        lines.append(f"## {i}. {s['symbol']} (score {s['score']})")
        for d in s["drivers"]:
            lines.append(f"- [{d['kind']}] {d['text']} ({d['date']}; {d['source']})")
        for u in s["unknown"]:
            lines.append(f"- unknown: {u}")
        lines.append("")
    return "\n".join(lines)
