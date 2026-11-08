# PSX trading calendar: what is needed to complete it

**Status 2026-11-08:** regular hours (Monday–Thursday, Friday) and the seven fixed-date 2026 holidays are
recorded from the official PSX website pages (Trading Hours, Calendar Holidays). Still absent pending official
notices: moon-dependent holiday dates, seasonal (Ramadan) timings, special sessions and closures. They may be entered only from official Pakistan Stock Exchange notices, and each
entry must cite its notice (`source`). The loader refuses an entry without one. Nothing in this document
is a confirmed date or time.

Until they are entered, grading infers each session from the bars the tracked symbols actually traded.
Nothing is lost by leaving them empty, except ANOMALY detection for bars outside official hours and the
explicit labelling of holidays (a holiday currently shows as MARKET_CLOSED_INFERRED, never as missing).

## Notices needed (official sources only)

| Calendar field | Official document to obtain | Published by / where |
|---|---|---|
| `regular_hours` (per weekday, incl. Friday) | The current notice on trading timings for the Ready (regular) market, and the PSX Rule Book section on trading hours | PSX: Notices section of psx.com.pk; PSX Rule Book |
| Seasonal changes (e.g. Ramadan timings) | The PSX notice announcing revised trading timings for that period | PSX notice, issued before each change |
| `holidays` | PSX's annual list of market holidays, plus each separate notice for holidays announced later (e.g. moon-sighting dependent Eid days) | PSX notices (PSX follows federal holiday notifications but issues its own notice) |
| `special_sessions` | The PSX notice for any special or extended session | PSX notice |
| `closures` | The PSX notice or circular confirming an unscheduled closure or trading halt | PSX notice; SECP if applicable |

## Entry template (fill only from the cited notice)

```json
"regular_hours": {
  "0": {"open": "HH:MM", "close": "HH:MM"},
  "4": {"open": "HH:MM", "close": "HH:MM"}
},
"holidays":         {"YYYY-MM-DD": {"name": "<as in the notice>", "source": "PSX notice <number>, <date>, <URL>"}},
"special_sessions": {"YYYY-MM-DD": {"open": "HH:MM", "close": "HH:MM", "source": "PSX notice <number>, <date>, <URL>"}},
"closures":         {"YYYY-MM-DD": {"name": "<reason in the notice>", "source": "PSX notice <number>, <date>, <URL>"}}
```

Times are PKT. `regular_hours` keys are weekday numbers (`0` Monday … `4` Friday), or `default`. A
weekday without its own entry uses `default`. If a notice gives split sessions (e.g. a Friday break), use
the overall open and close: the break is detected from the data without false alerts.

## Procedure
1. Download the notice from psx.com.pk and keep the PDF or URL.
2. Add the entry with `source` = notice number, date and URL.
3. Run `pytest tests/test_market_quality_and_ops.py`. The loader rejects malformed or uncited entries.
4. Open a PR that names the notice. No production change is needed: the calendar is read by the app and
   the collector at run time.
