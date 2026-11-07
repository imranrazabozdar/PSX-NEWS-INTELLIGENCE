# Phase 5 test strategy (design)

All tests run on throwaway local or CI SQLite (and SQLite 3.47 / libSQL compatibility runs), with
**synthetic sources (`is_synthetic = 1`) only**. Nothing is inserted into production Turso. Every
fixture is labelled `SYNTHETIC FIXTURE`, and every output carries `data_label = 'SYNTHETIC TEST DATA'`.

## 1. Fixture scenarios
| # | Scenario | Setup | Expected |
|---|---|---|---|
| S1 | Oil price shock (rise) | E&P with `product: crude`, refiner with `input: crude`, OMC without exposure | E&P +, refiner mixed, OMC unknown or sector-only scenario |
| S2 | Rate increase | borrower with floating debt; bank without repricing data | borrower −; bank unknown |
| S3 | PKR depreciation | exporter (FX revenue), importer, FX-debt holder | +, −, − respectively; separate mechanisms |
| S4 | Gas price increase | fertiliser (feedstock) with and without a documented pass-through order | − vs neutral/mixed |
| S5 | Tax or duty change | duty on product X; companies with and without X in scope | only the in-scope company is assessed |
| S6 | Company-specific positive and negative events | named-company events (corroborated) | direction from the event, exposure from the named mention |
| S7 | Mixed impact | one company with opposite documented exposures | mixed; review |
| S8 | Conflicting evidence | disputed event | scenario_only; direction mixed or unknown; review |
| S9 | Missing evidence | sector-only candidate | "exposure not established"; no direction |
| S10 | Revoked evidence | confirmed exposure, then source disabled | assessment → `needs_revalidation`; history kept |
| S11 | Stale evidence | `valid_to` or verification age past the threshold | `needs_revalidation` |
| S12 | Unknown direction | event with no stated change | direction unknown on every assessment |
| S13 | Indirect sector exposure | relationship or sector link | indirect; lower exposure confidence |
| S14 | Multiple events, same company | two events on one company | separate assessments; aggregate = mixed when opposed |
| S15 | Multiple companies, different exposure | one event, three exposure levels | different direction, magnitude and confidence per company |
| S16 | Quantification with units | synthetic `financial_metrics` + `commodity_prices` | formula output with units and sensitivity; mismatched units refused |
| S17 | Missing inputs | same without inputs | qualitative label; explicit `missing_inputs` |

## 2. Properties each test proves
- **No unsupported conclusions:**
  - an `unverified`, `potential`, `rejected` or `needs_revalidation` exposure never yields
    `confirmed_conclusion`;
  - sector-only exposure never yields a signed direction.
- **Provenance retained:** each assessment links event revision, candidate revision, evidence,
  `ruleset_version`, `transmission_version` and `calculation_version`.
- **Revocation:**
  - source disable, retraction, relationship supersession and expiry each move dependent assessments
    to `needs_revalidation`;
  - consumers reading the current view never see them as valid.
- **Unknown stays unknown:** property-style tests over all rules confirm that an unknown factor gives an
  unknown direction.
- **Differentiation:** S15 asserts at least two distinct assessments for the same event.
- **Idempotency:** running the same inputs twice creates no new rows or revisions; a version bump
  creates new records.
- **Traceability:** an old assessment still reports the versions it used after a rule change.
- **Database integrity (direct-SQL bypass tests, as in Phase 4):**
  - no confirmed conclusion without an acceptance review;
  - no forged inputs;
  - append-only history.
- **Labels:** qualitative, deterministic and quantified outputs are never confused, and there is no
  `market_check` other than `not_evaluable`.

## 3. Regression
- The full existing suite (Phases 0–4) must stay green.
- Compatibility runs on SQLite 3.47.0 and the libSQL engine, in a scratch environment.

## 4. Acceptance criteria (proposed for the Phase 5 gate)
1. All of S1–S17 pass, plus the bypass and regression tests.
2. Formulas are tested with units (spec §14), and there are no unsupported quantitative estimates.
3. Every assessment carries complete provenance and an evidence eligibility status.
4. No real-company claim is produced. This is explicitly stated as not operational until sources are
   approved.
