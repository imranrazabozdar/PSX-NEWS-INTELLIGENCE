"""Materiality scoring and the company radar. Deterministic, no model, no prices predicted.

A score (0-100) orders ATTENTION: how much recent, sourced evidence there is about a company that could
matter to its stock. It is not a forecast and not a recommendation. Every point comes from a named driver
with a date and a source, and anything that cannot be known is listed under `unknown` instead of being
guessed or counted as zero.

Drivers and their caps (the sum is capped at 100):
  results      35  a results/earnings fact in the window, +up to 25 for a like-for-like EPS change
  corporate    20  dividend, bonus, rights, book closure in the window
  announcement 15  a material company announcement in the window (5 if only routine scheduled notices)
  price        40  a close-to-close move (and volume vs its previous 20-session average) in the window
  news         15  a news-volume signal against the company's own baseline (news_rollup)
  technical    10  the technical engine's heuristic scores (labelled as heuristics; never a direction call)
"""

from __future__ import annotations

import calendar
import re
from collections import Counter
from typing import Any

CAPS = {"results": 60, "corporate": 20, "announcement": 15, "price": 40, "news": 15, "technical": 10}
# Investify announcement labels (announcements.<label>). Material ones are company-specific disclosures;
# scheduled ones are routine notices that say a date is coming, not why a price moved. Everything else
# (report transmission, briefings, auditor certificates, insider lines, "Other") is left out of scores.
MATERIAL_LABELS = {
    "Material Disclosure",
    "Management Change",
    "Financing / Restructuring",
    "M&A / Public Offer",
    "Legal / Regulatory",
    "Capacity / Shutdown",
    "Operations Update",
    "Unusual Movement Reply",
    "Share Buyback",
    "Share Split",
    "Credit Rating",
    "Scheme / Arrangement",
    "Rights / Bonus",
    "Corporate Action",
}
SCHEDULED_LABELS = {"Board Meeting", "AGM / EGM", "Book Closure", "Dividend", "Meetings"}

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


def eps_change(
    hist: dict[tuple[str, int], float | None], notes: dict[tuple[str, int], str] | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """Like-for-like change for the latest year that has the previous year too: (result, why unknown)."""
    years = sorted({(k, y) for (k, y) in hist}, key=lambda t: (t[1], _end_md(t[0])), reverse=True)
    for kind, year in years:
        cur, prev = hist.get((kind, year)), hist.get((kind, year - 1))
        if cur is None or prev is None:
            continue
        shown = kind.replace("|", " ").replace("@", " ")
        label = f"{shown} {year} vs {year - 1}"
        if notes and notes.get((kind, year)):
            label += f" (latest figure from {notes[(kind, year)]}, basis matched)"
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
        change, why = eps_pair(history_facts)
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
    ann = [f for f in window_facts if str(f["topic"]).startswith("announcements.")]
    material = [f for f in ann if str(f["topic"])[len("announcements.") :] in MATERIAL_LABELS]
    scheduled = [f for f in ann if str(f["topic"])[len("announcements.") :] in SCHEDULED_LABELS]
    if material:
        top = max(material, key=lambda f: f["source_date"])
        more = f"{len(material)} material announcements; latest: " if len(material) > 1 else ""
        drivers.append(
            _driver("announcement", 15, more + top["fact_text"][:180], top["source_date"], top["source_name"])
        )
    elif scheduled:
        top = max(scheduled, key=lambda f: f["source_date"])
        drivers.append(
            _driver(
                "announcement",
                5,
                "routine notice: " + top["fact_text"][:180],
                top["source_date"],
                top["source_name"],
            )
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


# --- pairing Investify's newest EPS with the PSX history, only when like-for-like can be shown --------

INVESTIFY_EPS = {
    "fundamentals.latest_quarter_eps": "quarter",
    "fundamentals.year_to_date_eps": "ytd",
    "fundamentals.annual_eps": "annual",
}
_FUND_PERIOD = re.compile(r"^(?:UPTO )?(\d{4}) (?:(\d)Q|FY)$")
IMPLAUSIBLE_RATIO = 4.0  # an Investify figure above this multiple of last year's is not used
AGREE_TOLERANCE = 0.02  # an overlapping period must match within 2% for the source to count as validated


def _is_investify(f: dict[str, Any]) -> bool:
    return str(f.get("source_name", "")).startswith("Investify") and f.get("topic") in INVESTIFY_EPS


def investify_key(topic: str, period: str, fye: tuple[int, int]) -> tuple[str, int] | None:
    """Investify's '2026 3Q', 'UPTO 2026 3Q' or '2025 FY' as PSX-style (kind, calendar year of period end).

    The label's year is the fiscal year; the quarter ends 3n months after the previous fiscal year end."""
    m = _FUND_PERIOD.match(str(period or "").strip())
    kind = INVESTIFY_EPS.get(topic)
    if not m or not kind:
        return None
    fy, n = int(m.group(1)), int(m.group(2) or 4)
    month, day = fye
    total = (fy - 1) * 12 + (month - 1) + 3 * n
    year, end_month = total // 12, total % 12 + 1
    end_day = day if n == 4 else calendar.monthrange(year, end_month)[1]
    if kind == "quarter" and n == 4:
        return None  # a fourth quarter is the year less nine months: not a reported figure to compare
    base = {"quarter": "Q", "annual": "FY"}.get(kind) or {1: "Q", 2: "H", 3: "9M", 4: "FY"}[n]
    if kind == "annual" and n != 4:
        return None
    return f"{base}@{end_month:02d}-{end_day:02d}", year


def _fiscal_year_end(hist: dict[tuple[str, int], float | None]) -> tuple[int, int] | None:
    ends = Counter(k.split("|", 1)[0].split("@", 1)[1] for (k, _y) in hist if k.startswith("FY@"))
    if not ends:
        return None
    month, day = ends.most_common(1)[0][0].split("-")
    return int(month), int(day)


def eps_pair(facts: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str | None]:
    """Like-for-like EPS change from every fact on file; Investify's newest figure joins only when proven.

    Investify labels no basis and, for one company, can follow different bases for different figures
    (HBL's annual EPS matches PSX's unconsolidated figure and its year-to-date EPS matches PSX's consolidated
    one). So its newest figure is paired with last year's PSX figure only when (1) PSX's figure for that prior
    period exists on exactly one basis, and (2) Investify's own figures agree with PSX on that basis wherever
    the two overlap (at least once, and never a disagreement). Otherwise it stays unpaired and the result
    stays unknown."""
    psx = [f for f in facts if not _is_investify(f)]
    hist = eps_history(psx)
    notes: dict[tuple[str, int], str] = {}
    fye = _fiscal_year_end(hist)
    points = []
    if fye:
        for f in facts:
            if _is_investify(f) and f.get("value") is not None:
                key = investify_key(f["topic"], f.get("period"), fye)
                if key:
                    points.append((key, float(f["value"])))
    by_period: dict[tuple[str, int], dict[str, float | None]] = {}
    for (kind, year), val in hist.items():
        base, _, basis = kind.partition("|")
        if "@" in base:  # PSX-style period; an unlabelled basis ("") is a basis of its own
            by_period.setdefault((base, year), {})[basis] = val
    agree: set[str] = set()
    disagree = False
    for key, val in points:
        bases = by_period.get(key)
        if bases and len(bases) == 1:
            basis, other = next(iter(bases.items()))
            if other is None or abs(val - other) > AGREE_TOLERANCE * max(abs(other), 1e-9):
                disagree = True
            else:
                agree.add(basis)
    if agree and not disagree:
        for (kind, year), val in points:
            if (kind, year) in by_period:
                continue  # PSX already has this period: its figure stands
            prior = by_period.get((kind, year - 1), {})
            if len(prior) == 1 and next(iter(prior)) in agree:
                basis = next(iter(prior))
                before = prior[basis]
                if before is not None and before > 0 and val / before > IMPLAUSIBLE_RATIO:
                    continue  # more than 4x last year's figure: more likely a source slip than a result
                key = f"{kind}|{basis}" if basis else kind
                hist[(key, year)] = val
                notes[(key, year)] = "Investify"
    return eps_change(hist, notes)
