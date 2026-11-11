# Provenance of the real statement fixtures

Both files are `pdftotext -layout` output of one page of a user-supplied annual report. Nothing was
edited except the trailing newline. The figures are the published ones.

| File | Source file supplied | Page | Statement |
|---|---|---|---|
| `real_manufacturing_unconsolidated_pl_pkr000_p39.txt` | `9acdac22-3.pdf` | 39 | Unconsolidated Statement of Profit or Loss, year ended June 30, 2026, PKR '000, with a Note column |
| `real_bank_consolidated_pl_usd000_p49.txt` | `4e37c56e-ubl271999-02.pdf` | 49 | Consolidated Profit and Loss Account, year ended December 31, 2025, US Dollars '000 (not rupees) |

These are annual-report pages, not PUCAR quarterly letterheads. The quarterly 4-column layout and the
newline-split labels are therefore synthetic and live in the test file.
