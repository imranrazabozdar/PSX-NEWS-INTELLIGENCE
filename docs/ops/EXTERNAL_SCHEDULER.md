# External scheduler (backup for the autonomous tick)

## Why
GitHub runs `schedule:` workflows on a best-effort basis. On Monday 16 Nov 2026 no scheduled run of
`psx_fetch.yml` or `tick-dispatcher.yml` fired between 01:17 and 05:00 UTC, although both crons on `main` were correct
and every workflow was active. The only scheduled runs so far were two on Friday 13 Nov (16:42 and 16:45 UTC, both
`tick_noop`, outside an open session). The in-repo cron is left in place; this adds a second, independent trigger.

## What it does
An outside cron service calls GitHub's workflow-dispatch API on the same weekday slots. The tick itself still decides
every run (trading window, open sessions, 15-minute gap across all resources, daily and weekly ceilings, library check,
robots.txt), so a double trigger is a harmless no-op and the owner-set ceilings (12 a day, 60 a week) still hold.

## Owner steps (about 5 minutes; the token is never put in the repository or in chat)
1. GitHub, Settings, Developer settings, Fine-grained tokens, Generate new token.
   - Repository access: only `imranrazabozdar/PSX-NEWS-INTELLIGENCE`.
   - Permission: Actions, Read and write. Nothing else.
   - Expiry: 90 days at most. Put the expiry date in your calendar.
2. Create a free account on a cron service that can send an HTTP POST with headers (for example cron-job.org).
3. New job:
   - URL: `https://api.github.com/repos/imranrazabozdar/PSX-NEWS-INTELLIGENCE/actions/workflows/psx_fetch.yml/dispatches`
   - Method: POST
   - Headers: `Authorization: Bearer <the token>`, `Accept: application/vnd.github+json`,
     `X-GitHub-Api-Version: 2022-11-28`
   - Body: `{"ref":"main"}`
   - Time zone: UTC. Days: Monday to Friday. Hours: 1 to 11. Minutes: 17 and 47 (that is 06:17 to 16:47 PKT).
   - Success is HTTP 204.
4. Check: after the first slot, GitHub, Actions, "PSX good-citizen fetcher" should show a `workflow_dispatch` run.
   401 or 403 means the token or its permission is wrong; 404 means the repository or file name is wrong.

## Keeping it healthy
- Renew the token before it expires and update it in the cron service.
- Do not add a second external scheduler: one in-repo cron plus one external trigger is the limit (see
  `AUTONOMOUS_FETCHER.md`, "exactly one scheduler").
