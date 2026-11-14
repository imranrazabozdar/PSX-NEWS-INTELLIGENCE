# Investify good-citizen policy (self-imposed, enforced in code)

Status: IMPLEMENTED and TESTED against fixtures. No live fetch was made to build it.
Single policy file: `config/investify_good_citizen.json`. Code: `collectors/investify_good_citizen.py`.

Principle: make bursting and over-fetching structurally impossible. Every limit is a hard guarantee in code,
not a convention. Nothing here sends a message to Investify; it is ethical discipline in our own client.

## Shipped defaults (fail-safe)

| Setting | Default | Meaning |
|---|---|---|
| `collectors_enabled` | all `false` | Each collector must be turned on in the policy file |
| `kill_switch` | `false` | Halts all Investify traffic instantly; also env `PSXNI_INVESTIFY_KILL` or `PSXNI_KILL_SWITCH` = `true` |
| `min_gap_minutes` | 15 (floor 15) | At least 15 minutes between ANY two requests, all resources, measured from the real send |
| `daily_ceiling` | 12 | Hard halt for the Pakistan day when reached; WARN at 60% |
| `weekly_ceiling` | 60 | Hard halt for the Pakistan week; WARN at 60% |
| `quiet_window_pkt` | 10:00 to 15:30 | No requests at the open or close bursts |
| `cooldown_base_hours` | 4 (floor 4) | Multi-hour cooldown on any single 403, 429 or 503; doubles per consecutive block |
| `cooldown_max_hours` | 24 | Cap on the cooldown. Retry-After can lengthen it, never shorten it |
| `breaker_threshold` | 1 | The first server signal trips the circuit breaker |
| `backfill` | paused, reserve 2 | Backfill yields to pending event triggers, can be paused, and keeps a daily reserve |
| `ttl_hours` | feeds 24h; fundamentals 30d; profile and competitors 90d | Cache-first: a fresh record is not re-fetched |

## Where each rule is enforced

| Rule | Enforcement |
|---|---|
| Single in-flight request, process-wide | `single_flight()`, a process lock, around every request path (`run_endpoint`, `run_once`) |
| 15-minute global gap | `gate()` on the shared state file; tested with 5, 10, and 16 minutes |
| Fail-closed budgets | `gate()` refuses on a missing policy, missing counters, or a clock that moved backwards |
| Hard ceilings with WARN before | `gate()` (daily and weekly); `footprint()` warnings |
| Event-driven only, no polling | No scheduler or timer in the client (tested). The announcements workflow is `workflow_dispatch` only, with no `schedule` |
| Off-peak windowing | `gate()` quiet window, plus the existing trading-hours check and jitter |
| Cache-first and conditional requests | `gate()` TTL check; ETag and If-Modified-Since on every read; a 304 is a recorded no-op |
| Multi-hour cooldown and owner alert | `cooldown_until()` on 403, 429 and 503 (page and robots); an `owner_alert` audit event |
| Backfill yields, pausable, counts to budget | `gate(backfill=True)`; backfill requests increment the same daily and weekly counters |
| Cache-only mode, zero calls | `gate()` refuses before any transport call (tested with a transport that fails if called) |
| Kill switch, instant | `gate()` (policy flag and environment variable), checked before everything except the policy load |
| Observability | `footprint()` from the audit log: requests today and this week, 304 share, errors, per-resource counts, WARN lines |
| Fail-safe defaults | Shipped file: cache-only, collectors off. An unreadable or invalid file refuses everything |

## Operating it

- To turn a collector on, set its flag in `config/investify_good_citizen.json` and review the diff. To tighten a
  limit, edit the number. A value outside its floor is refused at load time.
- The footprint view reads only the audit log. The owner can read it at any time.

## Caveats

1. **Budget counters in existing state files.** A state file written before this policy has no weekly counter, so the
   gate refuses (fail closed) until the owner resets it. Reset by moving the old state file aside after reviewing
   the audit log. The next request then starts a clean count.
2. **Validation driver (other branch).** `scripts/investify_validation_run.py` lives on
   `feature/investify-scale-validation`. When that branch merges, its "rate limit" check must also treat the
   "queued" and "cooldown" reasons as waits, or it will record them as finished steps.
3. **Dispatch-only workflow.** The announcements workflow no longer runs on a timer. Someone must dispatch it. That is
   intended: nothing polls.
4. **Tests use a permissive policy by default** (`tests/conftest.py`). The policy tests use explicit policies, and the
   shipped file is tested for its fail-safe defaults.
