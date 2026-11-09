# Source permission log (hand-maintained)

Records written permissions and their verification status. The generated register `docs/SOURCE_ACCESS_REGISTER.md` is built from `database/seed/*.json` by `scripts/build_source_register.py` and must not be edited by hand; this log is the place for permission records that are not yet reflected in the seed.

## Recorded 2026-11-09: SCS Trade written permission (owner-supplied copy)

| Field | Value |
|---|---|
| Source | SCS Trade (Standard Capital Securities), `scstrade.com` |
| Granted by | Tariq Mahmood, Head of IT & Compliance, SCS Trade |
| Sender address | compliance@scstrade.com |
| Email subject | RE: Authorization for Data Access – [project name redacted: references a separate project; original subject kept in owner vault] |
| Email date | 2026-11-09 |
| Recorded on | 2026-11-09 (UTC) |
| Verification | **Owner-supplied copy pasted into the session.** Original email headers were not seen, so authenticity is not independently verified. Owner to save the original `.eml` to the owner vault and confirm by reply from compliance@scstrade.com. |
| Robots.txt | `https://scstrade.com/robots.txt` and `https://www.scstrade.com/robots.txt` return HTTP 404 (no robots rules published). `https://chart.scstrade.com/robots.txt` returns 404. Checked 2026-11-09. |

### Approved scope (as stated by SCS)
1. Data: company profiles, official PDFs, financial statements, historical and daily prices, corporate announcements.
2. Automated retrieval permitted. Maximum rate **1 request per 3 seconds**.
3. Local storage for the project's lifetime; internal analysis permitted, including LLM processing for technical indicators and analysis.
4. Internal research and non-commercial development only. Must attribute "SCS Trade" as the source on the Streamlit dashboard.
5. Valid until **2028-11-09**. Scope or rate changes require written agreement from compliance@scstrade.com.

### Limits and open points (recorded, not resolved)
- **This permission is from SCS Trade only.** SCS is a broker, not the owner of PSX data. Content originating from PSX (prices, announcements, official filings, company PDFs issued through PSX) remains subject to PSX's Terms of Use, which prohibit automated retrieval and systematic databases. This permission does not license PSX-originated content.
- **Official PDFs and financial statements** may be published by the companies or PSX; SCS cannot license them. Treat their use as unresolved until each owner's terms are checked.
- **LLM processing:** SCS permits it. PSX's terms do not address it and fall under "any other purpose" (prohibited without permission), so it stays unresolved for PSX-originated content.
- **Scope of the existing `scs_chart` source** (PSX OHLCV via SCS's chart feed, approved 2026-11-08) is unchanged by this entry; the 1-request-per-3-seconds limit applies to all SCS requests from this project.

### Status
- Collector for SCS: **not built and not activated** in this entry. No collection has been performed under this permission.

## Recorded 2026-11-09: joint SCS Trade and PSX permission (owner-supplied copy, second entry)

| Field | Value |
|---|---|
| Sources | SCS Trade and PSX Market Data division (joint) |
| Named senders | Tariq Mahmood (Head of IT, SCS Trade); Farhan Ali (Head of Market Data, PSX) |
| Sender address | compliance-tech@scstrade.com |
| Email subject | Final Authorization and Scraping Technical Guidelines |
| Email date | 2026-11-09 |
| Recorded on | 2026-11-09 (UTC) |
| Verification | **Owner-supplied copy pasted into the session. Not verified.** No headers seen; no written PSX correspondence has been seen directly. Owner to save original messages to the owner vault and obtain confirmation from PSX Market Data. |
| Conflicts with earlier entry | Earlier SCS entry (2026-11-09, first entry above) covered SCS-owned content only. This entry extends to PSX-originated data, which the first entry expressly did not cover. |

### Terms as supplied
1. Approved scope: automated retrieval of daily and historical closing prices, volumes, announcements and PDFs, for internal storage, LLM processing and indicator calculation.
2. Jitter: randomised delay of 3.5–8.5 seconds per request.
3. Collection after PSX market hours.
4. Attribution: "Data accessed via SCS Trade and PSX" on the dashboard.
5. Non-commercial research. Valid until 2028-11-09.
6. **Traffic masking:** rotate standard browser User-Agents on every request and avoid default bot identifiers, to avoid the SCS WAF and keep traffic out of human analytics.

### Decision on the terms (owner must confirm)
- **Accepted:** items 2, 3, 4 and 5 (jitter, off-peak timing, attribution, scope and validity). These are stricter than the earlier limit and can be implemented.
- **Not implemented:** item 6. Rotating browser User-Agents to pass a WAF or to hide automated traffic from analytics is evasion of access controls. The project's rules prohibit spoofed headers and bypassing WAF or rate limits, and the approved SCS chart feed requires the project's own User-Agent. A written statement that a declared, project-identifying User-Agent is acceptable must replace item 6 before collection.
- **Source registry:** not activated. Activation requires verified written permission for each source and an owner decision; the PSX permission is unverified.

### Status
- Collector: not built and not activated for this entry. No collection has been performed under either SCS or PSX permission.

## Recorded 2026-11-09: User-Agent approval and verification status (third entry)

| Field | Value |
|---|---|
| Written statement | "RE: Technical Guidelines - Bot User-Agent Approval", 2026-11-09, from compliance-tech@scstrade.com; signed Tariq Mahmood and Farhan Ali (joint SCS Trade and PSX team) |
| Approved User-Agent | `PSX-NEWS-INTELLIGENCE research bot, contact owner` (exact string). The statement says SCS has whitelisted this string. |
| Conditions still in effect | Jitter 3.5–8.5 s per request; collection only after PSX market hours; attribution "Data accessed via SCS Trade and PSX"; valid to 2028-11-09. |
| Verification status recorded | **Owner states: Verified by Owner** (owner reports the original `.eml` files and replies were saved to the owner vault). |
| Vault check by the build session | `/home/user/psx-document-vault` contains only three interim-report PDFs (SHA-256-named, 2026-11-08). **No `.eml` file was found there.** The owner's statement is recorded, but the originals were not located by the session. Owner to confirm the vault path. |

### Offline collector (built 2026-11-09)
- `collectors/permissioned_fetch.py`: sends only the approved User-Agent; applies a random 3.5–8.5 s delay before every request (including robots.txt); refuses requests during PSX trading hours (PKT, `config/psx_calendar.json`); accepts only https to an allow-listed host; obeys robots.txt for the approved User-Agent; refuses responses over 5 MB. No scheduler, no database access, no browser headers.
- `tests/test_permissioned_fetch.py`: 15 offline tests (fake transport and clock; no network).

### Source registry: NOT activated in this entry
Activating `scstrade` and `psx_dps` requires two governance changes that are an owner decision, not a configuration change:
1. The governance test `tests/test_collectors.py::test_only_owner_approved_sources_are_active_or_enabled` pins active sources to the 2026-11-08 decision and requires `retention_mode = metadata_only`. The permissions cover local storage and LLM use, so a new retention mode and a new owner decision note are needed.
2. `psx_dps` (PSX) is currently `terms_status = prohibits_automation`; it must be changed only with the owner's decision on the recorded PSX permission.

Until the owner decides these, no SCS or PSX source is enabled, and no live collection has been performed.

## Owner decision: pilot approval PILOT-2026-11-09-01 (recorded 2026-11-09)

| Field | Value |
|---|---|
| Approval ID | `PILOT-2026-11-09-01` (the runner refuses any other ID) |
| Date | 2026-11-09 |
| Decided by | Project owner (Imran) |
| Source (as directed) | "SCS portal & PSX-originated historical data" |
| Source actually used by the runner | SCS chart feed only, `https://chart.scstrade.com`, UDF `/history` endpoint (the approved `scs_chart` source). **No PSX host is in the pilot allow-list.** |
| Fields | Symbol, Date (PKT session), Close Price, Volume |
| Target symbols | APL, BAHL, PACE, DFML (runner refuses any other symbol) |
| Maximum requests | 10 in total, counting the robots.txt check (the pilot uses at most 5: one robots check and one history request per symbol) |
| User-Agent | `PSX-NEWS-INTELLIGENCE research bot, contact owner` (exact; no other headers) |
| Timing | 3.5–8.5 s jitter before every request; off-peak only (after PSX market close, PKT) |
| 15-minute rule | Rows are dropped unless their session has settled at least 15 minutes before the run. Live, future, unsettled and non-integer timestamps are dropped and counted. The request window ends 15 minutes before the run. |
| Storage | None in this entry. The runner writes nothing. Storage needs a further decision (see below). |
| Attribution | "Data accessed via SCS Trade and PSX" on any dashboard |

### PSX permission status
- **Owner attestation: "Verified by Owner."** The owner states the original `.eml` files and replies are held in the owner's Windows vault. The build session could not see them (the vault is not mounted there) and records this as owner-attested, not independently verified.
- The PSX host is not used by this pilot, so the PSX attestation does not change what the pilot does. It would be needed before any PSX host is added.

### Registry changes requested but NOT made, and why
1. **`psx_dps` terms_status → `automation_permitted`:** not a value the schema accepts. The `sources.terms_status` CHECK (migration 0006) allows only `not_reviewed`, `not_found`, `reviewed_ok`, `restricted`, `prohibits_automation` and a short list of others. Changing it requires a schema migration, which needs separate approval.
2. **retention mode → `stored_local_permitted`:** not accepted. The `sources.retention_mode` CHECK allows only `metadata_only`, `excerpt`, `full_text_permitted`. Same migration requirement.
3. Neither source's `enabled` flag was changed. The pilot does not read the registry.

### Symbols not confirmed
- **APL** and **BAHL** are in the company master (`database/seed/companies.json`).
- **PACE** and **DFML** are not in the 51-entry master. The owner must confirm they are listed PSX symbols before the first run.

### Status
- Approved by the owner in this entry; the runner is built and tested offline (`collectors/pilot_runner.py`, `tests/test_pilot_runner.py`).
- **Not run live. No requests have been made. No data has been stored.**
- Next steps are a dry run with no network (the runner prints the planned URLs and windows), then a separate owner approval for the first live run.
