"""Regenerate the real-report text fixtures from the owner's document vault (PSXNI_DOCUMENT_VAULT).

Reads PDFs ONLY from the vault, by SHA-256 file name. Writes text (never PDFs) under
tests/fixtures/real_reports/<report>/: one file per page (pdftotext -layout), one file per spread half
(pdf_reader.region_lines), and a manifest.json that records the source SHA-256, the pdftotext version and the
extractor version. Expected values and their page references are defined in EXPECTED below and are checked
against the fixture text by tests/test_real_report_regression.py.

Usage (from the repository root):
    PSXNI_DOCUMENT_VAULT=/secure/vault python -m scripts.regenerate_real_report_fixtures
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # noqa: S404 - fixed argv only, no shell
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "real_reports"

from engines import pdf_extraction as pe  # noqa: E402
from engines import pdf_reader as pr  # noqa: E402
from scripts.financial_intake import EXTRACTOR_VERSION  # noqa: E402

# report key -> (vault SHA-256 prefix, owner upload name, sections)
REPORTS = {
    "ubl_ar2025": {
        "sha_prefix": "23a11e71312b",
        "upload_name": "04688c48-ubl_report_1.pdf",
        "description": "United Bank Limited, Annual Report 2025 (unconsolidated statements)",
        "period_end": "2025-12-31", "columns": ["2025-12-31", "2024-12-31"], "unit_scale": 1000,
        "currency": "PKR", "consolidation": "unconsolidated", "framework": "bank",
        "pages": [42, 43, 44, 45, 98], "regions": [],
        "statement_pages": {"BS": [43], "IS": [44], "OCI": [44], "CF": [45], "EQ": [45]},
        "auditor_pages": [41, 42], "kam_pages": [42],
    },
    "luck_ar2026": {
        "sha_prefix": "3eddc4ac2db3",
        "upload_name": "9acdac22-3.pdf",
        "description": "Lucky Cement Limited, Annual Report 2026 (unconsolidated; 2025 comparatives)",
        "period_end": "2026-06-30", "columns": ["2026-06-30", "2025-06-30"], "unit_scale": 1000,
        "currency": "PKR", "consolidation": "unconsolidated", "framework": "corporate",
        "pages": [35, 38, 39, 40, 41, 42], "regions": [],
        "statement_pages": {"BS": [38], "IS": [39], "OCI": [40], "CF": [41], "EQ": [42]},
        "auditor_pages": [34, 35, 36, 37], "kam_pages": [35],
    },
    "ogdc_ar2026_standalone": {
        "sha_prefix": "8dec488c20d5",
        "upload_name": "81de4043-ogdc_100-190.pdf",
        "description": "Oil and Gas Development Company Limited, Annual Report 2026: standalone statements "
                       "(pages 5-10 of this upload part)",
        "period_end": "2026-06-30", "columns": ["2026-06-30", "2025-06-30"], "unit_scale": 1000,
        "currency": "PKR", "consolidation": "unconsolidated", "framework": "corporate",
        "pages": [5, 6, 8, 9, 10],
        "regions": [[5, "R"], [6, "L"], [6, "R"], [9, "L"], [9, "R"], [10, "L"], [10, "R"]],
        "statement_pages": {"BS": [8], "CF": [10]},
        "statement_regions": {"IS": [9, "L"], "OCI": [9, "R"], "EQ": [10, "L"]},
        "auditor_pages": [5], "kam_pages": [[5, "R"], [6, "L"], [6, "R"]],
    },
}


def vault_pdf(prefix: str) -> Path:
    vault = os.environ.get("PSXNI_DOCUMENT_VAULT", "")
    if not vault:
        raise SystemExit("PSXNI_DOCUMENT_VAULT is not set: the fixtures are generated only from the vault")
    root = Path(vault)
    if not root.is_absolute() or ROOT in root.resolve().parents or root.resolve() == ROOT:  # noqa: SIM102
        raise SystemExit("PSXNI_DOCUMENT_VAULT must be an absolute directory outside the repository")
    matches = sorted(root.glob(f"{prefix}*.pdf"))
    if len(matches) != 1:
        raise SystemExit(f"expected one vault file for prefix {prefix}, found {len(matches)}")
    return matches[0]


def pdftotext_version() -> str:
    """The Poppler version that produced the layout text. Recorded in every manifest."""
    binary = shutil.which("pdftotext")
    if binary is None:
        raise SystemExit("pdftotext (Poppler) is not installed")
    proc = subprocess.run(  # noqa: S603 - fixed argv, absolute path, no shell
        [binary, "-v"], capture_output=True, text=True, check=False
    )
    m = re.search(r"version\s+([\d.]+)", proc.stdout + proc.stderr)
    return m.group(1) if m else "unknown"


def pdf_page_count(pdf: Path) -> int:
    binary = shutil.which("pdfinfo")
    if binary is None:
        raise SystemExit("pdfinfo (Poppler) is not installed")
    proc = subprocess.run(  # noqa: S603 - fixed argv, absolute path, no shell
        [binary, str(pdf)], capture_output=True, text=True, check=False
    )
    m = re.search(r"Pages:\s+(\d+)", proc.stdout)
    if not m:
        raise SystemExit("could not read the page count")
    return int(m.group(1))


def main() -> None:
    version = pdftotext_version()
    for key, spec in REPORTS.items():
        pdf = vault_pdf(spec["sha_prefix"])
        sha = pe.sha256_file(pdf)
        out_dir = FIXTURES / key
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("page-*.txt"):
            old.unlink()
        written = []
        layout = pr.read_layout_pages(pdf)  # the same engine the production reader uses
        for page in spec["pages"]:
            name = f"page-{page:03d}.txt"
            (out_dir / name).write_text("\n".join(layout[page - 1]) + "\n", encoding="utf-8")
            written.append(name)
        for page, side in spec["regions"]:
            name = f"page-{page:03d}{side}.txt"
            (out_dir / name).write_text("\n".join(pr.region_lines(pdf, page, side)) + "\n", encoding="utf-8")
            written.append(name)
        manifest = {
            "report_key": key,
            "description": spec["description"],
            "source_sha256": sha,
            "source_upload_name": spec["upload_name"],
            "source_pdf_pages": pdf_page_count(pdf),
            "pdftotext_version": version,
            "extractor_version": EXTRACTOR_VERSION,
            "period_end": spec["period_end"],
            "columns": spec["columns"],
            "unit_scale": spec["unit_scale"],
            "currency": spec["currency"],
            "consolidation": spec["consolidation"],
            "framework": spec["framework"],
            "page_files": written,
            "statement_pages": spec["statement_pages"],
            "statement_regions": spec.get("statement_regions", {}),
            "auditor_pages": spec["auditor_pages"],
            "kam_pages": spec["kam_pages"],
        }
        text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        (out_dir / "manifest.json").write_text(text, encoding="utf-8")
        print(f"{key}: sha256 {sha[:16]} pages {len(spec['pages'])} regions {len(spec['regions'])}")


if __name__ == "__main__":
    main()
