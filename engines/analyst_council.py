"""The three-specialist council: news, financial and macro lenses over one event, then a synthesis.

Division of labour (owner's design). The DATA ENGINE owns the facts: statement figures come from
extracted and reconciled reports, ratios are computed in Python (engines/ratios.py), news comes from
permitted sources, prices come from the separate technical system. The LLMs never supply a number. They
read an evidence pack the system built, interpret it, and say what it implies for a company.

Three lenses, deliberately. A news lens can read an oil-price rise as good for a producer while the macro
lens sees currency and rate damage and the financial lens sees the real exposure in the accounts. The
council exists to surface that disagreement rather than accept the first answer.

Conflict detection is DETERMINISTIC. Python compares the structured findings; no model is asked whether a
conflict exists, because a model that overlooks one would hide exactly the case this design is for. The
orchestrator LLM only explains a conflict the system already found, and when no model is reachable the
verdict is still produced from the findings that did arrive.

Every finding carries its role, provider, model, prompt id and version, and a UTC timestamp.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from database.canonical import now_utc
from engines import llm

ROLES = ("news", "financial", "macro")
ROLE_PROMPT = {"news": "role_news_v1", "financial": "role_financial_v1", "macro": "role_macro_v1"}
SYNTHESIS_PROMPT = "orchestrator_synthesis_v1"
DIRECTIONS = ("benefit", "suffer", "neutral", "unclear")
MAGNITUDES = ("high", "medium", "low")
TIMINGS = ("immediate", "delayed")
CONFIDENCES = ("high", "medium", "low")
# Which evidence each lens is shown. The financial lens is not given macro readings, so a conflict
# between lenses is a real difference of view and not an artefact of one lens seeing more.
ROLE_EVIDENCE = {
    "news": ("news", "announcement"),
    "financial": ("figure", "ratio", "note", "kam"),
    "macro": ("macro", "commodity", "policy", "sector_rule"),
}


class CouncilError(RuntimeError):
    """The council could not produce a verdict."""


@dataclass(frozen=True)
class Evidence:
    """One item the system verified. `id` is how a model must cite it."""

    id: str
    kind: str
    text: str
    source_name: str
    source_date: str
    company: str | None = None

    def render(self) -> str:
        who = f" company={self.company}" if self.company else ""
        return (f'<item id="{self.id}" kind="{self.kind}"{who} source="{self.source_name}" '
                f'date="{self.source_date}">{self.text}</item>')


@dataclass
class EvidencePack:
    """The event plus everything the system verified about it. Built by Python, never by a model."""

    event: str
    items: list[Evidence] = field(default_factory=list)

    @property
    def companies(self) -> tuple[str, ...]:
        return tuple(sorted({i.company for i in self.items if i.company}))

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(i.id for i in self.items)

    def for_role(self, role: str) -> str:
        kinds = ROLE_EVIDENCE[role]
        shown = [i for i in self.items if i.kind in kinds]
        if not shown:
            shown = []
        lines = "\n".join(i.render() for i in shown)
        known = ", ".join(self.companies) or "none"
        return (f"<event>{self.event}</event>\n<known_companies>{known}</known_companies>\n"
                f"<evidence>\n{lines}\n</evidence>")


@dataclass(frozen=True)
class Assessment:
    company: str
    direction: str
    magnitude: str
    timing: str
    reason: str
    evidence_ids: tuple[str, ...]
    confidence: str


@dataclass
class RoleFinding:
    """One lens's answer, with the provenance the owner requires on every model output."""

    role: str
    outcome: str
    provider: str = ""
    model: str = ""
    prompt_id: str = ""
    prompt_version: str = ""
    created_at: str = ""
    assessments: list[Assessment] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"


def provider_for_role(role: str, environ: Any = None) -> Any:
    """The role's own account first, then the other accounts, then the other vendors.

    Three roles on three free Groq accounts means no single quota carries the whole council, while a
    role whose own account is exhausted still gets an answer from another.
    """
    if role not in ROLES:
        raise ValueError(f"unknown role: {role}")
    env = os.environ if environ is None else environ
    offset = ROLES.index(role)
    chain: list[Any] = []
    for cls, model_var in ((llm.GroqProvider, llm.GROQ_MODEL_VAR),
                           (llm.GeminiProvider, llm.GEMINI_MODEL_VAR),
                           (llm.OpenRouterProvider, llm.OPENROUTER_MODEL_VAR)):
        keys = llm.keys_from_env(cls.key_var, env)
        if not keys:
            continue
        start = offset % len(keys)
        ordered = keys[start:] + keys[:start]
        model = str(env.get(model_var, "") or "").strip() or None
        built = [cls(api_key=k, model=model) for k in ordered]
        chain.append(built[0] if len(built) == 1 else llm.RotatingProvider(built))
    if not chain:
        return llm.ClaudeProvider()
    return chain[0] if len(chain) == 1 else llm.FallbackProvider(chain)


def _clean_assessments(raw: Any, pack: EvidencePack) -> tuple[list[Assessment], list[str]]:
    """Keep only assessments the evidence can carry. A model may not introduce a company or a citation."""
    kept: list[Assessment] = []
    dropped: list[str] = []
    known = set(pack.companies)
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            dropped.append("a non-object assessment")
            continue
        company = str(entry.get("company", "")).strip()
        direction = str(entry.get("direction", "")).strip().lower()
        if not company:
            dropped.append("an assessment with no company")
            continue
        if known and company not in known and not company.startswith("SECTOR:"):
            dropped.append(f"{company}: not in the evidence pack")
            continue
        if direction not in DIRECTIONS:
            dropped.append(f"{company}: direction {direction!r} is not one of {DIRECTIONS}")
            continue
        cited = tuple(str(e) for e in entry.get("evidence_ids", []) if str(e) in pack.ids)
        if not cited:
            dropped.append(f"{company}: cites no evidence id from the pack")
            continue
        kept.append(Assessment(
            company=company, direction=direction,
            magnitude=_one_of(entry.get("magnitude"), MAGNITUDES, "low"),
            timing=_one_of(entry.get("timing"), TIMINGS, "delayed"),
            reason=str(entry.get("reason", "")).strip()[:200],
            evidence_ids=cited,
            confidence=_one_of(entry.get("confidence"), CONFIDENCES, "low")))
    return kept, dropped


def _one_of(value: Any, allowed: tuple[str, ...], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def run_role(role: str, pack: EvidencePack, gateway: Any) -> RoleFinding:
    """Ask one lens. Never raises: a lens that cannot answer is recorded and the council goes on."""
    prompt = llm.load_prompt(ROLE_PROMPT[role])
    finding = RoleFinding(role=role, outcome="error", prompt_id=prompt.prompt_id,
                          prompt_version=prompt.version, created_at=now_utc())
    result = gateway.complete(prompt, pack.for_role(role), {})
    finding.model = result.model
    finding.provider = getattr(gateway.provider, "last_used", "") or getattr(gateway.provider, "name", "")
    if result.outcome not in ("ok", "cached") or not result.text:
        finding.outcome = result.outcome
        finding.error = result.error
        return finding
    try:
        payload = json.loads(result.text)
    except (json.JSONDecodeError, TypeError):
        finding.outcome = "unparsable"
        finding.error = "the model did not return one JSON object"
        return finding
    if not isinstance(payload, dict):
        finding.outcome = "unparsable"
        finding.error = "the model returned JSON that is not an object"
        return finding
    finding.assessments, finding.dropped = _clean_assessments(payload.get("assessments"), pack)
    finding.unresolved = [str(u)[:200] for u in payload.get("unresolved", []) if str(u).strip()][:10]
    finding.outcome = "ok"
    return finding


@dataclass
class Conflict:
    """One company the lenses disagree about. Found by comparison, never by asking a model."""

    company: str
    views: list[dict[str, str]]

    @property
    def lenses(self) -> tuple[str, ...]:
        return tuple(v["lens"] for v in self.views)


def detect_conflicts(findings: list[RoleFinding]) -> list[Conflict]:
    """A conflict is one company that one lens calls a benefit and another calls a loss.

    Deterministic on purpose: this is the case the council exists for, so it cannot depend on a model
    noticing it. Neutral and unclear views are carried on a conflicting company but never create one.
    """
    by_company: dict[str, list[dict[str, str]]] = {}
    for finding in findings:
        if not finding.ok:
            continue
        for a in finding.assessments:
            by_company.setdefault(a.company, []).append(
                {"lens": finding.role, "direction": a.direction, "why": a.reason,
                 "confidence": a.confidence, "magnitude": a.magnitude, "timing": a.timing})
    conflicts = []
    for company, views in sorted(by_company.items()):
        directions = {v["direction"] for v in views}
        if "benefit" in directions and "suffer" in directions:
            conflicts.append(Conflict(company=company, views=views))
    return conflicts


def agreed(findings: list[RoleFinding], direction: str) -> list[dict[str, Any]]:
    """Companies every lens that took a side put on the same side, with no lens opposing."""
    opposite = "suffer" if direction == "benefit" else "benefit"
    by_company: dict[str, list[RoleFinding | Any]] = {}
    for finding in findings:
        if not finding.ok:
            continue
        for a in finding.assessments:
            by_company.setdefault(a.company, []).append((finding.role, a))
    out = []
    for company, pairs in sorted(by_company.items()):
        dirs = {a.direction for _, a in pairs}
        if direction in dirs and opposite not in dirs:
            backing = [(role, a) for role, a in pairs if a.direction == direction]
            out.append({"company": company, "lenses": [role for role, _ in backing],
                        "why": backing[0][1].reason,
                        "timing": "immediate" if any(a.timing == "immediate" for _, a in backing)
                        else "delayed"})
    return out


@dataclass
class Verdict:
    """What the council concluded. Produced from the findings even when no model could synthesise."""

    event: str
    created_at: str
    findings: list[RoleFinding]
    benefit: list[dict[str, Any]]
    suffer: list[dict[str, Any]]
    conflicted: list[Conflict]
    monitor: list[str]
    narrative: dict[str, Any] | None = None
    narrative_error: str | None = None

    @property
    def lenses_that_answered(self) -> tuple[str, ...]:
        return tuple(f.role for f in self.findings if f.ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event, "created_at": self.created_at,
            "lenses_that_answered": list(self.lenses_that_answered),
            "benefit": self.benefit, "suffer": self.suffer,
            "conflicted": [{"company": c.company, "views": c.views} for c in self.conflicted],
            "monitor": self.monitor,
            "findings": [{"role": f.role, "outcome": f.outcome, "provider": f.provider,
                          "model": f.model, "prompt_id": f.prompt_id,
                          "prompt_version": f.prompt_version, "created_at": f.created_at,
                          "assessments": [vars(a) | {"evidence_ids": list(a.evidence_ids)}
                                          for a in f.assessments],
                          "unresolved": f.unresolved, "dropped": f.dropped, "error": f.error}
                         for f in self.findings],
            "narrative": self.narrative, "narrative_error": self.narrative_error,
        }


def deliberate(pack: EvidencePack, gateway_for: Any, *, synthesise: bool = True) -> Verdict:
    """Run the three lenses, compare them in Python, then ask the orchestrator to explain the comparison.

    `gateway_for(role)` returns the gateway for that role, so each lens can run on its own account.
    A lens that fails is recorded and the council continues with the rest; a verdict needs at least one.
    """
    findings = [run_role(role, pack, gateway_for(role)) for role in ROLES]
    if not any(f.ok for f in findings):
        reasons = "; ".join(f"{f.role}: {f.outcome}" for f in findings)
        raise CouncilError(f"no lens answered ({reasons})")
    conflicts = detect_conflicts(findings)
    monitor = sorted({u for f in findings if f.ok for u in f.unresolved})
    verdict = Verdict(event=pack.event, created_at=now_utc(), findings=findings,
                      benefit=agreed(findings, "benefit"), suffer=agreed(findings, "suffer"),
                      conflicted=conflicts, monitor=monitor)
    if synthesise:
        _add_narrative(verdict, pack, gateway_for)
    return verdict


def _add_narrative(verdict: Verdict, pack: EvidencePack, gateway_for: Any) -> None:
    """Ask the orchestrator to explain the comparison. The verdict stands without it."""
    prompt = llm.load_prompt(SYNTHESIS_PROMPT)
    brief = json.dumps({
        "event": pack.event,
        "computed_agreement": {"benefit": verdict.benefit, "suffer": verdict.suffer},
        "computed_conflicts": [{"company": c.company, "views": c.views} for c in verdict.conflicted],
        "unresolved": verdict.monitor,
        "findings": [{"lens": f.role, "assessments": [vars(a) | {"evidence_ids": list(a.evidence_ids)}
                                                      for a in f.assessments]}
                     for f in verdict.findings if f.ok],
    }, sort_keys=True)
    result = gateway_for("news").complete(prompt, brief, {})
    if result.outcome not in ("ok", "cached") or not result.text:
        verdict.narrative_error = result.error or result.outcome
        return
    try:
        payload = json.loads(result.text)
    except (json.JSONDecodeError, TypeError):
        verdict.narrative_error = "the orchestrator did not return one JSON object"
        return
    if not isinstance(payload, dict):
        verdict.narrative_error = "the orchestrator returned JSON that is not an object"
        return
    # The computed comparison is authoritative: a narrative may explain it, never replace it.
    payload.pop("benefit", None)
    payload.pop("suffer", None)
    verdict.narrative = payload
