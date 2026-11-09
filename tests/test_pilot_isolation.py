"""Production isolation: the pilot modules must not import network, cloud or database clients.

Checked statically from the import statements of each module."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    "engines/document_intake.py", "engines/financials.py", "engines/subtotals.py", "engines/pdf_reader.py",
    "engines/pdf_extraction.py", "engines/fundamentals.py", "scripts/ocr_evaluation.py",
]
FORBIDDEN = {"requests", "urllib", "http", "socket", "httpx", "aiohttp", "ftplib", "smtplib", "libsql",
             "libsql_client", "turso", "boto3", "google", "openai", "anthropic", "subprocess_ssh"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


@pytest.mark.parametrize("rel", MODULES)
def test_pilot_module_imports_no_network_cloud_or_database_client(rel):
    assert not (_imports(ROOT / rel) & FORBIDDEN), f"{rel} imports a forbidden client"


def test_subprocess_is_used_only_by_the_local_ocr_script():
    users = [rel for rel in MODULES if "subprocess" in _imports(ROOT / rel)]
    assert users == ["scripts/ocr_evaluation.py"]


def test_no_production_connection_string_or_token_in_pilot_code():
    for rel in MODULES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "libsql://" not in text and "turso.io" not in text and "PSXNI_TURSO" not in text, rel
