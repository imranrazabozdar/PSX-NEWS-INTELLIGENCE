"""Turn one source item into validated, evidence-checked event candidates.

Flow: relevance pre-filter (deterministic) -> LLM interpretation via the gateway -> strict
schema validation -> quote verification against the item text -> number checks -> entity
resolution against the company master -> deterministic importance and confidence with
explanations -> human-review flags. Anything the text does not support is removed and flagged.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from engines import schema
from engines.llm import LLMGateway, Prompt, load_prompt

PROVENANCE_FIELDS = ("provider", "source_id", "original_source", "original_url", "retrieval_method",
                     "published_at_utc", "published_at_raw", "published_tz_offset",
                     "publication_time_status", "collected_at_utc", "access_status",
                     "licence_status", "data_status")

RELEVANCE_TERMS = frozenset(
    "pakistan pakistani psx kse karachi lahore islamabad sbp secp ogra nepra ecc imf rupee pkr budget "
    "tariff policy rate inflation cpi oil lng gas petrol diesel crude brent opec cement fertiliser "
    "fertilizer urea bank refinery power electricity circular debt dividend profit earnings eps "
    "remittances exports imports reserves fbr tax sukuk t-bill pib".split())

TIER_WEIGHT = {"primary_official": 1.0, "established_media": 0.75, "specialist": 0.65,
               "commentary": 0.4, "unrated": 0.3}
CLAIM_WEIGHT = {"verified_fact": 1.0, "official_statement": 0.95, "news_report": 0.7,
                "analyst_interpretation": 0.5, "prediction": 0.35, "personal_opinion": 0.3,
                "rumour": 0.15, "advertisement": 0.0, "model_inference": 0.2, "unclear": 0.2}
STAGE_WEIGHT = {"rumour": 0.3, "discussion": 0.5, "proposal": 0.6, "consultation": 0.6,
                "committee_recommendation": 0.7, "approval": 0.9, "notification": 1.0,
                "implementation": 1.0, "amendment": 0.9, "delay": 0.8, "suspension": 0.9,
                "reversal": 0.9, "confirmed_fact": 1.0, "not_applicable": 0.6}
MAGNITUDE_WEIGHT = {"low": 0.3, "medium": 0.6, "high": 1.0, "unknown": 0.4}
HIGH_IMPACT_TYPES = frozenset({"monetary_policy", "fiscal_policy", "tax_policy", "energy_policy",
                               "imf_program", "geopolitical", "security_incident", "regulatory_action",
                               "credit_rating", "commodity_supply"})
REVIEW_CONFIDENCE = 0.55
_NUM = re.compile(r"-?\d+(?:[.,]\d+)*")


def normalise_for_match(text: str) -> str:
    text = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"')
    return re.sub(r"\s+", " ", text.replace("”", '"')).strip().casefold()


def relevance(title: str, text: str) -> tuple[float, str]:
    words = set(re.findall(r"[a-z][a-z\-]+", f"{title} {text}".lower()))
    hits = sorted(words & RELEVANCE_TERMS)
    score = min(1.0, len(hits) / 4)
    return score, ("matched: " + ", ".join(hits[:8])) if hits else "no Pakistan-economy terms"


@dataclass
class Candidate:
    event: dict
    companies: list[dict]
    importance: float
    importance_explanation: list[str]
    confidence: float
    confidence_explanation: list[str]
    review_reasons: list[str]


@dataclass
class ExtractionResult:
    source_item_id: int
    status: str  # extracted | not_relevant | skipped_prefilter | invalid_output | llm_unavailable
    candidates: list[Candidate] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)
    raw: dict | None = None
    call_id: int | None = None
    model: str = ""
    prompt: Prompt | None = None
    provenance: dict = field(default_factory=dict)

    @property
    def needs_human_review(self) -> bool:
        return bool(self.review_reasons or any(c.review_reasons for c in self.candidates))


def _quote_ok(quote: str, haystack: str) -> bool:
    q = normalise_for_match(quote)
    return len(q) >= 3 and q in haystack


def _numbers_ok(value: float | None, quote: str) -> bool:
    if value is None:
        return True
    found = {float(n.replace(",", "")) for n in _NUM.findall(quote)}
    return any(abs(f - value) < 1e-9 for f in found)


def importance(event: dict, tier: str, n_companies: int) -> tuple[float, list[str]]:
    mag = MAGNITUDE_WEIGHT[event["magnitude"]]
    typ = 1.0 if event["event_type"] in HIGH_IMPACT_TYPES else 0.6
    stage = STAGE_WEIGHT[event["status_stage"]]
    breadth = min(1.0, 0.4 + 0.2 * n_companies) if n_companies else 0.4
    score = round(0.35 * mag + 0.25 * typ + 0.25 * stage + 0.15 * breadth, 3)
    why = [f"magnitude={event['magnitude']} ({mag})",
           f"event_type={event['event_type']} ({'high-impact' if typ == 1.0 else 'standard'})",
           f"stage={event['status_stage']} ({stage})", f"companies_linked={n_companies}"]
    return score, why


def confidence(event: dict, tier: str, kept: int, dropped: int) -> tuple[float, list[str]]:
    claims = event["claims"]
    claim_w = sum(CLAIM_WEIGHT[c["claim_type"]] for c in claims) / len(claims) if claims else 0.2
    tier_w = TIER_WEIGHT.get(tier, 0.3)
    support = kept / (kept + dropped) if kept + dropped else 0.0
    stage = STAGE_WEIGHT[event["status_stage"]]
    score = round(0.35 * tier_w + 0.30 * claim_w + 0.20 * support + 0.15 * stage, 3)
    why = [f"source tier {tier} ({tier_w})", f"mean claim strength {claim_w:.2f}",
           f"{kept} quoted item(s) verified, {dropped} unsupported removed",
           f"stage {event['status_stage']} ({stage})",
           "single source; corroboration is assessed across the story cluster"]
    return score, why


def extract(item: dict, gateway: LLMGateway, *,
            resolve_company: Callable[[str], list[dict]] | None = None,
            prompt: Prompt | None = None) -> ExtractionResult:
    """Extract events from one item. ``item`` needs source_item_id, title, text, reliability_tier
    and the provenance fields; text must be content we are permitted to process."""
    prompt = prompt or load_prompt("event_extraction_v1")
    prov = {k: item.get(k) for k in PROVENANCE_FIELDS}
    res = ExtractionResult(item["source_item_id"], "extracted", prompt=prompt, provenance=prov)
    if item.get("access_status") in ("restricted", "unavailable"):
        res.status = "skipped_prefilter"
        res.review_reasons.append("source access is restricted; not processed")
        return res
    score, why = relevance(item.get("title", ""), item.get("text", ""))
    if score == 0:
        res.status = "skipped_prefilter"
        return res

    body = f"<item>\nTITLE: {item.get('title', '')}\nTEXT: {item.get('text', '')}\n</item>"
    out = gateway.complete(prompt, body, schema.json_schema())
    res.call_id, res.model = out.call_id, out.model
    if out.text is None:
        res.status = "llm_unavailable"
        res.review_reasons.append(f"llm {out.outcome}: {out.error}")
        return res
    try:
        payload = schema.validate_extraction(json.loads(out.text))
    except (json.JSONDecodeError, schema.SchemaError) as exc:
        res.status = "invalid_output"
        res.review_reasons.append(f"schema validation failed: {exc}")
        return res
    res.raw = payload
    if not payload["is_relevant"]:
        res.status = "not_relevant"
        return res

    haystack = normalise_for_match(f"{item.get('title', '')}\n{item.get('text', '')}")
    tier = item.get("reliability_tier", "unrated")
    for ev in payload["events"]:
        reasons: list[str] = []
        kept = dropped = 0
        clean = dict(ev)
        for key in ("entities", "indicators", "claims"):
            good = []
            for entry in ev[key]:
                ok = _quote_ok(entry["quote"], haystack)
                if ok and key == "indicators" and not _numbers_ok(entry["value"], entry["quote"]):
                    ok = False
                    reasons.append(f"indicator '{entry['name']}' value not present in its quote")
                if ok:
                    good.append(entry)
                    kept += 1
                else:
                    dropped += 1
            clean[key] = good
        if dropped:
            reasons.append(f"{dropped} unsupported entity/indicator/claim removed")
        if not clean["claims"]:
            reasons.append("no claim is supported by a verbatim quote")
        companies = []
        for ent in clean["entities"]:
            if ent["entity_type"] != "company":
                continue
            matches = resolve_company(ent["name"]) if resolve_company else []
            if len(matches) == 1:
                companies.append({**matches[0], "mention": ent["name"], "quote": ent["quote"]})
            else:
                reasons.append(f"company '{ent['name']}' {'ambiguous' if matches else 'not in master'}")
        imp, imp_why = importance(clean, tier, len(companies))
        conf, conf_why = confidence(clean, tier, kept, dropped)
        if conf < REVIEW_CONFIDENCE:
            reasons.append(f"confidence {conf} below {REVIEW_CONFIDENCE}")
        if clean["status_stage"] == "rumour" or any(c["claim_type"] == "rumour" for c in clean["claims"]):
            reasons.append("rumour: must not be treated as fact")
        if imp >= 0.75 and tier != "primary_official":
            reasons.append("high importance from a non-primary source; confirm with a primary source")
        if clean["uncertainties"]:
            reasons.append("model recorded uncertainties")
        res.candidates.append(Candidate(clean, companies, imp, imp_why, conf, conf_why, reasons))
    return res
