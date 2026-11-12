"""READ-ONLY diagnostic: trace the balance sheet of one vault report through the extraction stages.

Instrumentation only. It calls the existing functions, changes no extraction behaviour, makes no network
request and writes nothing except the trace file. It answers four questions for ONE report (NRL annual
FY2026 by default):
  1. which page was selected as the balance sheet, its heading, and whether it looks like a summary page;
  2. the column headers, the chosen current-period column, and the date it matched;
  3. the first rows: raw label -> canonical code (or UNMAPPED) -> raw cell -> parsed value;
  4. for the A=L+E identity, which total codes got a non-null value.

  python -m scripts.diag_nrl_bs_trace --vault <dir> --symbol NRL --period-end 2026-06-30 --out <trace.txt>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from engines import pdf_extraction as pe
from engines import report_metadata as rm
from engines import statement_pipeline as sp
from engines.financials import parse_statement_text

ROWS_SHOWN = 40
SUMMARY_WORDS = ("six years", "at a glance", "summary", "highlights", "five year", "ten year")


def _page(doc, number):
    return next(p for p in doc.pages if p.number == number)


def _heading_pages(doc):
    """Every page with a balance-sheet heading (a whole line, or two lines joined), selected or not."""
    rows = []
    for page in doc.pages:
        lines = page.lines
        for idx, line in enumerate(lines):
            joined = line
            code = rm.heading_code(line)
            if code is None and idx + 1 < len(lines):
                joined = f"{line} {lines[idx + 1]}"
                code = rm.heading_code(joined)
            if code == "BS":
                top = " ".join(lines[:3]).lower()
                rows.append(
                    {
                        "page": page.number,
                        "heading": joined.strip()[:90],
                        "amount_lines": rm.amount_lines(lines),
                        "summary_like": any(w in top for w in SUMMARY_WORDS),
                    }
                )
                break
    return rows


def _cell_tokens(line: str, n: int) -> list[str] | None:
    toks = line.split()
    vals: list[str] = []
    while toks and re.fullmatch(r"\(?-?[\d,]+(\.\d+)?\)?|-|—", toks[-1]):
        vals.insert(0, toks.pop())
    return vals if len(vals) >= n else None


def run(vault: Path, symbol: str, period_end: str, out: Path) -> None:
    manifest = [
        json.loads(x) for x in (vault / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if x
    ]
    row = next(
        r
        for r in manifest
        if r.get("symbol") == symbol
        and r.get("period_end") == period_end
        and r.get("report_type") == "annual_report"
    )
    pdf = vault / row["vault_path"]
    doc = pe.extract(pdf)
    layout = rm.detect_layout(doc, period_end)
    out_lines: list[str] = []

    def w(text: str = "") -> None:
        out_lines.append(text)

    w(f"TRACE: {symbol} {period_end} annual_report  file={row['vault_path']}")
    w(
        f"detector blocker={layout.get('blocker')} flags={layout.get('flags')} "
        f"unit={layout.get('unit_scale')} "
        f"consolidation={layout.get('consolidation')}"
    )
    w()

    # 1. page selection and ranking
    w("1. PAGE SELECTION (balance sheet)")
    chosen = layout.get("statement_pages", {}).get("BS", [])
    w(f"   selected BS page(s): {chosen}")
    for n in chosen[:1]:
        p = _page(doc, n)
        w(f"   selected page {n} heading lines: {[ln.strip()[:70] for ln in p.lines[:3]]}")
        flag = any(w_ in " ".join(p.lines[:3]).lower() for w_ in SUMMARY_WORDS)
        w(f"   looks like a summary/six-year page: {flag}")
    w("   every page carrying a balance-sheet heading (page ranking):")
    for r in _heading_pages(doc):
        mark = "SELECTED" if r["page"] in chosen else "        "
        w(
            f"     {mark} p{r['page']:<4} amounts={r['amount_lines']:<3} summary_like={r['summary_like']}  "
            f"heading='{r['heading']}'"
        )
    w()

    # 2. column headers and the chosen column
    columns = layout.get("columns", [])
    w("2. COLUMNS")
    w(f"   detected column dates: {columns}")
    target = period_end
    chosen_col = layout.get("period_column")
    w(f"   period_end requested: {target}; matched column: {chosen_col}")
    if chosen_col in columns:
        w(f"   chosen column index: {columns.index(chosen_col)} of {len(columns)}")
    if chosen:
        head = _page(doc, chosen[0]).lines[:14]
        w("   balance-sheet header lines (first 14):")
        for ln in head:
            w(f"     | {ln.rstrip()[:150]}")
    w()

    # 3. rows
    w(f"3. TAGGED ROWS (first {ROWS_SHOWN} with values)")
    mapping = sp.load_mappings(framework="corporate")
    n_cols = len(columns)
    parsed_lines: list[dict] = []
    unparsed: list[dict] = []
    raw_text_by_label: dict[str, str] = {}
    for number in chosen[:1]:
        page = _page(doc, number)
        parsed = parse_statement_text(
            "\n".join(page.lines), statement="BS", columns=columns, page=page.number
        )
        parsed_lines = parsed["lines"]
        unparsed = parsed["unparsed"]
        for ln in page.lines:
            toks = ln.split()
            if toks:
                raw_text_by_label.setdefault(
                    " ".join(t for t in toks if not re.fullmatch(r"\(?[\d,.]+\)?", t)), ln
                )
    w(f"   parsed value records: {len(parsed_lines)}  unparsed lines: {len(unparsed)}")
    reasons: dict[str, int] = {}
    for u in unparsed:
        key = re.sub(r"\d+", "N", u.get("reason", "?"))
        reasons[key] = reasons.get(key, 0) + 1
    w(f"   unparsed reasons: {reasons}")
    seen: list[str] = []
    for ln in parsed_lines:
        if ln["raw_label"] not in seen:
            seen.append(ln["raw_label"])
    w(f"   distinct labels parsed: {len(seen)}")
    w()
    w(f"   {'raw label':<52} -> {'canonical':<28} -> {'raw cell (chosen col)':<22} -> value")
    shown = 0
    for label in seen:
        if shown >= ROWS_SHOWN:
            break
        rec_chosen = next(
            (r for r in parsed_lines if r["raw_label"] == label and r["column_period_end"] == chosen_col),
            None,
        )
        code, conf = sp.map_label("BS", label, mapping)
        raw_line = raw_text_by_label.get(label, "")
        toks = _cell_tokens(raw_line, n_cols) if raw_line else None
        idx = columns.index(chosen_col) if chosen_col in columns else 0
        raw_cell = toks[idx] if toks and idx < len(toks) else "?"
        value = rec_chosen["value"] if rec_chosen else None
        w(f"   {label[:52]:<52} -> {str(code or 'UNMAPPED'):<28} -> {raw_cell:<22} -> {value}")
        shown += 1
    w()

    # 4. identity inputs
    w("4. A=L+E IDENTITY INPUTS")
    codes_needed = {"total assets": None, "total liabilities": None, "total equity": None}
    by_code: dict[str, list] = {}
    for ln in parsed_lines:
        code, _ = sp.map_label("BS", ln["raw_label"], mapping)
        if code and ln["column_period_end"] == chosen_col:
            by_code.setdefault(code, []).append(ln["value"])
    all_codes = sorted(by_code)
    w(f"   canonical codes present on the chosen column: {all_codes}")
    for key in codes_needed:
        hits = [c for c in all_codes if key.replace("total ", "") in c and "total" in c]
        values = {c: [v for v in by_code[c] if v is not None] for c in hits}
        w(
            f"   {key:<18}: candidates={hits or 'NONE'} non-null="
            f"{ {c: v[:1] for c, v in values.items()} or 'none' }"
        )
    w()
    w("   raw total rows on the page (regardless of mapping):")
    for ln in parsed_lines:
        if ln["column_period_end"] == chosen_col and re.match(
            r"(?i)total|net assets|capital and reserves|equity", ln["raw_label"]
        ):
            w(
                f"     {ln['raw_label'][:60]:<60} value={ln['value']} "
                f"code={sp.map_label('BS', ln['raw_label'], mapping)[0]}"
            )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"trace written: {out} ({len(out_lines)} lines)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="READ-ONLY balance-sheet trace for one vault report")
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--symbol", default="NRL")
    ap.add_argument("--period-end", default="2026-06-30")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    run(args.vault, args.symbol, args.period_end, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
