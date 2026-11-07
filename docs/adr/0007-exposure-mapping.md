# ADR-0007: Phase 4 company exposure mapping

Status: Accepted (owner, 2026-11-07; PR #15, merge commit 0bdfb1a)

## Context
Spec §14 Phase 4 says: seed business segments and evidence-backed exposures, build candidate mapping
and human review. Acceptance: correct direct and indirect links, and unrelated companies excluded with
reasons. Spec §1.2 forbids assuming identical exposure within a sector, and §5 forbids inferring
exposure from sector membership. No company-specific evidence source is approved yet.

## Decision
1. Reuse the existing tables: company master, aliases, identifiers, status history, `company_exposures`,
   `company_segments` and `event_companies`. Migration `0008` adds `company_relationships`,
   `exposure_candidates`, `exposure_candidate_revisions` and `exposure_reviews`, additively. It is applied
   to local and CI test databases only; production is unchanged (still at 0005).
2. Use deterministic, versioned rules first (`exposure-rules/1.0.0`). The sign of an effect comes from
   the company's own documented exposure. Sector membership yields only unverified, indirect,
   unknown-direction candidates.
3. Evidence status is assigned by fixed rules and guarded by CHECK constraints. Confirmation requires
   approved sources, a corroborated or primary-confirmed event, and a human acceptance.
4. Directions keep the existing column values, with an explicit lookup (UNCERTAIN → `unknown`).
   `neutral` stays distinct.
5. The LLM is optional, through the single Phase 3 gateway. Its suggestions are validated
   deterministically, capped at `potential` and always reviewed. Rejected suggestions are audited.
6. Records are append-only: candidates change only through revisions, reviews are never edited, and
   re-runs never overwrite human decisions.
7. PSX-sourced company profile text is not used as exposure evidence until the licensing question
   (D4) is resolved.

## Consequences
- Phase 5 can consume confirmed `event_companies` links and candidates with explicit missing evidence.
- Until approved company-evidence sources exist, no real mapping is confirmed or strongly supported.

## Amendment: database-integrity review (2026-11-07, before merge)
Migration 0008 had run only on throwaway local and CI databases, so it was revised in place. Production
is still at 0005. Changes:
- JSON evidence-id lists are replaced by `exposure_candidate_evidence`, with foreign keys and ownership
  triggers.
- Revisions are written by triggers.
- Status upgrades are re-checked against the linked evidence, approved sources and event verification.
- `confirmed` requires an immutable acceptance review referenced by `last_review_id`.
- `company_relationships` is append-only, with correction chains and cycle checks.
- A synthetic-source flag has been added.

Full list: `docs/EXPOSURE_MAPPING.md` §6.
