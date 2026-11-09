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
