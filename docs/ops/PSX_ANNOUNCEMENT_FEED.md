# PSX announcement feed (owner-supplied export)

**Source and permission.** PSX's Terms of Use (reviewed 7 Nov 2026, recorded in `docs/SOURCE_ACCESS_REGISTER.md`)
prohibit automated retrieval, and the exchange's announcement pages sit behind reCAPTCHA. So nothing in this repository
fetches from PSX. The input is the file the owner downloads from PSX's published export and supplies:
`announceWithSymbol.lis` (a PKZip, even when the name ends `.Z`) and `listed_cmp.lst`. Refreshing means the owner
supplies a newer file; there is no scheduled fetch. If PSX grants written permission (marketdatarequest@psx.com.pk is
the route the register records), a collector can be added then.

**What it holds.** One line per fragment: `SYMBOL|COMPANY|DDMonYYYY|HH:MM:SS|TEXT|`. Fragments with the same symbol, date
and time are one announcement. The file supplied on 11 Nov 2026 (sha256 `bb3837923d1d9989...`) has 205,970 lines from
21 Apr 1998 to 10 Nov 2026, 539 symbols.

**What is made of it** (`engines/psx_announcements.py`, no model): `results.annual | half_year | quarterly | nine_months`
(period, basis consolidated/unconsolidated as stated, profit/loss before and after tax in PKR million, EPS; value = EPS,
or after-tax profit when no EPS), `corporate_action.dividend | bonus | rights | book_closure | meeting`. A loss in
parentheses keeps its sign; a figure the announcement does not state is unknown, never zero; a figure PSX itself
mistyped (for example `34,370..887`) is left out and counted, never repaired.

**Run (dry run, nothing loaded):**
`python -m scripts.build_psx_announcement_capsule announceWithSymbol.lis.Z --out capsule.json --since 2023-01-01`
then, once approved, load with `python -m scripts.absorb_sector_capsule capsule.json --apply` (passes of about 1,800 rows).

**Dry run on the 11 Nov file, 1 Jan 2023 onward:** 15,574 rows, 509 companies; results 9,261 (annual 2,349, half-year 2,322,
quarterly 2,319, nine-month 2,271); dividends 1,304; book closures 2,794; meetings 2,101; bonus 67; rights 47. About 90
lines (of 63,000 since 2023) were not recognised: PSX typos or missing values.

**Cross-check against Investify's annual EPS (separate source):** HUBC 38.26, OGDC 56.35, PSO 54.29, FFC 58.44 and ENGROH
46.20 match exactly. Where a company reports both consolidated and unconsolidated results (banks, LUCK) the two sources can
differ because they pick different bases; each row states the basis PSX gave.

**Official directory (`listed_cmp.lst`, 567 companies).** It confirms IBLHL, JVDC, PIBTL, PICT, TREET, HINO, GHNI, GAL, IPAK,
BAFL, STL, BBFL, ISIL, PKGP, PGLC, SOYASUP as listed. It does NOT contain IBL, JBDC, PIBC, TRT, HPCO, GHAI, DHPL, SERG, SECMC,
DHCL, BYCO, DAPL, GAGL, IPAX, SRG, SSG or AGR: these are not PSX symbols (spoken or mistyped names). 53 symbols in the older
listing snapshot are absent from the official directory (for example DAWH, ENGRO, PSMC, PIAA, PIAB); they are probably
delisted or renamed and need the owner's confirmation before anything is changed.
