# News collector

## What it collects
Headlines, publication dates, links and a short snippet (never the article body) into the psx-library table
`news_item`. Facts are extracted from these later, with the usual dated pipeline, once the owner approves that phase.

| Source | Depth | How |
|---|---|---|
| Mettis (`mettisglobal.news`) | 16 Nov to 1 Dec 2025 (about 300 articles), then every new article | `/latest` (the 15 newest, every run) and the post sitemaps; each article page is read for its headline and date |
| Express Tribune business | new articles from the first run on | the site's business RSS feed (title, date, description); no article page is fetched |

Mettis's gap, found on 16 Nov 2026: its sitemap stopped listing articles after about 1 Dec 2025, `/latest` has no
pagination, and article links need their slug (a bare ID returns 404). The articles from December 2025 to November 2026
(IDs about 57,000 to 65,000) therefore cannot be discovered politely, so Mettis history starts at the sitemap slice and
continues from the first live run. If Mettis can supply an archive or feed, add it here.

Not included, by the owner's decision on 16 Nov 2026: Dawn, Business Recorder and Profit. Their robots.txt files (or
network access) do not allow what the owner wants; the owner will arrange access with them directly. Express Tribune's
history before the first run needs a separate decision (its business section has no deep feed; its sitemaps cover all
sections, about 185 stories a day).

## Rules it enforces (engines/news_collector.py)
- Every request is checked against the site's stored robots.txt first (refreshed daily). A disallowed URL is never
  fetched. If robots.txt cannot be read and no copy is stored, nothing is fetched.
- 8 seconds between requests; at most 25 article pages per run; at most 300 requests a day for Mettis and 100 for
  Tribune. Ceilings are counted in `news_progress`; the run is logged in `fetch_log` (`news_stored` / `news_noop`).
- Honest User-Agent with the contact address used by the Investify tick (`PSXNI_CONTACT_EMAIL`, default the repo URL).
- Idempotent: a stored or skipped URL is never fetched again. A re-run changes nothing.

## Scheduling (external timer, every 30 minutes, around the clock)
GitHub's own cron is not used. In cron-job.org, clone the existing PSX tick job and change only these:
- Title: `News collector`
- URL: `https://api.github.com/repos/imranrazabozdar/PSX-NEWS-INTELLIGENCE/actions/workflows/news_collect.yml/dispatches`
- Schedule: every 30 minutes, every day (the same token works; nothing else changes).
Success is HTTP 204 and a `workflow_dispatch` run of "News collector" in the Actions tab.

## Pace
Mettis publishes about 22 articles a day and `/latest` shows the 15 newest, so a poll every 30 minutes misses none.
The sitemap slice (about 300 articles) takes about half a day at 25 articles a run, then each run mostly stores new items.
