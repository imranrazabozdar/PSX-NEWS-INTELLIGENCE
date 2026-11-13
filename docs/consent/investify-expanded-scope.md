# Consent record: Investify expanded scope

Status: **owner-reported approval. The approval email is held by the owner and is not in this repository.**

| Field | Value |
|---|---|
| Source | Investify expanded-scope approval email |
| Approval date | [APPROVAL DATE] (owner to supply) |
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

## Enablement is separate from consent

Consent does not switch anything on. The per-category flags stay as they are:
- `collectors_enabled` in `config/investify_good_citizen.json`: announcements, fundamentals, profile, competitors, news. All false.
- `news_enabled` in `config/investify_flags.json`: false.
- The five categories with no collector (Market & Index, Sectors, Technicals, Sentiment, Rates & Commodities) have no
  fetch path at all. Enabling any of them is a separate, approved step.

## Owner to confirm

- The approval date, in place of `[APPROVAL DATE]`.
- That `investify.com` (the sender) and `investify.pk` (the data host) are the same operator, as noted in the earlier record.
