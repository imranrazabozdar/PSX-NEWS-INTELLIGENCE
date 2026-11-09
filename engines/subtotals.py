"""Deterministic recognition of unlabelled subtotal rows (master plan M2, pilot defect D5).

A statement row with figures but no label is never given a name by guesswork. It is recognised only when:

* R1 (block sum): its figures equal, in every column, the sum of one contiguous run of the rows directly
  above it (labelled rows or rows already recognised), within the same heading block, and exactly one such
  run matches. Two different matching runs make it ambiguous and it stays unresolved.
* A canonical meaning is given only by a fixed structural position:
  - R2 total_equity: the R1 subtotal that closes the block under "SHARE CAPITAL AND RESERVES".
  - R3 total_assets: the R1 subtotal that equals the sum of the two closing asset subtotals (NON CURRENT
    ASSETS and CURRENT ASSETS), where each closes its own heading block.
  - R4 cost_of_sales: the R1 subtotal whose rows lie exactly between the revenue row and the labelled
    "Gross profit" row on an income statement.

Every recognised row keeps its original text and records the rule in its stored label, so an explicit label
and a structural recognition can never be confused. Nothing here creates a value: each figure is the text
figure from the page. Unresolved rows are returned as such and stay out of the reconciliation.
"""

from __future__ import annotations

from engines import financials as fin

RULE_VERSION = "1"  # bump when a rule's behaviour changes; stored with every recognised row

HEADINGS = {"SHARE CAPITAL AND RESERVES", "NON CURRENT LIABILITIES", "CURRENT LIABILITIES",
            "NON CURRENT ASSETS", "CURRENT ASSETS"}


def _elements(lines: list[str], *, statement: str, columns: list[str], page: int) -> list[dict]:
    """Classify each extracted line, in order, as a heading, a labelled item, a figures-only row or text."""
    out = []
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if s in HEADINGS:
            out.append({"kind": "heading", "label": s, "text": s, "page": page})
            continue
        parsed = fin.parse_statement_text(s, statement=statement, columns=columns, page=page)
        if parsed["lines"]:
            values = {ln["column_period_end"]: ln["value"] for ln in parsed["lines"]}
            label = parsed["lines"][0]["raw_label"]
            out.append({"kind": "item", "label": label, "values": values, "text": s, "page": page})
            continue
        toks = s.split()
        is_year_row = all(t.isdigit() and len(t) == 4 for t in toks)  # column headers, not figures
        if toks and not is_year_row and all(fin._NUM.match(t) or t.casefold() in fin._BLANK for t in toks):
            vals = [fin.parse_number(t) for t in toks]
            if len(vals) == len(columns):
                out.append({"kind": "figures", "values": dict(zip(columns, vals, strict=True)), "text": s,
                            "page": page})
                continue
        out.append({"kind": "text", "text": s, "page": page})
    return out


def _sum_ok(total: dict, parts: list[dict], columns: list[str]) -> bool:
    """Exact block sum. A dash ('-') is a nil presentation: it counts as zero inside this arithmetic check
    only. Stored values are never changed, so a dash is still stored as not reported."""
    for c in columns:
        if total.get(c) is None:
            return False
        vals = [0.0 if p.get(c) is None else p[c] for p in parts]
        if abs(sum(vals) - total[c]) > 0.5:  # figures are in whole thousands; exact match required
            return False
    return True


def analyse(lines: list[str], *, statement: str, columns: list[str], page: int) -> list[dict]:
    """Return one record per figures-only row: {text, values, page, status, rule, code, covers}."""
    els = _elements(lines, statement=statement, columns=columns, page=page)
    # contributors are labelled items and recognised subtotals; each is a dict of column -> value
    results: list[dict] = []
    contributor: dict[int, dict] = {}  # element index -> values used as a contributor
    for i, e in enumerate(els):
        if e["kind"] == "item":
            contributor[i] = e["values"]
    for i, e in enumerate(els):
        if e["kind"] != "figures":
            continue
        # candidate runs: suffixes of contributors above this row, stopping at a heading
        idx = []
        j = i - 1
        while j >= 0 and els[j]["kind"] != "heading":
            if j in contributor:
                idx.insert(0, j)
            j -= 1
        matches = []
        for start in range(len(idx)):
            run = idx[start:]
            if _sum_ok(e["values"], [contributor[k] for k in run], columns):
                matches.append(run)
        if not matches and statement == "CF":
            # R8: the cash-flow block that begins with profit before income tax and runs through the
            # 'Adjustments for:' items, closed by this row. Recognised only by this exact structure.
            pbt = next((k for k, x in enumerate(els) if x["kind"] == "item"
                        and x["label"].casefold().startswith("profit before income tax")), None)
            adj = next((k for k, x in enumerate(els) if x["kind"] == "text"
                        and x["text"].casefold().startswith("adjustments for")), None)
            if pbt is not None and adj is not None and pbt < adj < i:
                run = [pbt] + [k for k in range(adj + 1, i) if els[k]["kind"] == "item"]
                if _sum_ok(e["values"], [contributor[k] for k in run], columns):
                    matches.append(run)
        rec = {"text": e["text"], "values": e["values"], "page": page, "index": i}
        if len(matches) == 1:
            run = matches[0]
            pbt_idx = next((k for k, x in enumerate(els) if x["kind"] == "item"
                            and x["label"].casefold().startswith("profit before income tax")), None)
            adj_idx = next((k for k, x in enumerate(els) if x["kind"] == "text"
                            and x["text"].casefold().startswith("adjustments for")), None)
            starts_at_pbt = statement == "CF" and pbt_idx is not None and run[0] == pbt_idx
            through_adjustments = adj_idx is not None and pbt_idx is not None and pbt_idx < adj_idx < i
            rule = "R8_cf_adjustments_block" if starts_at_pbt and through_adjustments else "R1_block_sum"
            rec.update(status="recognised", rule=rule, covers=matches[0], code=None,
                       rule_version=RULE_VERSION,
                       nil_items=sum(1 for k in matches[0] if any(
                           contributor[k].get(c) is None for c in columns)))
            contributor[i] = e["values"]
        else:
            rec.update(status="unresolved", rule=None, covers=[], code=None, rule_version=None,
                       reason="no unique block sum" if not matches else "ambiguous block sum")
        results.append(rec)
    _assign_positions(els, results, statement=statement, columns=columns)
    for r in results:  # every recognised row carries the version of the rule that recognised it
        if r["status"] == "recognised":
            r["rule_version"] = RULE_VERSION
    return results


def _assign_positions(els: list[dict], results: list[dict], *, statement: str, columns: list[str]) -> None:
    """R2 to R5: canonical meaning, or an unnamed structural total, only from fixed structural positions."""
    by_index = {r["index"]: r for r in results}
    n = len(els)

    def closing(lo: int, hi: int) -> dict | None:
        """The last recognised subtotal strictly between element indexes lo and hi."""
        found = [r for k, r in by_index.items() if lo < k < hi and r["status"] == "recognised"]
        return max(found, key=lambda r: r["index"]) if found else None

    def set_unresolved_match(target: dict, parts: list[dict], rule: str, code: str | None) -> bool:
        """A row equal, in every column, to the sum of the given closing subtotals is recognised by rule."""
        if not parts or not _sum_ok(target["values"], [p["values"] for p in parts], columns):
            return False
        target.update(status="recognised", rule=rule, code=code, covers=[p["index"] for p in parts],
                      reason=None)
        return True

    heads = {e["label"]: i for i, e in enumerate(els) if e["kind"] == "heading"}
    if statement == "BS":
        eq = heads.get("SHARE CAPITAL AND RESERVES")
        c_eq = None
        if eq is not None:
            nxt = min((i for i in heads.values() if i > eq), default=n)
            c_eq = closing(eq, nxt)  # the equity block closes before the next heading
            if c_eq is not None:
                c_eq["code"], c_eq["rule"] = "total_equity", "R2_equity_block"
        nca, ca = heads.get("NON CURRENT ASSETS"), heads.get("CURRENT ASSETS")
        tl_idx = next((k for k, e in enumerate(els) if e["kind"] == "item" and
                       e["label"].casefold() == "total liabilities"), None)
        cl = heads.get("CURRENT LIABILITIES")
        if cl is not None and tl_idx is not None and tl_idx > cl:
            c_cl = closing(cl, tl_idx)  # the current liabilities block closes before the total row
            if c_cl is not None:
                c_cl["code"], c_cl["rule"] = "current_liabilities", "R6_current_liabilities_block"
        if nca is not None and ca is not None and ca > nca:
            c_nca, c_ca = closing(nca, ca), closing(ca, n)
            if c_ca is not None:  # computed before the grand total is recognised, so it is the block close
                c_ca["code"], c_ca["rule"] = "current_assets", "R7_current_assets_block"
            for r in results:
                if r["status"] == "unresolved" and r["index"] > ca and c_nca and c_ca:
                    set_unresolved_match(r, [c_nca, c_ca], "R3_assets_total", "total_assets")
        # R5: the closing liabilities-and-equity row, after the last liabilities heading
        tl = next((k for k, e in enumerate(els) if e["kind"] == "item" and
                   e["label"].casefold() == "total liabilities"), None)
        if tl is not None and c_eq is not None:
            for r in results:
                if r["status"] == "unresolved" and r["index"] > tl:
                    tl_rec = {"index": tl, "values": els[tl]["values"]}
                    set_unresolved_match(r, [c_eq, tl_rec], "R5_equity_plus_liabilities", None)
    if statement == "IS":
        rev = next((k for k, e in enumerate(els) if e["kind"] == "item"
                    and e["label"].casefold().startswith("revenue")), None)
        gp = next((k for k, e in enumerate(els) if e["kind"] == "item"
                   and e["label"].casefold() == "gross profit"), None)
        if rev is not None and gp is not None and gp > rev:
            # the figures row directly above the gross profit row, if it is a recognised block sum
            above = [r for r in results if r["status"] == "recognised" and r["index"] < gp and
                     r["index"] > rev and all(k > rev for k in r["covers"])]
            if above:
                r = max(above, key=lambda x: x["index"])
                if r["index"] == max(k for k in range(rev + 1, gp) if els[k]["kind"] in ("item", "figures")):
                    r["code"], r["rule"] = "cost_of_sales", "R4_cost_block"
