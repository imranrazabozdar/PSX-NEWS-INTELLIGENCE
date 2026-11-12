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

## Owner confirmations (2026-11-12, recorded before the live proof)

- **Operator:** the owner confirms that **investify.pk is the operator** of the data served at `investify.pk`. The
  earlier open item on `investify.com` versus `investify.pk` is closed on this basis.
- **Endpoint paths** (confirmed by the owner from the browser):
  - fundamentals: `/company/{symbol}/fundamentals`
  - competitors: `/company/{symbol}/competitors`
  - profile: `/company/{symbol}/profile`, inferred and verified by one conditional GET. It stays unset if it returns 404.
- **Industry:** there is no Industry endpoint. Sector or industry fields are derived from the profile or competitors
  payload, and no separate page is fetched.
- **Storage:** STRUCTURED FIELDS ONLY. The raw page body and Investify's generated summary text are not persisted.
  The owner may expand this later, and that would need a new record.
- **Target:** the operational database only. Nothing goes to the archive, to production, or to Turso.

## Owner decisions recorded during the HUBC pilot (2026-11-12)

- **Company description:** stored per the owner's decision (the earlier exclusion is removed). It is stored
  privately, attributed to Investify (investify.pk), in the same structured record as the other profile fields.
- **Competitors:** the peer cards render client-side and are not in the server-rendered page. The peer set is
  therefore SECTOR-DERIVED from the page's embedded company index: every listed company in the same sector. It is
  marked `peer_source = "sector-derived"`. Investify's displayed peer tab curates to 14 companies; the derived set
  is a superset by two (the two same-sector companies Investify excludes are recorded in the record). No
  headless or JavaScript-rendering fetch is made for the pilot.
- **Industry:** derived from the profile sector; no separate endpoint.
- **Fundamentals first fill:** a company with no fundamentals on record is filled once from its most recent
  financial result, however old. After that, refreshes fire only on results newer than the last one seen, within
  three days, deduplicated by symbol, date and headline.

## Gate decisions (owner-confirmed, recorded 2026-11-12 at the HUBC pilot checkpoint)

- **First-fill rule (confirmed):** a watchlist company with no fundamentals on record is filled ONCE, from its most
  recent financial result, however old. Refreshes after that fire only on results newer than the last one seen,
  within three days, deduplicated by symbol, Pakistan-time date and headline.
- **Competitors (confirmed):** the peer set is the SECTOR-DERIVED list from the embedded company index (16 for
  HUBC), recorded as `peer_source = "sector-derived"`. It is a superset of Investify's displayed tab (14) by two.
- **Private retention (owner-confirmed):** all Investify-sourced data stays private to the local database. It is
  never redistributed, never shown in a public dashboard, and analysis outputs must not reproduce Investify's
  text or data verbatim publicly (consent condition 1 and Investify's copyright terms).
- **Audit correction:** the 09:47:26Z competitors request was logged `manual=true` in error. It was the first
  backfill. A correction line is appended to the audit log; the original line is kept.
