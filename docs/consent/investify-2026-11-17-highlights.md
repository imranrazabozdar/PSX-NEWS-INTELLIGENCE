# Consent record: Investify addendum, announcement Highlights and document access (17 November 2026)

Status: **owner-supplied written addendum from Investify's Platform & Compliance Team, dated 17 November 2026,
pasted into the session by the owner. The signed original is held by the owner and is not in this repository.**
It adds to the written permission of 12 November 2026 (`docs/consent/investify-2026-11-12.md`), which otherwise
stays in full force.

| Field | Value |
|---|---|
| Source | Investify (investify.pk), announcement cards |
| Granted | 2026-11-17 |
| Effective from | 2026-11-17T00:00:00Z. The collector stores Highlights only on or after this time. |
| Scope | Strictly private, non-commercial quantitative and market research |

## What the addendum grants

1. **Highlights text may be collected and stored.** The short "Highlights" summary text shown on each announcement
   card (the key-facts line and the summary paragraph under the title) may be stored, under all existing conditions.
   This replaces condition 7 of the 12 November permission ("Investify's own summary text is never stored") for
   announcement cards only.
2. **Conditions that continue to apply:**
   - **Use:** private, non-commercial. Public republication, commercial resale or redistribution of the extracted
     text or summaries stays prohibited. Nothing from this text goes into a public output.
   - **Attribution:** any internal report, output or dashboard using it keeps clear attribution to Investify
     (investify.pk). Stored facts carry the source name "Investify (investify.pk), announcement highlights".
   - **Rate:** at most one HTTP request per 15 minutes, no concurrent sessions, no circumvention of safeguards.

## What the addendum confirms about documents

- The "Original PDF" links point to the source filings on the official PSX data portal. **Investify hosts no mirrored
  copies**, and offers **no public API, webhook or bulk feed** for announcement PDFs.
- **Opening individual PDFs manually in a web browser**, in line with PSX's own terms of service, is acceptable and
  needs no further permission from Investify.
- Consequence for this project: the collector still never downloads PDFs. The PSX portal remains restricted for
  automated access in `docs/SOURCE_ACCESS_REGISTER.md`. Documents reach the brain only when the owner supplies them.

## How it is enforced

- `collectors/investify_policy.py`: `HIGHLIGHTS_CONSENT_EFFECTIVE_UTC` and `HIGHLIGHTS_CONSENT_RECORD`. The library
  job stores Highlights only when the consent record file exists and the run is on or after the effective time.
- Highlights facts are written to private psx-library only (topic `announcement_highlights`); reports and artifacts
  quote numbers and size bands, not Investify's text.

## Owner decision, 2026-11-17: the Highlights may go to the council
The owner confirmed in the session that the Highlights text may be included in the council's evidence packs
(`announcement_highlights` is mapped to the "announcement" lens in `scripts/council_run.py`). The council sends its
evidence to third-party free-tier model providers (Groq, Gemini, OpenRouter) for private analysis only; nothing is
published. The source name on every item carries the attribution to Investify. Caveat recorded for the owner: free-tier
terms differ by provider and some allow inputs to be used to improve their products; each provider's current terms
have not been verified here. To withhold the text again, remove the mapping line.

## Operating decision, 2026-11-18 (owner): robots.txt and the page in one run
The earlier wording "fetching robots.txt counts as the run's single request" cost a morning window: the first run of a day refreshes the 24-hour robots.txt copy and then has to wait for a second dispatch. Decision: one dispatch may now read robots.txt, wait out the 15-minute floor (15 min 30 s), and then fetch the announcements page. The limit is UNCHANGED: never more than one request per 15 minutes, every other gate (trading window 10:00-15:30 PKT in an open session, daily and weekly ceilings, calendar, circuit breaker, robots rules themselves) is re-checked before the second request, and robots.txt is still obeyed and still counts as a request.
