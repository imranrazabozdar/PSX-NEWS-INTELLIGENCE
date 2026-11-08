# X watchlist runbook (M1)

**Status:** the 33 owner-supplied accounts are seeded, plus 2 pending accounts whose handles are not guessed. There is
**no automated collection**: the official X API needs an owner plan decision (research task R7), and no paid plan is
authorised. Scraping, login bypass and browser imitation are not used.

**Check status:**

```
python -m engines.x_watchlist status
```

Every account reports `monitored: false` until its identity is verified and authorised access exists. The last
retrieval time comes only from stored imports.

**Manual import:** the owner obtains posts lawfully and attests to that.

```
python -m engines.x_watchlist import posts.json --importer "<name>" --rights-attestation "<how obtained>"
```

Each record in `posts.json`:

| Field | Required | Value |
|---|---|---|
| `handle` | Yes | A handle already in the watchlist |
| `post_url` | Yes | `https://x.com/<handle>/status/<id>` |
| `published_at_utc` | Yes | `YYYY-MM-DDTHH:MM:SSZ` |
| `text` | Unless the post is deleted or inaccessible | Post text |
| `availability` | No | `available`, `edited`, `deleted` or `inaccessible` |
| `official_statement` | No | `true` only when the account speaks for the institution |

**What import does:**
* Stores the post with its URL, timestamp, collection run and an excerpt of at most 1,000 characters.
* Types the claim. A post is never a verified fact.
* Links PSX companies and entities only by exact name or ticker.
* Flags copies as repost or syndicated content.
* Tracks predictions for later evaluation.
* Lists claims that need a primary source.

**What import never does:** posts never create event evidence and never count as independent corroboration.

**Linking a claim to an event:** `link_to_event(db, post_url, event_id, role=...)` attaches an imported post to an
event as an unverified lead, context, supporting or contradicting claim. It writes only `media_event_links`, with
independence set to `same_source` (or `repost` for a detected copy), never `independent`. The event's
verification state and its corroboration, which is computed from `event_evidence` only, are unchanged.

**Availability:** for a deleted, inaccessible or edited post, the state is stored in `media_items.rejection_reason`.

Production use needs separate owner approval.
