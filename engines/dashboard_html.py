# ruff: noqa: E501  (HTML and CSS strings)
"""HTML for the Streamlit dashboard: a dark, phone-first look. Pure functions, every dynamic string escaped.

Colours: green up, red down, teal accent. Nothing here decides or advises; it only lays out what the
dashboard data already holds.
"""

from __future__ import annotations

from html import escape as e
from typing import Any

CSS = """
<style>
.block-container{padding:1rem .9rem 4rem;max-width:760px}
.pi-bar{display:flex;justify-content:space-between;gap:8px;font-size:.78rem;color:#9aa0a6;
 padding:.35rem 0 .7rem;border-bottom:1px solid #222}
.pi-bar b{color:#e8eaed}
.pi-title{font-size:1.5rem;font-weight:800;margin:.2rem 0 .1rem;letter-spacing:.2px}
.pi-sub{color:#8a8f98;font-size:.8rem;margin-bottom:.6rem}
.pi-card{background:#121316;border:1px solid #26282d;border-radius:14px;padding:.85rem .95rem;margin:.6rem 0}
.pi-h{font-weight:700;font-size:1.02rem;display:flex;justify-content:space-between;align-items:baseline}
.pi-h span{font-weight:400;font-size:.78rem;color:#8a8f98}
.pi-breadth{display:flex;height:10px;border-radius:6px;overflow:hidden;margin:.6rem 0 .45rem;background:#222}
.pi-up{background:#18c08a}.pi-dn{background:#f0455a}.pi-fl{background:#6b6f76}
.pi-legend{display:flex;justify-content:space-between;font-size:.82rem}
.g{color:#18c08a}.r{color:#f0455a}.m{color:#8a8f98}
.pi-row{display:flex;justify-content:space-between;align-items:center;padding:.62rem 0;
 border-bottom:1px solid #1d1f24}
.pi-row:last-child{border-bottom:0}
.pi-sym{font-weight:800;font-size:1.02rem}
.pi-name{font-size:.74rem;color:#8a8f98;max-width:46vw;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pi-px{text-align:right}.pi-px b{font-size:1.02rem}
.pi-mini{font-size:.7rem;color:#8a8f98}
details.pi-d{background:#121316;border:1px solid #26282d;border-radius:14px;margin:.55rem 0;padding:.1rem .9rem}
details.pi-d summary{cursor:pointer;list-style:none;padding:.75rem 0;display:flex;gap:.6rem;align-items:center}
details.pi-d summary::-webkit-details-marker{display:none}
details.pi-d summary::after{content:"\\25BE";color:#6b7280;font-size:1rem;margin-left:auto}
details.pi-d[open] summary::after{content:"\\25B4"}
.pi-score{background:#16323a;color:#4fd8e0;border-radius:8px;padding:.15rem .5rem;font-weight:800;
 font-size:.85rem;min-width:2.3rem;text-align:center}
.pi-st{flex:1}.pi-st b{font-size:1rem}.pi-st div{font-size:.76rem;color:#9aa0a6}
.pi-chip{display:inline-block;font-size:.66rem;border-radius:20px;padding:.08rem .5rem;margin:0 .25rem .25rem 0;
 background:#1c1f26;color:#b9c0cc;border:1px solid #2b2f38}
.pi-body{padding:.1rem 0 .8rem;font-size:.84rem;color:#d4d7dc;line-height:1.35}
.pi-body p{margin:.35rem 0}.pi-body i{color:#8a8f98}
.pi-pil{display:flex;gap:.9rem;margin:.3rem 0 .1rem}
.pi-pil div{flex:1;font-size:.68rem;color:#8a8f98}
.pi-pil i{display:block;height:5px;border-radius:3px;background:#222;margin-top:3px;overflow:hidden}
.pi-pil i b{display:block;height:100%;background:#4fd8e0}
.pi-rk{color:#6b7280;font-weight:700;min-width:1.4rem}
.pi-note{font-size:.74rem;color:#7d828b;margin:.4rem 0 .2rem}
</style>
"""


def _signed(x: float) -> str:
    return f"{x:+.2f}%"


def status_bar(price_day: str | None, news_day: str | None, universe: int) -> str:
    return (
        f'<div class="pi-bar"><span>Prices to <b>{e(price_day or "unknown")}</b></span>'
        f"<span>News to <b>{e(news_day or 'unknown')}</b></span>"
        f"<span><b>{universe}</b> stocks</span></div>"
    )


def title(text: str, sub: str = "") -> str:
    return f'<div class="pi-title">{e(text)}</div><div class="pi-sub">{e(sub)}</div>'


def breadth_card(b: dict[str, Any] | None) -> str:
    if not b:
        return '<div class="pi-card"><div class="pi-h">Market breadth<span>no price data</span></div></div>'
    total = max(b["symbols"], 1)
    pct = lambda n: f"{100 * n / total:.1f}%"  # noqa: E731
    top_up = ", ".join(f"{e(s)} {v:+.1f}%" for s, v in b["top_up"])
    top_dn = ", ".join(f"{e(s)} {v:+.1f}%" for s, v in b["top_down"])
    return (
        '<div class="pi-card">'
        f'<div class="pi-h">Market breadth<span>{b["symbols"]} stocks traded · median {b["median"]:+.2f}%</span></div>'
        f'<div class="pi-breadth"><div class="pi-up" style="width:{pct(b["up"])}"></div>'
        f'<div class="pi-fl" style="width:{pct(b["flat"])}"></div>'
        f'<div class="pi-dn" style="width:{pct(b["down"])}"></div></div>'
        f'<div class="pi-legend"><span class="g">{b["up"]} advanced</span>'
        f'<span class="m">{b["flat"]} unchanged</span><span class="r">{b["down"]} declined</span></div>'
        f'<div class="pi-note">Biggest rises: {top_up}<br>Biggest falls: {top_dn}</div>'
        "</div>"
    )


def mover_rows(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<div class="pi-card m">No trades on the latest day.</div>'
    rows = []
    for m in items:
        cls = "g" if m["move"] > 0 else "r" if m["move"] < 0 else "m"
        arrow = "▲" if m["move"] > 0 else "▼" if m["move"] < 0 else "–"
        vol = f"{m['volume'] / 1e6:.2f}M" if m["volume"] >= 1e6 else f"{m['volume']:,.0f}"
        vx = f" · {m['volume_x']:.1f}x usual" if m.get("volume_x") else ""
        rows.append(
            f'<div class="pi-row"><div><div class="pi-sym">{e(m["symbol"])}</div>'
            f'<div class="pi-name">{e(m["name"] or "")}</div>'
            f'<div class="pi-mini">vol {vol}{vx}</div></div>'
            f'<div class="pi-px"><b>{m["close"]:,.2f}</b><div class="{cls}">{arrow} {_signed(m["move"])}</div></div>'
            "</div>"
        )
    return '<div class="pi-card">' + "".join(rows) + "</div>"


def _details(summary_html: str, body_lines: list[str]) -> str:
    body = "".join(f"<p>{line}</p>" for line in body_lines)
    return (
        f'<details class="pi-d"><summary>{summary_html}</summary><div class="pi-body">{body}</div></details>'
    )


def radar_cards_html(
    radar: list[dict[str, Any]], names: dict[str, str], ctx: dict[str, dict[str, Any]] | None = None
) -> str:
    out = []
    for s in radar:
        top = max(s["drivers"], key=lambda d: d["points"])
        kinds = "".join(
            f'<span class="pi-chip">{e(k)}</span>' for k in sorted({d["kind"] for d in s["drivers"]})
        )
        summary = (
            f'<span class="pi-score">{s["score"]:g}</span><div class="pi-st"><b>{e(s["symbol"])}</b>'
            f"<div>{e(names.get(s['symbol'], ''))}</div><div>{e(top['text'][:90])}</div>{kinds}</div>"
        )
        lines = [
            f"<b>{e(d['kind'])}</b> <i>({e(str(d['date']))}, {e(str(d['source']))})</i><br>{e(d['text'][:260])}"
            for d in sorted(s["drivers"], key=lambda d: -d["points"])
        ]
        lines += [f"<i>unknown:</i> {e(u)}" for u in s["unknown"][:2]]
        c = (ctx or {}).get(s["symbol"])
        if c:
            latest = f"; latest {e(c['latest'][0])}: {e(c['latest'][1])}" if c["latest"] else ""
            lines.append(
                f"<i>context:</i> {c['d7']} material item(s) in the last 7 days, {c['d30']} in the last 30{latest}"
            )
        out.append(_details(summary, lines))
    return "".join(out) or '<div class="pi-card m">Nothing scored.</div>'


def move_cards_html(moves: list[dict[str, Any]]) -> str:
    out = []
    for m in moves:
        cls = "g" if m["move"] > 0 else "r"
        vol = f" · volume {m['volume_x']:.1f}x usual" if m.get("volume_x") else ""
        summary = (
            f'<div class="pi-st"><b>{e(m["symbol"])}</b> <span class="{cls}">{_signed(m["move"])}</span>'
            f"<div>{e(m['day'])}{vol}</div><div>{e(m['verdict'])}</div></div>"
        )
        lines = [e(x["text"][:220]) for x in m["evidence"][:3]] or ["<i>No evidence on file.</i>"]
        out.append(_details(summary, lines))
    return "".join(out) or '<div class="pi-card m">None.</div>'


def unexplained_card(moves: list[dict[str, Any]], total: int) -> str:
    ranked = sorted(moves, key=lambda m: -abs(m["move"]) * (m.get("volume_x") or 1))[:25]
    rows = []
    for m in ranked:
        cls = "g" if m["move"] > 0 else "r"
        vol = f'<span class="pi-mini"> volume {m["volume_x"]:.1f}x</span>' if m.get("volume_x") else ""
        rows.append(
            f'<div class="pi-row"><div><span class="pi-sym">{e(m["symbol"])}</span>{vol}'
            f'<div class="pi-mini">{e(m["day"])}</div></div><b class="{cls}">{_signed(m["move"])}</b></div>'
        )
    head = (
        f'<div class="pi-h">No cause on file<span>{len(moves)} of {total} notable moves</span></div>'
        '<div class="pi-note">Absence of evidence on file, not proof of no cause.</div>'
    )
    return '<div class="pi-card">' + head + "".join(rows) + "</div>"


def _pillar_bar(label: str, value: float | None) -> str:
    if value is None:
        return f"<div>{e(label)} <span class='m'>unknown</span><i></i></div>"
    return f"<div>{e(label)} <b style='color:#e8eaed'>{value:.0f}</b><i><b style='width:{value:.0f}%'></b></i></div>"


def setup_cards_html(rows: list[dict[str, Any]], mode: str) -> str:
    """mode: technical | fundamental | combined. One tap-to-open card per stock, best first."""
    out = []
    for i, r in enumerate(rows, 1):
        score = r[mode]
        show_t = mode in ("technical", "combined")
        show_f = mode in ("fundamental", "combined")
        bars = (_pillar_bar("Technical", r["technical"]) if show_t else "") + (
            _pillar_bar("Fundamental", r["fundamental"]) if show_f else ""
        )
        sector = f" · {e(r['sector'])}" if r.get("sector") else ""
        summary = (
            f'<span class="pi-rk">{i}</span><span class="pi-score">{score:.0f}</span>'
            f'<div class="pi-st"><b>{e(r["symbol"])}</b> <span class="m">{r["close"]:,.2f}</span>'
            f'<div>{e(r["name"] or "")}{sector}</div><div class="pi-pil">{bars}</div></div>'
        )
        lines = []
        if show_t:
            lines += [f"<b>Technical:</b> {e(x)}" for x in r["tech_evidence"]]
            if r["tech_unknown"]:
                lines.append("<i>not on file:</i> " + e(", ".join(r["tech_unknown"])))
        if show_f:
            lines += [f"<b>Fundamental:</b> {e(x)}" for x in r["fund_evidence"]]
            if r["fund_unknown"]:
                lines.append("<i>not on file:</i> " + e(", ".join(r["fund_unknown"])))
        out.append(_details(summary, lines))
    return "".join(out) or '<div class="pi-card m">Nothing qualifies on the evidence on file.</div>'


def lookup_html(found: dict[str, Any]) -> str:
    """One stock's standing: its three scores and ranks, its evidence, or why it is not scored."""
    sym = e(found["symbol"])
    if found["row"] is None:
        return f'<div class="pi-card"><div class="pi-h">{sym}<span>not scored</span></div><div class="pi-note">{e(found["reason"])}</div></div>'
    r = found["row"]

    def rank(key: str) -> str:
        v, rk = r[key], found["ranks"].get(key)
        if v is None:
            return "unknown (not enough on file)"
        return f"{v:.0f}" + (f" · rank {rk[0]} of {rk[1]}" if rk else "")

    rows = [
        f"<b>Technical:</b> {rank('technical')}",
        f"<b>Fundamental:</b> {rank('fundamental')}",
        f"<b>Combined:</b> {rank('combined')}",
    ]
    rows += [f"<b>Technical:</b> {e(x)}" for x in r["tech_evidence"]]
    rows += [f"<b>Fundamental:</b> {e(x)}" for x in r["fund_evidence"]]
    rows += ["<i>not on file:</i> " + e(", ".join(r["tech_unknown"] + r["fund_unknown"]))]
    return (
        f'<div class="pi-card"><div class="pi-h">{sym}<span>{e(r["name"] or "")}</span></div>'
        + "".join(f"<p class='pi-body'>{x}</p>" for x in rows)
        + "</div>"
    )


def moves_by_day_html(moves: list[dict[str, Any]], per_day: int = 12) -> str:
    """Notable moves grouped by trading day, newest day first, biggest first within a day. Every move is
    shown: the ones with a candidate cause open to its evidence, the others say plainly that none is on file."""
    days: dict[str, list[dict[str, Any]]] = {}
    for m in moves:
        days.setdefault(m["day"], []).append(m)
    out = []
    for day in sorted(days, reverse=True):
        rows = sorted(days[day], key=lambda m: -abs(m["move"]) * (m.get("volume_x") or 1))
        none = sum(1 for m in rows if m["verdict"].startswith("no identified cause"))
        out.append(
            f'<div class="pi-h" style="margin-top:1rem">{e(day)}'
            f"<span>{len(rows)} notable moves · {none} with no cause on file</span></div>"
        )
        for m in rows[:per_day]:
            cls = "g" if m["move"] > 0 else "r"
            vol = f"volume {m['volume_x']:.1f}x usual" if m.get("volume_x") else "volume not comparable"
            nocause = m["verdict"].startswith("no identified cause")
            verdict = "no cause on file yet" if nocause else m["verdict"]
            label = cause_label(m)
            summary = (
                f'<div class="pi-st"><b>{e(m["symbol"])}</b> <span class="{cls}">{_signed(m["move"])}</span>'
                f"<div>{e(vol)}</div>"
                f'<div><span class="pi-chip">{e(label)}</span></div>'
                f'<div class="{"m" if nocause else ""}">{e(verdict)}</div></div>'
            )
            lines = [e(x["text"][:220]) for x in m["evidence"][:3]]
            lines += [f"<i>technical engine:</i> {e(t)}" for t in m.get("technical_context", [])[:2]]
            if not lines:
                lines = ["<i>No evidence on file for this move.</i>"]
            out.append(_details(summary, lines))
        if len(rows) > per_day:
            out.append(f'<div class="pi-note">{len(rows) - per_day} smaller moves on {e(day)} not shown.</div>')
    return "".join(out) or '<div class="pi-card m">No notable moves in the last few days.</div>'


def cause_label(move: dict[str, Any]) -> str:
    """One plain label for what the evidence on file says about a move. CONFIRMED_EVENT and
    CONTRADICTORY_EVIDENCE are deliberately never produced: a stored fact cannot confirm a cause, and
    direction conflicts are not yet tested; the labels exist in the vocabulary for when they can be."""
    verdict = move["verdict"]
    if verdict.startswith("no identified cause") or verdict.startswith("only routine"):
        return "NO_IDENTIFIED_CAUSE"
    kinds = {x.get("kind") for x in move.get("evidence", [])}
    company = {k for k in kinds if k in ("company_event", "company_news")}
    if verdict.startswith("the move was shared"):
        return "PLAUSIBLE_CATALYST (sector or market)"
    if len(company) >= 2 or (company and len(move.get("evidence", [])) >= 3):
        return "MULTIPLE_POSSIBLE_CATALYSTS"
    return "PLAUSIBLE_CATALYST"
