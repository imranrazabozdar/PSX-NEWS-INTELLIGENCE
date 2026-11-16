# Entity review list (16 Nov 2026) - for the owner to settle

Source: `python -m scripts.validate_entities` on psx-library. "Candidate" is only a suggestion from the 544-company
snapshot or from the fact text; nothing is changed until you answer. Write the answer in the last column
(FOLD TO <ticker> / KEEP / NOT PSX / DELETE ROWS).

## A. One clear candidate in the PSX snapshot (confirm or correct)
| Entity | Rows | What its facts say | Candidate | Your answer |
|---|---|---|---|---|
| ADAMJEE | 2 | Adamjee Insurance looks attractive | AICL (Adamjee Insurance) | |
| ARL | 1 | Attock Refinery share price | ATRL | |
| BMWM, BWML, BWMT | 1+1+1 | Bannu Woollen Mills results and price | BNWM | |
| CPAL | 2 | Century Paper and Board technical levels | CEPB | |
| GWCL, GCWL | 3+2 | Gharibwal Cement (sponsors, earnings per share) | GWLC | |
| INTER | 1 | Interloop board meeting | ILP | |
| MBL | 1 | Metropolitan Bank EPS | HMB (Habib Metropolitan) | |
| NIMIR | 1 | Nimir Industrial Chemicals dividend | NICL (not NRSL = Nimir Resins) | |
| PWC, PCL, POWC | 5+3+2 | Power Cement valuation and debt | POWER | |
| SSOIL | 1 | S.S. Oil top gainer | SSOM | |
| HPCO | 1 | share price in the week to 14 Aug 2026 | HINO (HinoPak) - the text does not name it | |
| GHAL | 1 | Gandhara Automobiles board meeting | GAL (you confirmed GAL = Ghandhara Automobiles) | |

## B. Real PSX names, ticker not in the snapshot (please give the ticker)
| Entity | Rows | What its facts say | Your ticker |
|---|---|---|---|
| ALFH | 5 | Bank Alfalah balance sheet (my recollection: BAFL) | |
| BBFL | 4 | Big Bird Foods export orders | |
| DHPL | 4 | DH Partners dividend, PKR 1 per unit | |
| GHAI | 4 | Suzuki-linked auto maker, "name not verified" | |
| SECMC | 4 | Sindh Engro Coal Mining Company (Thar Block II) | |
| SERG | 3 | Serg weekly price moves | |
| STL | 3 | STL Super Net Technologies (after a merger) | |
| PARCO | 2 | Pak-Arab Refinery exports | |
| PEL | 2 | Pakistan Electron (Walton Road factory) | |
| WAFI | 2 | WAFI Energy results | |
| BYCO | 1 | Byco Petroleum | |
| DHCL | 1 | Dawood Hercules | |
| DAPL, GAGL, IBL, IPAX, JBDC, PIBC, SRG, SSG, TRT, AGR | 1 each | only a weekly price move or one event; the transcript gave a spoken code, not a name | |

## C. Already PSX-verified earlier, missing from the snapshot (I would add to owner_confirmed)
MIIETF (Mahaana Islamic Index ETF, 3 rows), MZNPETF (Meezan ETF, 1), JSMFETF (JS Momentum Factor ETF, 2).

## D. Not PSX-listed (I would keep as names, not tickers)
BYD (16 rows, Chinese EV maker), FTX (1, collapsed crypto exchange).

## E. Named entities
| Entity | Rows | Question | Your answer |
|---|---|---|---|
| SITARA | 9 | Sitara Chemicals (caustic soda). Snapshot has SITC = Sitara Chemical Industries. Fold to SITC? (SPL = Sitara Peroxide, SEL = Sitara Energy are different) | |
| Smile Industries | 1 | Food company at P/E ~25. Validator suggested ISIL (Ismail Industries) - not the same name. Is it Ismail, or keep? | |
| Park Power (3), Park Jan Power (1) | 4 | Same company? Snapshot has no "Park". PKGP is PAKGEN, which you already confirmed. | |
| Park GL Leasing (1), Park Glen Leasing (1) | 2 | Same, a mis-transcription of one name? | |
| Apex Agro Processors and Atmospheric Gases (28) vs Soya Supreme (12) | 40 | Two different companies, or one renamed? Neither is in the snapshot. | |

Everything not listed here is either a ticker already in the snapshot, a SECTOR/MACRO entity, or a plain company name
that the validator reports but I would leave alone (261 name-only entities).
