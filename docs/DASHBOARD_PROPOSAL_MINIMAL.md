# Minimal dashboard proposal: company radar, event explanations, prospective performance tracker (19 Nov 2026)

**Status: proposal only. Nothing here is built or changed by this document.** It follows the council evaluation (docs/COUNCIL_DRYRUN_EVALUATION_2026-11-19.md) and depends on it for the council parts.

## Purpose
One phone-friendly page set that answers three questions with data already in the brain: which companies deserve attention today (radar), why did a stock move (event explanations), and are our rankings actually working (prospective performance tracker). No buy or sell wording, no placeholder numbers, unknown shown as unknown.

## Three screens
1. **Company radar.** Today's radar (7-day evidence window) with the score and its drivers; each company opens to its evidence (date, source), the announcement size grade and stage, and what is not on file. Source: existing radar and announcement substance engines. Already built; only a tidier layout.
2. **Event explanations.** Notable moves by day, newest first, with the candidate causes on file and "no cause on file yet" where none; each opens to the evidence and the technical-engine context. Source: existing move explainer. Already built. The council's verdicts are NOT shown until you approve production storage (they are not available to a hosted page otherwise).
3. **Performance tracker (prospective).** From the daily private snapshots now being recorded: for each ranking (technical, fundamental, combined, technical without volume) the top-10 average return minus the group's over 1, 5 and 10 sessions, how many snapshots, and a plain-language reading ("too few snapshots to say" until at least 20). Needs the snapshot file exposed to the hosted app (see decisions).

## What is excluded
The council view and the contradiction flag (waiting for your approval), charts of index data (not in the brain), alerts, personal watchlists, any trade instruction.

## Decisions needed from you
- **Where the tracker reads from.** Options: (a) a small results file the tracker workflow commits to a separate data branch and the app reads; (b) the app reads the workflow's artifact through a read-only GitHub token stored as a Streamlit secret; (c) results written to a new library table (needs your approval, production storage). I would take (a).
- Whether the radar stays a 7-day window.

## Effort and risk
Screens 1 and 2: small (layout only). Screen 3: about one day once the storage option is chosen. Risks: the tracker shows nothing meaningful for about a month; the radar for announcement-only companies is thin until Investify reads are running daily.

## Acceptance
All three pages render on a phone from live data; every number carries its date and source or says unknown; no advice wording; tests pass; you review a screen recording before it is called done.
