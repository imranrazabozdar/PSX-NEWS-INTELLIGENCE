# Consent record: Investify (investify.pk)

Status: **owner-reported authorisation; the signed consent itself is held by the owner and is not in this repository.**

| Field | Value |
|---|---|
| Source | Investify (investify.pk), public announcements listing at `https://www.investify.pk/announcements` |
| Granted | 2026-11-12 (as reported by the owner) |
| Effective from | 2026-11-12T00:00:00Z. The collector refuses to poll before this time. |
| Scope | Non-commercial personal research |
| Revocable | Yes. Revocation disables the source in the registry and stops all polling. |

## Conditions (binding on the collector)

These are enforced in code, not only documented:

1. **Rate:** at most one request per 15 minutes. Enforced in `collectors/investify_policy.py` (`MIN_INTERVAL`), with the last-request time kept in a state file that persists across scheduled runs.
2. **Trading hours:** Monday to Friday, 09:00 to 16:30 Pakistan Standard Time (PKT). Enforced with the existing gate `engines.termux_node_runner.within_trading_hours`.
3. **Conditional requests:** send `If-None-Match` (ETag) and `If-Modified-Since` from the previous response. A `304 Not Modified` is a no-op.
4. **robots.txt:** obey `https://www.investify.pk/robots.txt`. A disallowed path is never fetched. The robots file is cached for 24 hours. Fetching it counts as the run's single request.
5. **Backoff:** on `429` or `503`, stop. Do not retry. Wait for `Retry-After` if given (capped at 6 hours), otherwise 60 minutes.
6. **Attribution:** every stored record carries `Source: Investify (investify.pk)`. Anyone displaying the data must show the same attribution.
7. **Metadata only:** store symbol, title, date, category, source URL, PDF URL and the PDF access flag. Investify's own summary text is never stored.
8. **PDFs:** the PDFs are hosted by PSX (`dps.psx.com.pk`). They are browser-fetch only and are never downloaded by the collector.
9. **Identifying User-Agent:** the collector identifies itself with the project name and repository URL.

## Verification note (owner to confirm)

- The consent email came from an `investify.com` address. The data is served from `investify.pk` and `www.investify.pk`.
- **Owner to confirm** that `investify.com` and `investify.pk` are the same entity (the same operator under both domains) before the first live run.
- The sender's identity and contact details are deliberately not recorded here.

## How the registry encodes this consent

The news database's constraints only accept the values below, so the consent is encoded with these
rather than with a dedicated label:

| Field | Value | Why |
|---|---|---|
| `enabled` | 1 | Set from the registry flag for consent-governed sources only |
| `lifecycle_status` | `APPROVED` | Not `ACTIVE`, so the generic engine never collects it; the lifecycle set has no consent value and adding one needs a table rebuild migration |
| `terms_status` | `approved` | The consent itself is the record in this file |
| `access_status` | `verified_permitted` | Required by the database for `enabled = 1`. It reflects the written permission, not a technical access test |
| `access_method` | `html_permitted` | The database has no consent value; the page is HTML |
| `licensing_status` | `permission_required` | Kept deliberately: the generic engine refuses dry runs for it |

The generic engine also refuses this source outright (`CONSENT_GOVERNED` in `collectors/engine.py`).

## Date note (owner to confirm)

The consent is dated 2026-11-12. The repository date when this record was written is 2026-11-11, so the collector will refuse to poll until 2026-11-12T00:00:00Z. Confirm the date, or correct it here and in `collectors/investify_policy.py`.
