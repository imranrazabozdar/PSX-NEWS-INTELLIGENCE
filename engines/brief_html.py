# ruff: noqa: E501
"""HTML for the company page: the same dark, phone-first cards as the dashboard. Pure functions; every dynamic
string is escaped. Nothing here advises: it lays out what the company brief already holds."""

from __future__ import annotations

from html import escape as e
from typing import Any

from engines import dashboard_html as ui


def _chg(v: float | None) -> str:
    if v is None:
        return '<span class="m">n/a</span>'
    cls = "g" if v > 0 else "r" if v < 0 else "m"
    return f'<span class="{cls}">{v:+.1f}%</span>'


def header(b: dict[str, Any], name: str = "") -> str:
    p = b["price"]
    sector = e(b["sector"]) if b.get("sector") else "sector unknown"
    top = (
        f'<div class="pi-h"><span style="font-size:1.4rem;font-weight:800;color:#e8eaed">{e(b["symbol"])}</span>'
        f"<span>{e(name)} · {sector}</span></div>"
    )
    if not p:
        return f'<div class="pi-card">{top}<div class="pi-note">No price series on file.</div></div>'
    return (
        f'<div class="pi-card">{top}'
        f'<div class="pi-row"><div><div class="pi-mini">Close {e(str(p["date"]))}</div>'
        f'<div style="font-size:1.5rem;font-weight:800">{p["close"]:,.2f}</div></div>'
        f'<div class="pi-px"><div class="pi-mini">1 day · 5 days · 20 days</div>'
        f"<div>{_chg(p['change_1d'])} · {_chg(p['change_5d'])} · {_chg(p['change_20d'])}</div></div></div></div>"
    )


def standing(found: dict[str, Any] | None) -> str:
    """Where the company stands in the setups rankings (from setups.lookup), or why it is not scored."""
    if not found:
        return ""
    if found["row"] is None:
        return (
            '<div class="pi-card"><div class="pi-h">In the setups rankings<span>not scored</span></div>'
            f'<div class="pi-note">{e(found["reason"])}</div></div>'
        )
    r, rk = found["row"], found["ranks"]

    def cell(key: str, label: str) -> str:
        v = r[key]
        if v is None:
            return f"<div>{label} <span class='m'>unknown</span><i></i></div>"
        pos = f" · rank {rk[key][0]} of {rk[key][1]}" if rk.get(key) else ""
        return f"<div>{label} <b style='color:#e8eaed'>{v:.0f}</b>{pos}<i><b style='width:{v:.0f}%'></b></i></div>"

    return (
        '<div class="pi-card"><div class="pi-h">In the setups rankings<span>evidence on file, not advice</span></div>'
        f'<div class="pi-pil">{cell("technical", "Technical")}{cell("fundamental", "Fundamental")}</div>'
        f'<div class="pi-pil">{cell("combined", "Combined")}</div></div>'
    )


def facts(rows: list[dict[str, Any]], empty: str, date_key: str = "event_date") -> str:
    if not rows:
        return f'<div class="pi-card m">{e(empty)}</div>'
    lines = "".join(
        f'<div class="pi-row"><div><div class="pi-mini">{e(str(f.get(date_key) or f.get("as_of") or ""))}</div>'
        f'<div style="font-size:.86rem">{e(str(f.get("fact_text") or f.get("text") or "")[:260])}</div>'
        f'<div class="pi-mini">{e(str(f.get("source_name") or f.get("source") or ""))}</div></div></div>'
        for f in rows
    )
    return f'<div class="pi-card">{lines}</div>'


def announcements(items: list[dict[str, Any]]) -> str:
    shown = [x for x in items if x["weight"] != "routine"]
    out = []
    for x in shown:
        tag = f"size: {x['tier']}" if x["weight"] == "material" else "scheduled notice"
        basis = "".join(f"<p><i>basis:</i> {e(line)}</p>" for line in (x.get("basis") or []))
        summary = (
            f'<div class="pi-st"><b>{e(str(x["label"]))}</b> <span class="pi-chip">{e(tag)}</span>'
            f"<div>{e(str(x['date']))}</div><div>{e(str(x['text'])[:140])}</div></div>"
        )
        out.append(ui._details(summary, [e(str(x["text"])[:400]), *(basis and [basis])]))  # noqa: SLF001
    routine = len(items) - len(shown)
    note = f'<div class="pi-note">{routine} routine filings not listed (transmissions, briefings, insiders).</div>'
    if not items:
        return '<div class="pi-card m">No announcements on file for the last month.</div>'
    return "".join(out) + (note if routine else "")


def news(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return '<div class="pi-card m">No news on file for the last month.</div>'
    lines = []
    for r in rows:
        title = e(str(r["top_title"] or "")[:160])
        link = (
            f' · <a href="{e(r["top_url"])}" target="_blank" rel="noopener">source</a>'
            if r.get("top_url")
            else ""
        )
        lines.append(
            f'<div class="pi-row"><div><div class="pi-mini">{e(str(r["day"]))} · {r["stories"]} stories</div>'
            f'<div style="font-size:.86rem">{title}{link}</div></div></div>'
        )
    return f'<div class="pi-card">{"".join(lines)}</div>'


def moves(items: list[dict[str, Any]]) -> str:
    if not items:
        return (
            '<div class="pi-card m">No notable move (5% or more, or heavy volume) in the last 30 days.</div>'
        )
    out = []
    for m in items:
        cls = "g" if m["move"] > 0 else "r"
        vol = f" · volume {m['volume_x']:.1f}x usual" if m.get("volume_x") else ""
        label = ui.cause_label(m)
        summary = (
            f'<div class="pi-st"><b>{e(str(m["day"]))}</b> <span class="{cls}">{m["move"]:+.1f}%</span>{e(vol)}'
            f'<div><span class="pi-chip">{e(label)}</span></div><div>{e(str(m["verdict"]))}</div></div>'
        )
        lines = [
            f"<b>{e(str(x['kind']))}</b> <i>({e(str(x['date']))}, {e(str(x['source']))})</i><br>{e(str(x['text']))}"
            for x in m["evidence"]
        ] + [
            f"<i>market context (not shown to cause this move):</i> {e(str(c))}"
            for c in m.get("macro_context", [])
        ]
        out.append(ui._details(summary, lines or ["<i>No evidence on file for this move.</i>"]))  # noqa: SLF001
    return "".join(out)
