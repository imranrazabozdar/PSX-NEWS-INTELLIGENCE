# Manual import workflow (design only)

Status: **design proposal; not implemented.** It is for sources whose automated retrieval is
prohibited or unconfirmed: PSX documents and daily files, SBP/SECP/Commerce publications blocked
to automation, OGRA/NEPRA PDFs, OPEC reports, and company annual reports.

**Precondition:** the owner downloads files personally, through normal browser use.

**PSX documents: a personal-use download does not automatically authorise any of these:**
1. persistent storage in a private database;
2. bulk retention of documents;
3. historical backfilling;
4. LLM extraction (sending text to an external model);
5. reuse in an intelligence product.

**Written clarification from PSX is required before any manually downloaded PSX document enters
the persistent intelligence database or is sent to an external LLM.** Until then this workflow must
not be used for PSX documents. Other publishers follow their own terms, right by right (UNCONFIRMED
unless documented).

## Flow
1. **Drop.** The owner places files in a local import folder, or uploads them through a private,
   authenticated Streamlit page (Phase 6). Nothing is fetched by the system.
2. **Identify.** The owner selects the registry source (for example `psx_dps`, `sbp`, `ogra`) and the
   document type. They enter the publication date (with timezone) and, optionally, the original URL.
   The system records the import time, the owner as importer, and retrieval method `manual`.
3. **Hash and dedupe.** The system computes SHA-256 of the file bytes and checks it against existing
   `source_items.content_sha256` and the versions table. An identical file is a duplicate; a new file
   at the same URL is a new version (existing Phase 1/2 logic).
4. **Store per permission.**
   - **Metadata-only** mode by default: title, dates, hash, page count, document metadata via the
     existing `document_info`.
   - Original files are kept outside the database (local or private storage), **only** where the
     source's terms permit retention.
   - Excerpts of at most 1,000 characters are stored with page references.
5. **Extract.**
   - Text and tables come from text-based PDFs, Excel or CSV (a parser to be chosen; no dependency is
     added without approval).
   - Scanned or unreadable pages are flagged `unreadable`; there is no OCR guesswork without approval.
   - Each excerpt keeps its page number.
6. **Feed the pipeline.**
   - The item enters the existing source-item, extraction (Phase 3) and exposure-mapping (Phase 4)
     pipeline as a normal `source_item` with `retrieval_method = 'manual'`.
   - Evidence quotes must match the extracted text; numbers must match.
   - LLM processing runs **only** if the source's terms allow it (a per-source flag).
7. **Flag.**
   - Incomplete documents (missing pages, encrypted, image-only), unknown publication dates and
     possible duplicates go to the human-review queue.

## Required controls (when implemented)
- **Lifecycle:** a source needs a new `manual_import_permitted` state (or a review note) separate from
  automated `ACTIVE`. Manual import never enables automated collection.
- **Audit:** append-only import log (who, when, file hash, source, decision).
- **Size limits:** follow the Phase 2 `MAX_BYTES` principle. No large blobs are stored in Turso.
- **No redistribution:** imported documents are visible only in the private dashboard.

## Feasibility
- **Technical:** high. Most building blocks exist: hashing, versions, `document_info`, provenance
  fields, and the extraction and exposure pipeline.
- **New work:** an import entry point, text and table extraction, a per-source permission flag and the
  review page.
- **Legal:** depends on per-source confirmation, which is the critical path for PSX documents.
