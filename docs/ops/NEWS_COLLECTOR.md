# News collector

## What it collects
Headlines, publication dates, links and a short snippet (never the article body) into the psx-library table
`news_item`. Facts are extracted from these later, with the usual dated pipeline, once the owner approves that phase.

| Source | Depth | How |
|---|---|---|
| Mettis (`mettisglobal.news`) | 16 Nov to 1 Dec 2025 (about 300 articles), then every new article | `/latest` (the 15 newest, every run) and the post sitemaps; each article page is read for its headline and date |
| Express Tribune business | new articles from the first run on | the site's business RSS feed (title, date, description); no article page is fetched; read every run |
| Dawn business | new articles from the first run on (the feed holds about 3 days) | `/feeds/business`, read hourly; no article page is fetched |
| Business Recorder | new articles from the first run on (the feeds hold about 7 hours) | `/feeds/latest-news` and `/feeds/business-finance`, read hourly; the same article in both feeds is stored once |
| Profit (`profit.pakistantoday.com.pk`) | new articles from the first run on, published within the last year | the front page lists them; each article page is read once for headline, date and section; read hourly |

Mettis's gap, found on 16 Nov 2026: its sitemap stopped listing articles after about 1 Dec 2025, `/latest` has no
pagination, and article links need their slug (a bare ID returns 404). The articles from December 2025 to November 2026
(IDs about 57,000 to 65,000) therefore cannot be discovered politely, so Mettis history starts at the sitemap slice and
continues from the first live run. If Mettis can supply an archive or feed, add it here.

Dawn and Business Recorder state "No AI training" and block named AI crawlers in robots.txt; they allow other crawlers to
read their feeds, so only the feeds are used and only headline, date, link and a snippet of at most 300 characters are
stored (Business Recorder's feed carries each full article, which is never read). Their archives are not collected:
Dawn's robots.txt blocks `/archive/*` and the dated `/newspaper/*/20*` pages. The owner may ask both for archive access.
Express Tribune's history before the first run needs a separate decision (its business section has no deep feed; its
sitemaps cover all sections, about 185 stories a day). Profit's sitemaps list about 10,000 articles per file back to
December 2025; a one-year history would be about 20 days of slow page fetches, or a URL-and-date index (titles from URLs
are approximate). Not started: owner decision.

## Rules it enforces (engines/news_collector.py)
- Every request is checked against the site's stored robots.txt first (refreshed daily). A disallowed URL is never
  fetched. If robots.txt cannot be read and no copy is stored, nothing is fetched.
- 8 seconds between requests; at most 25 article pages per run; daily request ceilings: Mettis 300, Profit 200,
  Business Recorder 120, Tribune 100, Dawn 60. Dawn, Business Recorder and Profit are read at most once an hour. Ceilings are counted in `news_progress`; the run is logged in `fetch_log` (`news_stored` / `news_noop`).
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

## From headlines to facts (built, not yet loaded: owner gate)
`engines/news_facts.py` and `scripts/build_news_capsule.py` turn stored headlines into dated `research_fact` rows with no
model: a company row for each listed company the HEADLINE names (a company named only in the snippet is not tagged;
sponsor mentions such as "HBL PMI" are ignored; at most three companies), a sector row when the headline is about a
sector the library already has, and a `MACRO:PAKISTAN` `market.*` row for index moves and for rates, FX, inflation,
energy, fiscal and trade headlines that have a Pakistan context. World news with no Pakistan link becomes no row.
"today" and "yesterday" become dates; source_date is the publication date; the outlet and link are on every row.
Dry run on 344 stored headlines (16 Nov 2026): 97 became rows (112 rows: 42 company, 24 sector, 46 macro). Loading goes
through `scripts/absorb_sector_capsule.py` (exact and near-duplicate rows are skipped, so one story from two outlets is
stored once). Command: `python -m scripts.build_news_capsule --out capsule.json --days 3`, then
`python -m scripts.absorb_sector_capsule capsule.json --apply`.
