# ruff: noqa: E501, E731
"""Did the technical setups score predict anything? A walk-forward check on the stored daily bars. No model.

For each past trading day D, every eligible stock is scored with ONLY the bars up to D (the same price items
the live score uses: 20-session change, position in the recent range, volume against usual), then compared with
what it did over the next h sessions. Reported per horizon: the average excess return of the top 10 over the
whole eligible group, how often the top 10 beat the group, and the rank correlation (IC) of the score, and of
each item, with the forward return.

Honest limits, repeated in the report: about a hundred sessions in one market regime; forward windows overlap,
so days are not independent and the numbers are indicative, not proof; only price items are tested (the
fundamental ratios on file are today's values, so testing them on the past would leak the future); no costs,
no slippage, closes only; the technical engine's own scores were not stored for the past.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Any

from engines import setups

HORIZONS = (1, 5, 10)
LOOKBACK = 38  # sessions the live score sees (about eight weeks of closes)
MIN_STOCKS = 20


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) != len(b) or len(a) < 5:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return None if den == 0 else num / den


def _eligible(window: list[dict[str, Any]], min_turnover: float) -> bool:
    if len(window) < setups.MIN_SESSIONS:
        return False
    turnover = statistics.fmean(float(x["close"]) * float(x["volume"]) for x in window[-20:])
    return turnover >= min_turnover and float(window[-1]["close"]) >= setups.MIN_PRICE


def run(
    bars: dict[str, list[dict[str, Any]]],
    horizons: tuple[int, ...] = HORIZONS,
    top: int = 10,
    *,
    min_turnover: float = setups.MIN_TURNOVER,
    volume_weight: float = 1.0,
    days_filter: Any = None,
) -> dict[str, Any]:
    series = {s: sorted(b, key=lambda r: r["trade_date"]) for s, b in bars.items()}
    days = sorted({r["trade_date"] for b in series.values() for r in b})
    index = {s: {r["trade_date"]: i for i, r in enumerate(b)} for s, b in series.items()}
    per_h: dict[int, dict[str, list[Any]]] = {
        h: {"excess": [], "beat": [], "ic": [], "top": [], "group": [], "days": []} for h in horizons
    }
    item_ic: dict[int, dict[str, list[float]]] = {h: {k: [] for k, _m in setups.TECH_ITEMS} for h in horizons}
    for day in days:
        if days_filter is not None and not days_filter(day):
            continue
        rows = []
        for s, b in series.items():
            i = index[s].get(day)
            if i is None or i + 1 < setups.MIN_SESSIONS:
                continue
            window = b[max(0, i + 1 - LOOKBACK) : i + 1]
            if not _eligible(window, min_turnover):
                continue
            pts, _ = setups.technical_items(window, [], date.fromisoformat(day))
            if pts.get("volume") is not None:
                pts["volume"] = pts["volume"] * volume_weight
            score = setups.pillar(pts, setups.TECH_ITEMS, setups.MIN_TECH_POINTS)
            if score is None:
                continue
            rows.append((s, i, score, pts))
        if len(rows) < MIN_STOCKS:
            continue
        for h in horizons:
            fw = []
            for s, i, score, pts in rows:
                b = series[s]
                if i + h < len(b) and float(b[i]["close"]) > 0:
                    fw.append((s, score, pts, (float(b[i + h]["close"]) / float(b[i]["close"]) - 1) * 100))
            if len(fw) < MIN_STOCKS:
                continue
            allmean = statistics.fmean(r[3] for r in fw)
            best = sorted(fw, key=lambda r: -r[1])[:top]
            bestmean = statistics.fmean(r[3] for r in best)
            per_h[h]["excess"].append(bestmean - allmean)
            per_h[h]["top"].append(bestmean)
            per_h[h]["group"].append(allmean)
            per_h[h]["days"].append(day)
            per_h[h]["beat"].append(1.0 if bestmean > allmean else 0.0)
            ic = spearman([r[1] for r in fw], [r[3] for r in fw])
            if ic is not None:
                per_h[h]["ic"].append(ic)
            for k, _m in setups.TECH_ITEMS:
                sub = [(r[2][k], r[3]) for r in fw if r[2].get(k) is not None]
                v = spearman([x for x, _ in sub], [y for _, y in sub]) if len(sub) >= MIN_STOCKS else None
                if v is not None:
                    item_ic[h][k].append(v)
    return {"horizons": per_h, "item_ic": item_ic, "days_scored": len(days)}


def _mean_t(xs: list[float]) -> tuple[float | None, float | None]:
    if len(xs) < 3:
        return None, None
    m = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    return m, (m / (sd / len(xs) ** 0.5) if sd > 0 else None)


def report(result: dict[str, Any]) -> str:
    lines = [
        "# Technical setups: did the score predict anything? (walk-forward on stored daily bars)",
        "",
        "Indicative only: about a hundred sessions in one market regime; overlapping forward windows (days are "
        "not independent, so a t-statistic overstates certainty); closes only, no costs; price items only "
        "(the fundamental ratios on file are today's values, so they cannot be tested on the past).",
        "",
        "| horizon | days tested | top-10 excess return (avg) | top-10 beat the group | rank correlation (IC) | IC t-stat |",
        "|---|---|---|---|---|---|",
    ]
    for h, d in result["horizons"].items():
        ex, ext = _mean_t(d["excess"])
        ic, ict = _mean_t(d["ic"])
        beat = statistics.fmean(d["beat"]) * 100 if d["beat"] else None
        f = lambda x, p=2: "n/a" if x is None else f"{x:.{p}f}"  # noqa: E731
        lines.append(
            f"| {h} session(s) | {len(d['excess'])} | {f(ex)}% (t {f(ext, 1)}) | "
            f"{'n/a' if beat is None else f'{beat:.0f}%'} | {f(ic, 3)} | {f(ict, 1)} |"
        )
    lines += ["", "Per item, average rank correlation with the forward return:", ""]
    lines.append("| item | " + " | ".join(f"{h}s" for h in result["item_ic"]) + " |")
    lines.append("|---|" + "---|" * len(result["item_ic"]))
    for k, _m in setups.TECH_ITEMS:
        cells = []
        for h in result["item_ic"]:
            m, _t = _mean_t(result["item_ic"][h][k])
            cells.append("n/a" if m is None else f"{m:+.3f}")
        lines.append(f"| {setups.LABELS[k]} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "How to read it: an IC near zero means no predictive rank order; positive means higher scores were "
        "followed by higher returns, negative the reverse (a reversal pattern). Top-10 excess return is in "
        "percentage points over the whole eligible group on the same days. These are the tests of the "
        "equal-weight scoring; no weights were fitted.",
    ]
    return "\n".join(lines) + "\n"


def summarise(result: dict[str, Any], h: int) -> dict[str, Any]:
    """One horizon: average excess, beat rate, the market's own drift, and an overlap-aware t-stat from days
    sampled h sessions apart (so the forward windows do not overlap)."""
    d = result["horizons"][h]
    ex = d["excess"]
    sampled = ex[::h]
    m, t_all = _mean_t(ex)
    _m2, t_sep = _mean_t(sampled)
    return {
        "days": len(ex),
        "excess": m,
        "beat": (statistics.fmean(d["beat"]) * 100 if d["beat"] else None),
        "top": statistics.fmean(d["top"]) if d["top"] else None,
        "group": statistics.fmean(d["group"]) if d["group"] else None,
        "t_overlapping": t_all,
        "t_separate": t_sep,
        "separate_days": len(sampled),
    }


def robustness_report(bars: dict[str, list[dict[str, Any]]], horizons: tuple[int, ...] = (5, 10)) -> str:
    sessions = sorted({r["trade_date"] for b in bars.values() for r in b})
    mid = sessions[len(sessions) // 2]
    variants = (
        ("all days (baseline)", {}),
        (f"first half (to {mid})", {"days_filter": lambda d: d <= mid}),
        (f"second half (after {mid})", {"days_filter": lambda d: d > mid}),
        ("liquidity floor Rs 100m a day", {"min_turnover": 100e6}),
        ("volume item at half weight", {"volume_weight": 0.5}),
        ("volume item removed", {"volume_weight": 0.0}),
    )
    f = lambda x, p=2: "n/a" if x is None else f"{x:.{p}f}"  # noqa: E731
    lines = [
        "# Robustness of the technical setups score (walk-forward, stored daily bars)",
        "",
        "Same limits as the first report: one regime, about a hundred sessions, closes only, no costs. "
        "'t (separate)' uses days h sessions apart so the forward windows do not overlap; it is the number "
        "to trust, not the overlapping one. 'market' is the average forward return of the whole eligible group.",
        "",
        "| variant | h | days | top-10 avg return | market avg return | excess | beat | t (overlapping) | t (separate, n) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for name, kw in variants:
        res = run(bars, horizons, **kw)
        for h in horizons:
            r = summarise(res, h)
            beat = "n/a" if r["beat"] is None else f"{r['beat']:.0f}%"
            lines.append(
                f"| {name} | {h} | {r['days']} | {f(r['top'])}% | {f(r['group'])}% | {f(r['excess'])}pp | {beat} "
                f"| {f(r['t_overlapping'], 1)} | {f(r['t_separate'], 1)} ({r['separate_days']}) |"
            )
    lines += [
        "",
        "Read: a result that holds in both halves, with a separate-window t above about 2, is a candidate "
        "for a weight; one that holds in only one half is regime luck. Nothing was fitted here.",
    ]
    return "\n".join(lines) + "\n"
