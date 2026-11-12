# Consent record: Investify fundamentals, company profile, competitors and industry (investify.pk)

Status: **owner-reported expansion; the consent email is held by the owner and is not in this repository.** The
sender's identity and contact details are deliberately not recorded here.

This record extends `docs/consent/investify-2026-11-12.md` (the announcements listing). It does not replace it:
the announcements conditions still apply to the announcements collector.

| Field | Value |
|---|---|
| Source | Investify (investify.pk): Fundamentals, Company Profile, Competitors and Industry pages for watchlist companies |
| Granted | 2026-11-12 (email from Investify support, as reported by the owner) |
| Effective from | 2026-11-12T00:00:00Z. The collector refuses to fetch before this time. |
| Scope | Non-commercial personal research, private to the local database |
| Revocable | Yes. Revocation disables `investify_fundamentals` in the source registry and stops all requests. |

## Conditions (binding; enforced in code)

1. **Use.** Strictly personal and non-commercial. The data stays private to the local database. No redistribution,
   no public hosting, no resale. Enforced by the registry
   entry (private, not public) and by the absence of any export or publishing path in this code.
2. **Refresh is event-driven only.** A fundamentals refresh is triggered by a new financial-result announcement
   for that company, and no other trigger. At most one request per 15 minutes, shared across all Investify
   endpoints (the collector uses one state file for every endpoint). Enforced in
   `collectors/investify_fundamentals.py` (rule a) and `collectors/investify_policy.py` (`MIN_INTERVAL`).
3. **Conditional requests and robots.** Honour ETag and If-Modified-Since. A 304 is a recorded no-op. Honour
   `robots.txt`; a disallowed path is never fetched. Back off immediately on 429 or 503 (Retry-After if given,
   otherwise 60 minutes, capped at 6 hours).
4. **Attribution.** Investify (investify.pk) is the source of every profile and fundamental metric. Every stored
   record carries `source = "investify.pk"` and the attribution string. Anyone displaying the data must show it.

## Additional conditions adopted by the collector (not in the email; to be confirmed by the owner)

- **Profile, competitors and industry are backfilled once** per company and are then refreshed only by a manual
  command. They are never polled. The stored copy is considered stale after 90 days but is still not re-fetched
  automatically.
- **No PDFs, no crawling, no link following.** One endpoint per request, the paths below only.
- **Honest identifiable User-Agent** as for the announcements collector.

## Open items before the first live request (owner)

1. **Endpoint paths.** The four path templates are not yet confirmed. They are `None` in the code and the collector
   refuses to request an unconfirmed path. Confirm the exact paths on investify.pk (for example
   `/company/{SYMBOL}/...`), or confirm that the company quote page carries these pages.
2. **Entity.** Confirm that `investify.com` (the consent email's sender domain) and `investify.pk` are the same
   operator. Unchanged from the announcements record.
3. **Summary text.** Investify's generated summary paragraphs may appear on these pages. The announcements
   collector never stores them. Owner to decide whether this collector stores the raw page body (current
   behaviour, needed for the cache) or only the structured fields once a parser is approved.
4. **Storage target.** The first proof uses the local operational SQLite database. Production Turso writes need
   owner approval.
