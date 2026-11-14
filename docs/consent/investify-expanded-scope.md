# Consent record: Investify expanded scope

Status: **owner-reported approval. The approval email is held by the owner and is not in this repository.**

| Field | Value |
|---|---|
| Source | Investify expanded-scope approval email |
| Approval date | 2026-11-12 (owner-reported, "12-11-26", day-month-year) |
| Effective from | 2026-11-12T00:00:00Z (as in the earlier records) |
| Scope | Private, non-commercial research |
| Revocable | Yes. Revocation disables the source in the registry and stops all polling. |

## Categories (exactly as the approval names them)

Original four: Announcements, Fundamentals, Profile, Competitors.
Expanded six: Market & Index, Sectors, Technicals, News, Sentiment, Rates & Commodities.

Only these ten are consented. Nothing else is. The machine-readable copy is `config/investify_consent.json`.

## Conditions (binding; enforced in code where a collector exists)

- Private, non-commercial use only.
- Attribution on every stored record: `Source: Investify (investify.pk)`.
- Revocable.
- Good-citizen limits: at most one request per 15 minutes; trading hours only; conditional requests; robots.txt;
  backoff on 429, 403 or 503 with a multi-hour cooldown; identifying User-Agent.
- Metadata only from listings; Investify's summary text is not stored.

## Limits (set by the owner, not by Investify)

- Daily ceiling: 12 requests per Pakistan day, set by the owner. The first live day is capped at 2.
- Weekly ceiling: 60 requests, set by the owner.
- Minimum gap: 15 minutes between any two requests, across all resources (the approval's condition).
- Investify's approval does not state a daily or weekly number. These limits are the owner's own.

## Enablement is separate from consent

Consent does not switch anything on. The per-category flags stay as they are:
- `collectors_enabled` in `config/investify_good_citizen.json`: announcements, fundamentals, profile, competitors, news. All false.
- `news_enabled` in `config/investify_flags.json`: false.
- The five categories with no collector (Market & Index, Sectors, Technicals, Sentiment, Rates & Commodities) have no
  fetch path at all. Enabling any of them is a separate, approved step.

## Owner to confirm

- The approval date is recorded as 2026-11-12 (read from "12-11-26", day-month-year). Confirm it if the email says otherwise.
- That `investify.com` (the sender) and `investify.pk` (the data host) are the same operator, as noted in the earlier record.
