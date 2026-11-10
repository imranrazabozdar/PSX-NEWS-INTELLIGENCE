"""Reproducible extraction-quality evaluation on SYNTHETIC labelled cases.

Deterministic, with no model calls.

Ported functionality from the technical engine's evaluation (PR #66, owner-approved exception in ADR-0001),
re-implemented on this project's own modules: entity resolution (engines/entity_resolution.py), near-duplicate
detection (engines/similarity.py), quote normalisation (engines/extraction.py) and the relevance pre-filter
(engines/relevance_prefilter.py).

Measures: quote grounding, company/entity matching, invented-ticker prevention, sector/commodity exposure
matches, event usefulness, exact and near-duplicate detection, and precision, recall and false positives.

Rules: a precision or recall with no denominator is reported as None, never as zero. Expectations are
hand-labelled and live in the sample file; the resolver's output is never used to label itself.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from itertools import combinations
from typing import Any

from engines.extraction import normalise_for_match
from engines.relevance_prefilter import company_phrase, normalise
from engines.similarity import Doc, similarity

_TICKER_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Z][A-Z0-9]{1,15})(?![A-Za-z0-9])")

VERSION = "eval-news/1"


def _canon(text: str | None) -> str:
    """Normalise for name matching: '&' and 'and' are the same word in company names."""
    return re.sub(r"\s+", " ", re.sub(r"\band\b", " ", normalise(text))).strip()


def direct_companies_in_text(db: Any, text: str) -> set[str]:
    """Current PSX tickers of companies named directly in text: an uppercase whole-word ticker, or the
    whole legal-name phrase of a listed company (legal suffixes removed, as in the relevance pre-filter)."""
    tickers = {r["value"] for r in db.execute(
        "SELECT value FROM company_identifiers WHERE id_type = 'psx_ticker' AND valid_to IS NULL")}
    found = {t for t in _TICKER_TOKEN.findall(text or "") if t in tickers}
    low = _canon(text)
    for row in db.execute(
            "SELECT c.legal_name AS name, i.value AS ticker FROM companies c "
            "JOIN company_identifiers i ON i.company_id = c.company_id "
            "AND i.id_type = 'psx_ticker' AND i.valid_to IS NULL WHERE c.listing_status = 'listed'"):
        phrase = _canon(company_phrase(row["name"]))
        if phrase and re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", low):
            found.add(row["ticker"])
    return found


def pr(tp: int, fp: int, fn: int) -> dict[str, Any]:
    """Precision and recall from counts. Undefined ratios are None, never 0."""
    precision = round(tp / (tp + fp), 3) if tp + fp else None
    recall = round(tp / (tp + fn), 3) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}


def quote_grounding(quotes: Iterable[str], source_text: str) -> dict[str, Any]:
    """A quote is grounded when its normalised text appears verbatim in the source."""
    source = normalise_for_match(source_text)
    quotes = [q for q in quotes if q and q.strip()]
    grounded = sum(1 for q in quotes if normalise_for_match(q) in source)
    return {"quotes": len(quotes), "grounded": grounded,
            "ungrounded": len(quotes) - grounded,
            "rate": round(grounded / len(quotes), 3) if quotes else None}


def invented_tickers(claimed: Iterable[str], known: set[str]) -> list[str]:
    """Tickers a record claims that are not in the company master. Each one is a safety failure."""
    return sorted({t.upper() for t in claimed} - {k.upper() for k in known})


def dedup_eval(docs: list[Doc], expected_pairs: set[frozenset]) -> dict[str, Any]:
    """Pairwise near-duplicate detection against hand-labelled duplicate pairs."""
    predicted: set[frozenset] = set()
    for a, b in combinations(docs, 2):
        _score, near = similarity(a, b)
        if near:
            predicted.add(frozenset({a.item_id, b.item_id}))
    tp = len(predicted & expected_pairs)
    return {**pr(tp, len(predicted - expected_pairs), len(expected_pairs - predicted)),
            "false_positive_pairs": sorted(sorted(p) for p in predicted - expected_pairs),
            "missed_pairs": sorted(sorted(p) for p in expected_pairs - predicted)}


def entity_eval(cases: list[dict[str, Any]], resolve_direct: Callable[[str], set[str]],
                known: set[str]) -> dict[str, Any]:
    """Direct company matches against hand-labelled tickers.

    resolve_direct(text) returns the tickers found in text."""
    tp = fp = fn = 0
    invented: list[str] = []
    disagreements: list[dict[str, Any]] = []
    for case in cases:
        got = {t.upper() for t in resolve_direct(case["text"])}
        want = {t.upper() for t in case["direct"]}
        tp += len(got & want)
        fp += len(got - want)
        fn += len(want - got)
        invented += invented_tickers(got, known)
        if got != want:
            disagreements.append({"text": case["text"], "expected": sorted(want), "got": sorted(got)})
    return {**pr(tp, fp, fn), "cases": len(cases),
            "invented_tickers": sorted(set(invented)),
            "disagreements": disagreements}


def useful(record: dict[str, Any]) -> bool:
    """Useful: a grounded quote AND a direct company or sector/commodity match."""
    matched = record.get("direct_match") or record.get("sector_match")
    return bool(record.get("grounded_quotes", 0)) and bool(matched)


def usefulness_rate(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    count = sum(1 for r in records if useful(r))
    return {"records": n, "useful": count,
            "useful_rate": round(count / n, 3) if n else None,
            "definition": "grounded quote AND (direct company match OR sector/commodity match)"}


def controlled_report(db: Any, sample: dict[str, Any]) -> dict[str, Any]:
    """Every measure over one labelled sample, as one reproducible record. Read-only."""
    known = {r["value"] for r in db.execute(
        "SELECT value FROM company_identifiers WHERE id_type = 'psx_ticker' AND valid_to IS NULL")}
    docs = [Doc(item_id=i["id"], title=i["title"], text=i["text"]) for i in sample["dedup"]["items"]]
    quote_rows = [quote_grounding([q["quote"]], q["source"]) for q in sample["quotes"]]
    grounded_total = sum(r["grounded"] for r in quote_rows)
    quote_total = sum(r["quotes"] for r in quote_rows)
    return {
        "eval_version": VERSION,
        "sample_version": sample["version"],
        "entities": entity_eval(sample["entities"], lambda t: direct_companies_in_text(db, t), known),
        "dedup": dedup_eval(docs, {frozenset(p) for p in sample["dedup"]["expected_duplicate_pairs"]}),
        "quotes": {"quotes": quote_total, "grounded": grounded_total,
                   "rate": round(grounded_total / quote_total, 3) if quote_total else None},
        "usefulness": usefulness_rate(sample["usefulness"]),
        "changed_records": 0,
    }
