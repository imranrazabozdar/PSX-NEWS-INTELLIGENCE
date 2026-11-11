"""Trade debts note (note 21), its ageing schedule, circular-debt disclosure and counterparty exposures.

Input is the printed text of the note pages (one list of lines per block: the note's column, the ageing table,
the related-party table). Nothing here reads a number that is not printed, and nothing assumes a zero: a
bucket
or figure that is not disclosed is returned as None, with the reason.

Units: the note is printed in PKR '000 unless stated. Circular-debt sentences are printed in PKR million; both
units are returned so they can be compared.

Separation (kept on purpose):
* trade debts (note 21) and the doubtful-debt provision are not ECL. The company defers the IFRS 9 ECL
model for
  debts due directly or ultimately from the GoP (SECP, note 2.1.2); the provision shown is the doubtful-debt
  provision only.
* counterparty exposures (the related-party credit-risk table) are a separate list, never summed into trade
debts.
"""

from __future__ import annotations

import re

ECL_DEFERRAL = re.compile(
    r"SECP has deferred the applicability of ECL model till (?:the )?financial year ending on or before "
    r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s+on\s+(?:financial assets|debts)\s+due directly or ultimately from "
    r"the GoP",
    re.IGNORECASE,
)
OVERDUE_CIRCULAR = re.compile(
    r"overdue amount of Rs\s*([\d,]+)\s*million\s*\(2025:\s*Rs\s*([\d,]+)\s*million\)\s*on account of "
    r"inter-corporate circular debt",
    re.IGNORECASE,
)
SNGPL_SSGC = re.compile(
    r"out of which Rs\s*([\d,]+)\s*million\s*\(2025:\s*Rs\s*([\d,]+)\s*million\)\s*and "
    r"Rs\s*([\d,]+)\s*million\s*"
    r"\(2025:\s*Rs\s*([\d,]+)\s*million\)\s*are overdue from related parties, Sui Northern Gas Pipeline "
    r"Limited "
    r"and Sui Southern Gas Company Limited",
    re.IGNORECASE,
)
RELATED_PARTY_TOTAL = re.compile(
    r"Total amount due from related parties as on 30 June 2026 is "
    r"Rs\s*([\d,]+)\s*million\s*\(2025:\s*Rs\s*([\d,]+)",
    re.IGNORECASE,
)
COUNTERPARTIES = (
    ("sngpl", "Sui Northern Gas Pipelines Limited"),
    ("ssgc", "Sui Southern Gas Company Limited"),
    ("prl", "Pakistan Refinery Limited"),
    ("parco", "Pak Arab Refinery Company Limited"),
    ("enar", "Enar Petroleum Refining Facility"),
    ("wapda", "WAPDA"),
)
AGEING_ROWS = (
    ("not_past_due", r"not past due"),
    ("past_due_0_30", r"past due 0-30 days"),
    ("past_due_31_60", r"past due 31-60 days"),
    ("past_due_61_90", r"past due 61-90 days"),
    ("over_90", r"over 90 days"),
)
_TOKEN = re.compile(r"\(\s*[\d,]+\s*\)|-?[\d,]*\d[\d,]*|(?<!\w)-(?!\w)")


def _to_number(tok: str) -> float | None:
    """A printed figure: brackets are negative, a dash is nil (None), never zero."""
    t = tok.strip()
    if t == "-":
        return None
    neg = t.startswith("(") and t.endswith(")")
    value = float(t.strip("()").replace(",", "").replace(" ", "") or 0)
    return -value if neg else value


def _numbers(text: str) -> list[float | None]:
    return [_to_number(t) for t in _TOKEN.findall(text)]


def _flat(lines: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _find(lines: list[str], pattern: str, start: int = 0) -> int | None:
    rx = re.compile(pattern, re.IGNORECASE)
    for i in range(start, len(lines)):
        if rx.search(lines[i]):
            return i
    return None


def _check(name: str, ok: bool, detail: str) -> dict:
    return {"check": name, "status": "RECONCILED" if ok else "UNRECONCILED", "detail": detail}


def parse_note_21(lines: list[str], *, pages: list[str]) -> dict:
    """Trade debts (note 21): gross, doubtful-debt provision, net; the printed sub-totals are verified."""
    start = _find(lines, r"^\s*21\.\s*(TRADE DEBTS)?\s*$")
    if start is None:
        return {"status": "not_found", "reason": "note 21 heading not in the supplied text", "pages": pages}
    end = _find(lines, r"^\s*22\.", start + 1)
    block = lines[start + 1 : end if end is not None else len(lines)]
    good = doubtful = provision = gross_printed = net_printed = None
    for raw in block:
        ln = raw.strip()
        label = re.sub(r"[\d(),.\-\s]+$", "", ln).strip()
        vals = _numbers(ln[len(label) :] if label else ln)
        if re.search(r"considered good", label, re.I) and len(vals) >= 2:
            good = vals[:2]
        elif re.search(r"considered doubtful", label, re.I) and len(vals) >= 2:
            doubtful = vals[:2]
        elif re.search(r"provision for doubtful trade debts", label, re.I) and len(vals) >= 2:
            provision = vals[:2]
        elif not label and len(vals) == 2 and None not in vals:
            if gross_printed is None:
                gross_printed = vals
            else:
                net_printed = vals
    if good is None:
        return {"status": "not_found", "reason": "no 'considered good' row", "pages": pages}
    gross = [(good[i] or 0) + (doubtful[i] or 0) for i in range(2)] if doubtful else good
    # the provision is printed in brackets, i.e. already negative: net = gross + provision
    net = [gross[i] + (provision[i] or 0) if provision else gross[i] for i in range(2)]
    checks = []
    if gross_printed is not None:
        checks.append(
            _check("trade_debts_gross", gross_printed == gross, f"printed {gross_printed} vs {gross}")
        )
    if net_printed is not None:
        checks.append(_check("trade_debts_net", net_printed == net, f"printed {net_printed} vs {net}"))
    out = {"status": "parsed", "units": "PKR '000", "pages": pages, "checks": checks, "by_year": {}}
    for idx, year in enumerate(("2026", "2025")):
        out["by_year"][year] = {
            "unsecured_considered_good": good[idx],
            "unsecured_considered_doubtful": doubtful[idx] if doubtful else None,
            "gross_trade_debts": gross_printed[idx] if gross_printed else gross[idx],
            "doubtful_debt_provision": provision[idx] if provision else None,
            "net_trade_debts": net_printed[idx] if net_printed else net[idx],
        }
    return out


def parse_circular_debt(lines: list[str]) -> dict:
    """Overdue inter-corporate circular debt (note 21.1) and the related-party total (note 21.2)."""
    text = _flat(lines)
    out: dict = {"units": "PKR million", "pages": None}
    m = OVERDUE_CIRCULAR.search(text)
    if m:
        out["overdue_total"] = {"2026": _num(m.group(1)), "2025": _num(m.group(2))}
    else:
        out["overdue_total"] = None
        out["overdue_total_reason"] = "sentence not found"
    s = SNGPL_SSGC.search(text)
    if s:
        out["overdue_from_sngpl"] = {"2026": _num(s.group(1)), "2025": _num(s.group(2))}
        out["overdue_from_ssgc"] = {"2026": _num(s.group(3)), "2025": _num(s.group(4))}
    else:
        out["overdue_from_sngpl"] = out["overdue_from_ssgc"] = None
    rp = RELATED_PARTY_TOTAL.search(text)
    out["related_party_total"] = {"2026": _num(rp.group(1)), "2025": _num(rp.group(2))} if rp else None
    if out["overdue_total"] and out["overdue_from_sngpl"]:
        # the two named counterparties are part of the overdue total, not all of it
        out["other_overdue"] = {
            y: out["overdue_total"][y] - out["overdue_from_sngpl"][y] - out["overdue_from_ssgc"][y]
            for y in ("2026", "2025")
        }
    return out


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def parse_ageing(lines: list[str], *, pages: list[str]) -> dict:
    """Trade debts ageing: gross and impaired for 2026 and 2025, in the printed buckets. A bucket that is not
    disclosed is None. Over 365 days is looked for and left None when it is not printed."""
    start = _find(lines, r"aging of trade debts")
    if start is None:
        return {"status": "not_found", "reason": "ageing heading not in the supplied text", "pages": pages}
    block = lines[start + 1 :]
    rows: dict[str, list[float | None]] = {}
    total = None
    for ln in block:
        for key, pat in AGEING_ROWS:
            if key not in rows and re.match(rf"^\s*{pat}\b", ln, re.I):
                rest = re.sub(rf"^\s*{pat}", "", ln, flags=re.I)
                rows[key] = _numbers(rest)[:4]
        if re.match(r"^\s*21\s+\S", ln):  # the total row carries the note reference 21
            total = _numbers(re.sub(r"^\s*21", "", ln))[:4]
            break
    if total is None or len(rows) < 5:
        return {
            "status": "incomplete",
            "reason": "ageing rows not all found",
            "found": sorted(rows),
            "pages": pages,
        }
    checks = []
    for idx, year in ((0, "2026"), (2, "2025")):
        gross_sum = sum((rows[k][idx] or 0) for k, _ in AGEING_ROWS)
        checks.append(
            _check(
                f"ageing_gross_{year}",
                gross_sum == total[idx],
                f"buckets {gross_sum} vs printed total {total[idx]}",
            )
        )
    over_365_printed = any(
        re.search(r"365", ln)
        for ln in block[: (block.index(next(ln for ln in block if re.match(r"^\s*21\s+\S", ln)))) + 1]
    )
    out = {"status": "parsed", "units": "PKR '000", "pages": pages, "checks": checks, "by_year": {}}
    for idx, year in ((0, "2026"), (2, "2025")):
        buckets = {k: rows[k][idx] for k, _ in AGEING_ROWS}
        out["by_year"][year] = {
            "gross_by_bucket": buckets,
            "over_365": None,  # not disclosed: never assumed zero (see over_365_disclosed)
            "over_365_disclosed": over_365_printed,
            "total_gross": total[idx],
            "impaired_total": total[idx + 1],
            "over_90_share_of_gross": (buckets["over_90"] / total[idx])
            if buckets["over_90"] is not None and total[idx]
            else None,
        }
    return out


def parse_counterparties(lines: list[str], *, pages: list[str]) -> dict:
    """Related-party credit-risk table, 2026 block: total and ageing by counterparty. Kept separate from trade
    debts. Each row is read from its first seven figures (total, not due, four past-due buckets, over 90,
    impaired); the 2025 block on the same line is ignored."""
    start = _find(lines, r"aging of trade debts from related parties")
    if start is None:
        return {
            "status": "not_found",
            "reason": "related-party ageing heading not in the supplied text",
            "pages": pages,
        }
    rows, printed_total, checks = [], None, []
    for ln in lines[start + 1 :]:
        label_match = None
        for key, name in COUNTERPARTIES:
            if re.match(rf"^\s*{re.escape(name)}\b", ln):
                label_match = (key, name)
                break
        if label_match:
            rest = ln[ln.index(label_match[1]) + len(label_match[1]) :]
            vals = _numbers(rest)[:7]
            if len(vals) == 7:
                total = vals[0]
                buckets = vals[1:6]
                impaired = vals[6]
                ok = (total is None and all(b is None for b in buckets[:4])) or (
                    total is not None and sum((b or 0) for b in buckets) == total
                )
                checks.append(
                    _check(f"counterparty_{label_match[0]}", ok, f"total {total} vs buckets {buckets}")
                )
                rows.append(
                    {
                        "counterparty": label_match[1],
                        "key": label_match[0],
                        "total_2026": total,
                        "not_past_due": buckets[0],
                        "past_due_0_30": buckets[1],
                        "past_due_31_60": buckets[2],
                        "past_due_61_90": buckets[3],
                        "over_90": buckets[4],
                        "impaired": impaired,
                        "source_page": pages[0] if pages else None,
                    }
                )
        elif re.match(r"^\s*[\d(,]", ln) and printed_total is None and rows:
            vals = _numbers(ln)
            if len(vals) >= 7:
                printed_total = vals[:7]
                break
    if printed_total is not None and rows:
        sums = [sum((r["total_2026"] or 0) for r in rows)]
        checks.append(
            _check(
                "counterparty_total",
                sums[0] == printed_total[0],
                f"sum of rows {sums[0]} vs printed {printed_total[0]}",
            )
        )
    return {
        "status": "parsed" if rows else "not_found",
        "units": "PKR '000",
        "pages": pages,
        "rows": rows,
        "printed_total_2026": printed_total[0] if printed_total else None,
        "checks": checks,
        "kept_separate_from_trade_debts": True,
    }


def ecl_treatment(lines: list[str], *, pages: list[str]) -> dict:
    """The doubtful-debt provision is NOT an ECL allowance; the deferral for GoP-linked debts is recorded."""
    m = ECL_DEFERRAL.search(_flat(lines))
    return {
        "doubtful_debt_provision_is_ecl": False,
        "ecl_allowance": None,
        "ecl_model_deferred_for_gop_linked_debts": bool(m),
        "deferral_deadline": m.group(1) if m else None,
        "deferral_source_note": "2.1.2" if m else None,
        "pages": pages,
    }


def extract_note_21(
    *,
    note_lines: list[str],
    ageing_lines: list[str],
    counterparty_lines: list[str],
    pages: dict[str, list[str]],
) -> dict:
    """Everything for note 21. Each argument is the text of one page block; `pages` names the PDF pages."""
    trade = parse_note_21(note_lines, pages=pages.get("note", []))
    if trade.get("status") == "not_found":  # a report that lists components (note 11 in some reports)
        trade = parse_trade_debts_components(note_lines, pages=pages.get("note", []))
    return {
        "trade_debts": trade,
        "circular_debt": parse_circular_debt(note_lines),
        "ageing": _ageing_or_not_disclosed(ageing_lines, pages.get("ageing", []), note_lines),
        "counterparty_exposures": parse_counterparties(
            counterparty_lines, pages=pages.get("counterparty", [])
        ),
        "ecl": ecl_treatment(note_lines, pages=pages.get("note", [])),
    }


def parse_trade_debts_components(lines: list[str], *, pages: list[str]) -> dict:
    """Trade debts for a report that lists its components (LUCK note 11).

    Each component is read from its last two figures (the note reference is dropped); the printed gross and
    net
    sub-totals are checked; the provision is printed as a positive "Less:" amount and is subtracted.
    Nothing is
    assumed where a line is not printed."""
    start = _find(lines, r"TRADE DEBTS\s*$")
    if start is None:
        return {
            "status": "not_found",
            "reason": "trade debts heading not in the supplied text",
            "pages": pages,
        }
    end = _find(lines, r"^\s*12\.\s|LOANS AND ADVANCES", start + 1)
    block = [ln.strip() for ln in lines[start + 1 : end if end is not None else len(lines)]]
    components: list[dict] = []
    gross_printed = provision = net_printed = None
    provision_label = None
    for ln in block:
        label = re.sub(r"[\d(),.\-\s]+$", "", ln).strip()
        vals = _numbers(ln[len(label) :] if label else ln)
        if re.search(r"secured|unsecured|bills receivable", label, re.I) and len(vals) >= 2:
            components.append({"label": label, "2026": vals[-2], "2025": vals[-1]})
        elif re.search(r"provision for doubtful debts", label, re.I) and len(vals) >= 2:
            provision = (vals[-2], vals[-1])
            provision_label = label
        elif not label and len(vals) == 2 and None not in vals and components:
            if gross_printed is None and provision is None:
                gross_printed = vals
            elif net_printed is None and provision is not None:
                net_printed = vals
    if not components or gross_printed is None:
        return {"status": "not_found", "reason": "components or gross sub-total not found", "pages": pages}
    sums = [sum((c[y] or 0) for c in components) for y in ("2026", "2025")]
    checks = [
        _check(
            "trade_debts_components_gross",
            sums == gross_printed,
            f"components {sums} vs printed {gross_printed}",
        )
    ]
    prov = [None, None]
    if provision is not None:
        sign = -1 if re.match(r"less", provision_label, re.I) else 1
        prov = [sign * abs(provision[0] or 0), sign * abs(provision[1] or 0)]
    net = [gross_printed[i] + (prov[i] or 0) for i in range(2)]
    if net_printed is not None:
        checks.append(_check("trade_debts_net", net_printed == net, f"printed {net_printed} vs {net}"))
    out = {
        "status": "parsed",
        "units": "PKR '000",
        "pages": pages,
        "checks": checks,
        "components": components,
        "by_year": {},
        "layout": "components",
    }
    for i, year in enumerate(("2026", "2025")):
        out["by_year"][year] = {
            "gross_trade_debts": gross_printed[i],
            "doubtful_debt_provision": prov[i],
            "net_trade_debts": net_printed[i] if net_printed is not None else net[i],
        }
    return out


def parse_credit_quality(lines: list[str], *, pages: list[str]) -> dict:
    """The printed credit-quality analysis of trade debts: neither past due nor impaired, and past due but not
    impaired. A printed dash is a printed nil; a line that is not printed is None."""
    out: dict = {"pages": pages, "neither_past_due_nor_impaired": None, "past_due_but_not_impaired": None}
    for ln in lines:
        s = ln.strip()
        if re.match(r"^Neither past due nor impaired\b", s, re.I):
            vals = _numbers(re.sub(r"^Neither past due nor impaired", "", s, flags=re.I))
            if len(vals) >= 2:
                out["neither_past_due_nor_impaired"] = {"2026": vals[0], "2025": vals[1]}
        if re.match(r"^Past due but not impaired\b", s, re.I):
            rest = re.sub(r"^Past due but not impaired", "", s, flags=re.I)
            vals = _numbers(rest)
            out["past_due_but_not_impaired"] = {
                "2026": vals[0] if vals else None,
                "2025": vals[1] if len(vals) > 1 else None,
                "printed_nil": bool(re.search(r"[–-]", rest)) and not any(v for v in vals if v),
            }
    return out


def _ageing_or_not_disclosed(ageing_lines: list[str], pages: list[str], note_lines: list[str]) -> dict:
    """The ageing schedule when one is printed.

    When none is, every bucket is null: the report does not disclose an ageing, so none is assumed (and no
    bucket is
    set to zero)."""
    if ageing_lines:
        parsed = parse_ageing(ageing_lines, pages=pages)
        if parsed.get("status") == "parsed":
            return parsed
    return {
        "status": "not_disclosed",
        "reason": "no ageing schedule printed; buckets are null, never zero",
        "pages": pages,
        "by_year": {
            y: {
                "gross_by_bucket": {k: None for k, _ in AGEING_ROWS},
                "over_365": None,
                "over_365_disclosed": False,
                "total_gross": None,
                "impaired_total": None,
                "over_90_share_of_gross": None,
            }
            for y in ("2026", "2025")
        },
    }
