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

## F. Evidence from the owner's Investify screenshots (KSE All list, 16 Nov 2026 close, 20 images)
Read from the screenshots only; names in the app are sometimes cut off, so "seen" means the ticker and the visible part
of the name. Nothing has been changed in the alias file or Turso from this.

| Entity in the brain | Seen in the app | Reading |
|---|---|---|
| ALFH | BAFL, Bank Al-Falah Ltd | fold ALFH -> BAFL (confirms my recollection) |
| PEL (Pakistan Electron) | PAEL, Pak Elektron Ltd | fold PEL -> PAEL |
| STL | STL, Supernet Technologies | ticker is STL (a listed company, not a bad ticker) |
| BBFL | BBFL, Big Bird Foods Ltd | ticker is BBFL (listed) |
| GCWL | GCWL, Ghani Chemworld Ltd | GCWL is Ghani Chemworld, NOT Gharibwal Cement: my section A line for GCWL (GWLC) was wrong; GCWL stays GCWL |
| GWCL | not seen (GWLC only in the older snapshot) | still Gharibwal Cement, GWLC |
| Apex Agro Processors and Atmospheric Gases (28) and Soya Supreme (12) | SOYASUP, "Agro Processors & ..." (logo APAG) | looks like ONE company; fold both to SOYASUP. The app cuts the full name off, so please confirm |
| SITARA | SPL = Sitara Peroxide, SPSL = Sitara Petroleum Services; Sitara Chemicals (SITC) not seen | the 9 SITARA rows are about Sitara Chemicals: SITC is still the candidate |
| POWER, CEPB, ATRL, AICL | all seen with the names I proposed | section A lines confirmed (PWC, PCL, POWC -> POWER; CPAL -> CEPB; ARL -> ATRL; ADAMJEE -> AICL) |
| MIIETF, MZNPETF, JSMFETF | seen (Mahaana Islamic Index, Meezan Pakistan ETF, JS Momentum Factor ETF) | verified: add to owner_confirmed |
| JBDC | JVDC, Javedan Corporation | likely a mis-hearing of JVDC; please confirm |
| PIBC | PIBTL, Pakistan International Bulk Terminal | possible; please confirm |
| TRT | TREET, Treet Corporation | possible; please confirm |
| PARCO | not in the list | Pak-Arab Refinery is not on the PSX board: put it in section D (not listed) |
| SECMC, DHPL, SERG, WAFI, BYCO, DHCL, GHAI, IPAX, IBL, INTER, DAPL, GAGL, SRG, SSG, AGR, SSOM, HINO, BNWM, NICL, ILP, HMB | not on the screens I was sent (the app list is long; the screenshots end near the lower-volume names) | no change from section A / B |
| Smile Industries, Park Power, Park Jan Power, Park GL / Glen Leasing | not seen | still need your answer |

Other facts visible in the screenshots (not stored anywhere): KSE-100 closed at 178,183, up 309 points (+0.17%),
16 Nov 2026 5:30 PM.

## G. More evidence from the second set of 20 screenshots (the lower-volume names, same close)
| Entity in the brain | Seen in the app | Reading |
|---|---|---|
| GWCL | GWLC, Gharibwal Cement | confirmed: GWCL -> GWLC |
| NIMIR | NICL, Nimir Industrial Che... (NRSL is Nimir Resins, seen earlier) | confirmed: NIMIR -> NICL |
| SSOIL | SSOM, SS Oil Mills Ltd | confirmed: SSOIL -> SSOM |
| BMWM, BWML, BWMT | BNWM, Bannu Woollen Mills | confirmed: all three -> BNWM |
| SITARA | SITC, Sitara Chemical Ind... | confirmed that SITC exists; the 9 rows describe Sitara Chemicals, so SITARA -> SITC |
| WAFI | WAFI, Wafi Energy Pakista... | WAFI is a listed ticker as written |
| IBL | IBLHL, IBL HealthCare Ltd; FIBLM = First IBL Modaraba | possible: IBL -> IBLHL. The stake fact (PKR 81 a share) does not match today's price of 40.92, so please confirm |
| JBDC | JVDC, Javedan Corporation; JDMT = Janana-de-Malucho | still unclear; JVDC is the closest |
| PIBC | PIBTL (Pakistan International Bulk Terminal) and PICT (Pakistan International Container Terminal) | two candidates; please choose |
| ISIL | ISIL, Ismail Industries Ltd | exists; no evidence that Smile Industries is Ismail, so Smile Industries stays unmatched |
| IBL, DHPL, SERG, SECMC, GHAI, DHCL, BYCO, DAPL, GAGL, IPAX, SRG, SSG, AGR, HPCO, Park..., Smile | not found in either set | still need your answer |

## H. Third set of screenshots (13 images, mostly repeats of the first two sets)
| Entity in the brain | Seen in the app | Reading |
|---|---|---|
| INTER | ILP, Interloop Ltd | confirmed: INTER -> ILP |
| MBL | HMB, Habib Metropolitan Bank | confirmed: MBL -> HMB |
| GHAI | GHNI, Ghandhara Industries (and GAL, Ghandhara Automobiles) | the fact says "Suzuki-linked auto maker, name not verified"; GHNI is Ghandhara Industries (trucks), not obviously Suzuki. Not folded; please say which, or leave |
| HGFA, NNAR, GAL, BFBIO, BFAGRO, MIIETF, MZNPETF, JSMFETF, STL, BBFL, WAFI | all visible with the names already recorded | no change |
Still not found on any of the 53 screenshots: DHPL, SERG, SECMC, DHCL, BYCO, DAPL, GAGL, IPAX, SRG, SSG, AGR, HPCO,
Smile Industries, Park Power / Park Jan Power, Park GL / Glen Leasing.


## Resolution (owner answers, 16 Nov 2026) - APPLIED to psx-library
Folded (alias file + Turso, rows unchanged at 25,763, entities 610 -> 590): ALFH -> BAFL, PEL -> PAEL, GWCL -> GWLC,
SSOIL -> SSOM, BMWM/BWML/BWMT -> BNWM, PWC/PCL/POWC -> POWER, CPAL -> CEPB, ARL -> ATRL, ADAMJEE -> AICL,
INTER -> ILP, MBL -> HMB, SITARA -> SITC, Smile Industries -> ISIL (Ismail Industries), Park Power and Park Jan Power
-> PKGP (Pakgen Power), Park GL Leasing and Park Glen Leasing -> PGLC (Pak Gulf Leasing Company).
Held for the owner: NIMIR ("NICL not registered separate": fold NIMIR into NICL, or leave NIMIR as it is?),
SOYASUP (Apex Agro / Soya Supreme), IBL -> IBLHL, JBDC, PIBC, TRT, HPCO, GHAI, GHAL -> GAL, the three ETFs for
owner_confirmed, and DHPL, SERG, SECMC, DHCL, BYCO, DAPL, GAGL, IPAX, SRG, SSG, AGR (not on any screen).
