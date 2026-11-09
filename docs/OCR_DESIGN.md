# Optional OCR for scanned statement pages (D8): design only

Status: **design proposal. Not implemented. No OCR dependency is added.** It is needed because the owner's FY2026
results annexure (SHA-256 `3156c593…d7a5`) has 15 of 16 pages with no text layer, so the approved reader extracts
nothing from them. Until an OCR capability is approved, those pages are refused (`extraction_failed`) and their
figures can only be entered by manual verification.

## 1. Principles
- **Local only.** Page images never leave the machine or the project vault. No cloud OCR, no hosted model, no
  external AI service. Nothing is uploaded.
- **Opt-in and explicit.** OCR runs only when a document is intaken with `ocr_pages` listed. It never runs
  silently for a page the reader can read.
- **No automatic promotion.** Every figure read by OCR is stored with `extraction_method = 'ocr'`,
  `review_status = 'pending'` and its confidence. Promotion to metrics is refused until the owner has accepted each
  OCR figure after comparing it with the page image.
- **Original preserved.** The vault copy is never modified. OCR output is a separate derived record that points to
  the original by SHA-256 and page number.

## 2. Pipeline
1. **Render** each listed page to an image at a fixed resolution (300 dpi proposed), recording DPI and the render
   library version.
2. **Recognise** with a local engine (section 5). Keep word-level text, bounding boxes and engine confidence.
3. **Structure** the words with the same column-detection and subtotal rules used for text pages (engines/
   pdf_reader.py layout detection and engines/subtotals.py). OCR text does not bypass the structural checks.
4. **Score** confidence per figure (section 3). Low-confidence figures are not stored as values: they are
   stored as `unreadable`, with the image crop reference, for manual entry.
5. **Verify arithmetically.** Figures that pass a block sum or a reconciliation identity raise the confidence;
   a figure that breaks one is flagged. Arithmetic cannot correct a figure, only flag it.
6. **Record provenance** for every figure: source SHA-256, page number, OCR engine name and version, model
   identifier and checksum, DPI, language set, the word box, the engine confidence and the review decision.
7. **Hand to review** (section 4). No figure reaches the financial tables as accepted.

## 3. Confidence scoring
- Engine word confidence (0–1) is aggregated per figure as the minimum over its digits and separators.
- A figure is **accepted for review display** only if its minimum word confidence is at least 0.90 and it passes
  the arithmetic checks; otherwise it is `unreadable`.
- Thresholds are proposals to be calibrated on owner-verified pages before use. Until calibration, every OCR figure
  is treated as pending review regardless of score.
- Digits are the risk: 6/8/0, 1/7 and the comma position. Grouping must match the Pakistani pattern (lakh grouping
  is accepted); an irregular grouping is flagged, never repaired.

## 4. Manual verification workflow
- The owner sees each OCR figure next to its cropped page image, with the extracted text, the page number and the
  confidence. The owner accepts, corrects or rejects it.
- Corrections are stored as a new record with the reviewer and time; the OCR value is kept, not overwritten.
- Only accepted figures may be promoted. A page with any rejected figure is marked `needs_review` as a whole.
- Acceptance is per figure. Batch acceptance of a page is not permitted, because it would hide single-digit errors.

## 5. Candidate engines and dependency implications
These are options to compare, not choices. None is installed, and each needs owner approval (as pdfplumber did, U3).

| Option | Licence | Runs locally | Dependency implication |
|---|---|---|---|
| Tesseract via a local binary | Apache-2.0 | Yes | A system package (not on PyPI). Wrapper and language data to be pinned. |
| OCRmyPDF (wraps Tesseract) | MPL-2.0 | Yes | Needs Ghostscript and Tesseract on the system. MPL terms to be reviewed. |
| RapidOCR (ONNX models) | Apache-2.0 | Yes | Pure-Python wheel plus onnxruntime and model files; models need checksums. |
| PaddleOCR / EasyOCR | Apache-2.0 | Yes | Large framework dependencies (PaddlePaddle or PyTorch). Heavy for this project. |

Recommendation for the first comparison: Tesseract, because it is mature and its output is well understood, and
RapidOCR, because it can be pinned as Python packages. Both must be tested on the owner's scanned page (image
only, not stored) and measured against manually verified figures before any choice.

Dependency and guard implications (for any option):
- Each new third-party import must be added to the reviewed list in `scripts/check_independence.py`, and every
  package must be pinned in `requirements*.txt` with a `pip-audit` pass.
- System binaries are not covered by `pip-audit`; their version and source must be recorded and reviewed.
- Model files need a SHA-256 checksum stored with the code, and must not be downloaded at run time.

## 6. Tests required before use
- Synthetic scanned pages with known text (controlled fixtures), including: a digit confusion case, a missing comma,
  a bracketed negative, a dash, a two-column page, and a skewed page.
- Owner-verified real pages (the FY2026 annexure, pages 2–3 first), compared figure by figure.
- Accuracy is reported only on real, manually verified pages, separately from synthetic results.

## 7. Out of scope
- No handwriting recognition. No signature or stamp interpretation. No automatic translation.
- No OCR of pages the reader can already read.


## Update (OGDC pilot finalisation): bounded Tesseract evaluation

Status: **evaluated on a small sample. Not approved for production or for a wider pilot without the conditions below.**

- Engine: tesseract 5.3.4 (Ubuntu package tesseract-ocr 5.3.4, language `eng`), installed in the development container only. No Python dependency was added; `scripts/ocr_evaluation.py` uses the Tesseract and `pdftoppm` command lines through the standard library.
- Renderer: poppler `pdftoppm` at 300 dpi. Page segmentation mode 6.
- Pages: FY2026 results annexure, pages 2 and 3 (scanned, no text layer). Local processing only; the original PDF is unchanged and remains in the owner's vault.
- Truth: 21 figures read manually from the page images, outside the OCR output.

| Outcome | Figures |
|---|---|
| Exact | 20 of 21 |
| Misread (close but wrong) | 1 (total assets: read as `22852,828,189_`, word confidence 0.0) |
| Missed | 0 |

Confidence observations:
- Exact figures carried word confidence from 42 to 97. 4 exact figure(s) fell below 90, so a 90 threshold would flag correct figures for review too (false alarms).
- The one misread carried confidence 0.0, so a confidence threshold would have caught it.
- Brackets were preserved in the two bracketed figures checked (for example `(147,693,389)`). The comparison normalises digits, so the sign is checked from the bracket, not by the digit match.

Recommendation: **Tesseract is usable only as a candidate for flagging and drafting. It is not suitable for automatic extraction.** Every OCR figure must be verified against the image. A wider pilot needs: a larger owner-verified sample (all statement pages of one annual report), a calibrated threshold, and a rule that any misread-like result (low confidence, or a total that fails its identity) forces manual entry. No production OCR activation is approved.

Reproduce: `python scripts/ocr_evaluation.py --pdf PATH --pages 2 3 --truth TRUTH.json --out DIR` (the truth file lists page, label and manually verified figure). The output directory keeps the renders, the word-level TSV and `ocr_report.json`.
