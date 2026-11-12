"""Identity checks by coordinates for the readable vault reports.

Results go to a THROWAWAY local SQLite only.

Per report: the balance sheet (A=L+E, equity from components and the printed subtotal) and the income
statement
(PBT-tax=PAT) on each resolved period column. Nothing here fetches, and nothing here writes to Turso or
production.

  python -m scripts.run_position_identities --vault <dir> --db <throwaway.sqlite>
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pdfplumber

from engines import layout_words as lw
from engines import pdf_extraction as pe
from engines import position_identities as pid
from engines import report_metadata as rm

SCHEMA = """CREATE TABLE IF NOT EXISTS identity_checks (
    symbol TEXT, period_end TEXT, report_type TEXT, statement TEXT, column_role TEXT, column_group TEXT,
    column_x REAL, identity TEXT, status TEXT, detail TEXT, page INTEGER)"""


def _chars(path: Path, page: int) -> list[dict]:
    with pdfplumber.open(path) as pdf:
        return [
            {"text": c["text"], "x0": c["x0"], "x1": c["x1"], "top": c["top"]}
            for c in pdf.pages[page - 1].chars
        ]


def check_report(row: dict, vault: Path) -> list[tuple]:
    path = vault / row["vault_path"]
    doc = pe.extract(path)
    layout = rm.detect_layout(doc, row["period_end"])
    out: list[tuple] = []
    pages = layout.get("statement_pages", {})
    if "BS" in pages:
        page_no = pages["BS"][0]
        page = lw.apply_deshadow(lw.read_page(_chars(path, page_no)))
        bands = page["columns"]
        if page["ambiguous"] or len(bands) != 2:
            out.append(
                (
                    row["symbol"],
                    row["period_end"],
                    row["report_type"],
                    "BS",
                    "",
                    "",
                    None,
                    "A=L+E",
                    "requires_review",
                    f"{len(bands)} distinct columns; {len(page['ambiguous'])} ambiguous",
                    page_no,
                )
            )
        else:
            for idx, (x, _) in enumerate(bands):
                role = "current" if idx == 0 else "prior"
                res = pid.balance_identity(page["rows"], idx)
                detail = json.dumps({k: res.get(k) for k in ("assets", "liabilities", "delta")}, default=str)
                eq = res.get("equity", {})
                detail += f" equity_source={eq.get('source')} equity={eq.get('value')}"
                out.append(
                    (
                        row["symbol"],
                        row["period_end"],
                        row["report_type"],
                        "BS",
                        role,
                        "",
                        x,
                        "A=L+E",
                        res["status"],
                        detail,
                        page_no,
                    )
                )
    if "IS" in pages:
        page_no = pages["IS"][0]
        words_chars = _chars(path, page_no)
        page = lw.apply_deshadow(lw.read_page(words_chars))
        words = lw.words_from_chars(lw.dedupe_chars(words_chars)[0])
        header = [w for w in words if w.top < min((r.top for r in page["rows"] if r.cells), default=1e9)]
        roles = pid.period_group_columns(header, page["columns"])
        for idx, (x, _) in enumerate(page["columns"]):
            info = roles.get(idx)
            if info is None or "role" not in info:
                out.append(
                    (
                        row["symbol"],
                        row["period_end"],
                        row["report_type"],
                        "IS",
                        "unresolved",
                        "",
                        x,
                        "PBT-tax=PAT",
                        "requires_review",
                        "column group not found in header",
                        page_no,
                    )
                )
                continue
            res = pid.tax_identity(page["rows"], idx)
            out.append(
                (
                    row["symbol"],
                    row["period_end"],
                    row["report_type"],
                    "IS",
                    info["role"],
                    info["group"],
                    x,
                    "PBT-tax=PAT",
                    res["status"],
                    json.dumps(res, default=str),
                    page_no,
                )
            )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Identity checks by coordinates; throwaway SQLite only")
    ap.add_argument("--vault", required=True, type=Path)
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--symbols", nargs="*")
    args = ap.parse_args(argv)
    if "://" in str(args.db):
        print("refused: local file only", file=sys.stderr)
        return 2
    manifest = [
        json.loads(x) for x in (args.vault / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if x
    ]
    # the six readable reports: all NRL reports and the HUBC annual
    rows = [
        r
        for r in manifest
        if r.get("source") == "ir_fetch"
        and (r["symbol"] == "NRL" or (r["symbol"] == "HUBC" and r["report_type"] == "annual_report"))
    ]
    rows = [r for r in rows if not args.symbols or r["symbol"] in args.symbols]
    if args.db.exists():
        args.db.unlink()
    con = sqlite3.connect(args.db)
    con.execute(SCHEMA)
    for row in rows:
        try:
            checks = check_report(row, args.vault)
        except Exception as exc:  # one report never stops the run
            checks = [
                (
                    row["symbol"],
                    row["period_end"],
                    row["report_type"],
                    "ALL",
                    "",
                    "",
                    None,
                    "run",
                    "requires_review",
                    f"{type(exc).__name__}: {exc}",
                    None,
                )
            ]
        con.executemany("INSERT INTO identity_checks VALUES (?,?,?,?,?,?,?,?,?,?,?)", checks)
        for c in checks:
            print(f"{c[0]} {c[1]} {c[2]} {c[3]} {c[4]:<10} {c[7]:<11} {c[8]:<16} {c[9][:150]}", flush=True)
    con.commit()
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
