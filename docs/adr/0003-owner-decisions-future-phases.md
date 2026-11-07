# ADR-0003: Owner decisions for future phases

* **Status:** Accepted as **guidance only**. These decisions **do not** authorise starting Phase 1
  or any later phase. Each phase still needs the owner's explicit approval.
* **Date:** 2026-11-07

| # | Topic | Decision | Applies from |
|---|---|---|---|
| C1 | Specification | A sanitised technical specification is kept in the repo at `docs/SPECIFICATION.md`. It excludes private investment information, credentials and secrets. | Phase 0 (done) |
| C2 | LLM | Provider-independent architecture behind a provider adapter interface. Claude API is the preferred first candidate, with a daily spending limit, per-call and daily token limits, caching by content hash + prompt/model version, and relevance filtering before any LLM call. | Phase 3 |
| C3 | Dashboard | Private / authenticated only. The dashboard must never be publicly accessible. | Phase 6 |
| C4 | Company universe | About 30–50 companies. Start from the KSE-30, then add fundamentally important, liquid companies across banks, E&P, gas utilities, OMCs, refineries, power, cement, fertilizer, steel, technology and other relevant sectors. Every entry must be validated against official PSX listings. The schema must allow later expansion. | Phase 1 |
| C5 | Initial sources | PSX announcements, SBP, Business Recorder, Dawn, Profit, with official sources (PSX, SBP) first. Before any collector is implemented, verify and document its access permissions, terms of use, robots rules and collection method. | Phase 2 |
| C6 | Reuters | Not activated until licensed or authorised access is available. | — |
| C7 | X and YouTube | The supplied watchlists are preserved verbatim (`docs/SPECIFICATION.md` §4). Implementation and API/subscription decisions are deferred to Phase 11. Donald Trump and Reuters stay pending until exact handles are supplied. | Phase 11 |
| — | Independence | ADR-0001 remains permanent and non-negotiable. | Always |
