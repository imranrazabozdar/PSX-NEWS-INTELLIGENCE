# Plan: more company-level evidence for small caps (proposal, nothing built or collected)

## The gap (measured 2026-11-17)
Over 15 days, 56 of 60 notable moves had no company-level cause on file; 4 moved with their sector. The 10 small caps
checked had no news-rollup rows since 10 November. The news outlets cover large names. Small caps are mainly visible
through PSX announcements.

## What the brain already holds for small caps
- Results, dividends, bonus, rights, book closures and meetings from the owner-supplied PSX announcement export
  (15,510 facts, 509 companies, to 2026-11-10).
- Investify announcement facts (`announcements.*`) for about 470 companies, loaded 2026-11-16/17.
- The explainer and radar use results and corporate actions, but not the other announcement kinds
  (`announcements.Board Meeting`, `AGM / EGM`, `Report Transmission`).

## Options (cheapest and safest first)
1. **Refresh the PSX export regularly (owner action, no code).** The export ends 2026-11-10. A newer `announceWithSymbol.lis`
   each week lets the existing converter add the last days' results and actions (a few hundred facts, small writes).
2. **Count more announcement kinds as evidence, at lower weight.** Board meetings and AGM notices are weak causes but
   better than nothing; label them "scheduled event", never as a cause. Code change only, read only, no new source.
3. **Show "no coverage" as information.** A heavy-volume move with no announcement and no news is itself notable. The radar
   would list it under "unexplained moves" so it is seen, not hidden.
4. **More outlets (needs source approval each time).** Only outlets whose terms permit it, one at a time, as with Profit
   and Tribune. Slowest, and small caps are rarely covered even there.

## Not proposed
Scraping PSX pages (its terms prohibit automation and the pages sit behind reCAPTCHA), social media, or any model that
guesses a cause. Unexplained stays unexplained.

## Owner decisions
- Will you export a fresh PSX announcement file weekly (or when you can)? (option 1)
- Go ahead with options 2 and 3 (code only)?
- Any outlet you want evaluated for option 4?
