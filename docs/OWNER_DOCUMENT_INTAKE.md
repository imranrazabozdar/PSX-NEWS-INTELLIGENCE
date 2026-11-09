# Owner-assisted document intake (M2)

Status: **IMPLEMENTED and TESTED on synthetic PDFs.** No real company document has been processed yet.

## What it does
`engines/document_intake.py` takes a PDF the owner has downloaded in their own browser and:

1. Verifies it is a readable PDF with the approved reader (pdfplumber, `engines/pdf_reader.py`).
2. Stores the original bytes in a **vault outside the repository**, named by SHA-256. A file with the same
   hash and different bytes is never overwritten.
3. Reports an **identical document** (same SHA-256 already imported) as `duplicate`, and adds no rows.
4. Reports a **possible revision** (same company, report type, period and scope, different bytes) as
   `possible_revision` and does **not** import it, so the owner can confirm whether it restates the period.
5. Extracts statement lines (IS, BS, CF, EQ) with page numbers, records unparsed lines and scanned pages,
   and never invents values. A dash is `not_reported`, never zero.
6. Imports through `engines/financials.import_report`, which keeps the existing reconciliation,
   page-reference and promotion gates. Nothing is promoted by intake.

It makes **no network request**, performs **no OCR**, and sends nothing to an external service.

## Vault
Set `PSXNI_DOCUMENT_VAULT` to an absolute directory **outside** the repository, for example a private
folder in your home directory. Intake refuses a missing, relative or in-repository path.

## Required metadata
`company_ticker`, `doc_type` (annual, half_yearly, quarterly, nine_month), `period_end`, `scope`
(consolidated or unconsolidated), `currency`, `unit_scale`, `audit_status`, `columns` (period ends in the
order the PDF prints them), `retrieved_at_utc` (when the owner downloaded it), `filed_at_utc`, and a source:
`original_url` or `source_note`.

## Limits
- Extraction uses text layers only. Scanned pages are flagged for manual review; there is no OCR.
- Statement headings are found by phrase (`pdf_extraction.HEADERS`). Pages can be supplied explicitly with
  `statement_pages` when the heading is unusual.
- Accuracy on real documents is **not measured**. Validation requires documents the owner supplies and
  manually checked figures.
- Nothing from this workflow is stored in production, and no production migration is applied.

## Update (OGDC pilot finalisation): what intake now records

- **Layout:** side-by-side pages are split only when at least three rows agree on the same gutter, and no label or figure crosses it. Otherwise the page is flagged `uncertain` and never parsed. Each column keeps its own comparative periods.
- **Touching glyphs:** a 1–3 digit fragment joins a comma-grouped figure only when the glyph boxes touch (gap 0.0 pt). Every join is recorded with its original text in the report's provenance.
- **Structural subtotals:** recognised only by the rules in `engines/subtotals.py`, each with a rule version. The provenance carries one audit record per subtotal row: original text, explicit label (none), derived label, rule identifier and version, status, confidence and `label_origin` (`structurally_inferred` or `unresolved`).
- **Dates, kept separate:** `receipt_at_utc` (the upload date), `download_at_utc` (`unknown` unless supplied), `filed_at_utc` (the letter or publication date, not verified as the PUCARS timestamp) and the financial import time. A date-only receipt is recorded with `receipt_precision: date_only`; midnight is never presented as the upload time.
- **Duplicates:** same bytes for the same company, report type, period and scope is a duplicate. The same file for a different scope is imported. Same scope with different bytes is a possible revision and is not imported.
- **Vault and paths:** the vault must be absolute, outside the repository, and private (mode 0700). Symbolic links are refused as inputs and in the vault.
- **Atomicity:** an unknown canonical code is refused before any write, so a failed import leaves no source record.
- **Company mappings:** owner-approved OGDC mappings apply only to OGDC reports and only in their reporting context (see `docs/OGDC_MAPPING_REVIEW.md`).
