"""Tests for ADR-0001 independence enforcement (scripts/check_independence.py)."""

from __future__ import annotations

from pathlib import Path

from scripts import check_independence as ci

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def _rules(root: Path) -> set[str]:
    return {v.rule for v in ci.run(root)}


def test_this_repository_is_independent():
    violations = ci.run(REPO_ROOT)
    assert violations == [], "\n".join(map(str, violations))


def test_clean_fixture_passes(tmp_path):
    root = _make(tmp_path, {"app.py": "import os\nimport streamlit\nfrom config import x\n"})
    assert ci.run(root) == []


def test_reference_to_technical_engine_is_rejected(tmp_path):
    for variant in ("psx-intelligence-new-2026", "PSX_INTELLIGENCE_NEW_2026",
                    "../PSX-INTELLIGENCE-NEW-2026/backend"):
        root = _make(tmp_path / variant.replace("/", "_"), {"notes.md": f"see {variant}\n"})
        assert "project-reference" in _rules(root), variant


def test_technical_engine_module_import_is_rejected(tmp_path):
    root = _make(tmp_path, {"x.py": "from fire_engine import scan\nimport backend.api\n"})
    rules = [v.rule for v in ci.run(root)]
    assert rules.count("forbidden-import") == 2


def test_undeclared_import_is_rejected(tmp_path):
    root = _make(tmp_path, {"x.py": "import some_unknown_pkg\n"})
    assert "undeclared-import" in _rules(root)


def test_sys_path_manipulation_is_rejected(tmp_path):
    root = _make(tmp_path, {"x.py": "import sys\nsys.path.insert(0, '/elsewhere')\n"})
    assert "sys-path" in _rules(root)


def test_vcs_and_url_dependencies_are_rejected(tmp_path):
    root = _make(tmp_path, {
        "requirements.txt": (
            "streamlit>=1.40\n"
            "git+https://github.com/someone/other.git\n"
            "-e ../other-project\n"
            "--extra-index-url https://example.com/simple\n"
            "pkg @ https://example.com/pkg.whl\n"
        ),
    })
    violations = [v for v in ci.run(root) if v.rule == "non-pypi-dependency"]
    assert len(violations) == 4


def test_pyproject_dependency_must_be_reviewed(tmp_path):
    root = _make(tmp_path, {
        "pyproject.toml": '[project]\nname="x"\ndependencies=["requests>=2"]\n',
    })
    assert "unmapped-dependency" in _rules(root)


def test_workflow_cross_repo_checkout_and_foreign_secret_are_rejected(tmp_path):
    root = _make(tmp_path, {
        ".github/workflows/bad.yml": (
            "jobs:\n  a:\n    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n          repository: someone/other\n"
            "      - uses: someone/custom-action@v1\n"
            "      - run: echo ${{ secrets.TURSO_AUTH_TOKEN }}\n"
            "        env:\n          PYTHONPATH: ../other\n"
        ),
    })
    rules = _rules(root)
    assert {"workflow-checkout", "workflow-action", "workflow-secret", "pythonpath"} <= rules


def test_prefixed_secret_is_allowed(tmp_path):
    root = _make(tmp_path, {
        ".github/workflows/ok.yml": (
            "jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n"
            "      - run: echo ${{ secrets.PSXNI_TURSO_AUTH_TOKEN }} ${{ secrets.GITHUB_TOKEN }}\n"
        ),
    })
    assert ci.run(root) == []


def test_submodules_are_rejected(tmp_path):
    root = _make(tmp_path, {".gitmodules": "[submodule \"x\"]\n"})
    assert "submodule" in _rules(root)


def test_dynamic_and_path_based_imports_are_rejected(tmp_path):
    root = _make(tmp_path, {"x.py": (
        "import importlib\nimport runpy\n"
        "importlib.import_module('fire_engine')\n"
        "name = 'x'\nimportlib.import_module(name)\n"
        "__import__('backend')\n"
        "runpy.run_path('/somewhere/else.py')\n"
        "from importlib.util import spec_from_file_location\n"
        "spec_from_file_location('m', '/other/m.py')\n"
    )})
    rules = [v.rule for v in ci.run(root)]
    assert rules.count("dynamic-import") == 3
    assert rules.count("path-loading") == 2


def test_cloning_or_fetching_other_repos_is_rejected(tmp_path):
    root = _make(tmp_path, {
        "scripts/sync.sh": "git clone https://example.com/other.git\n",
        "x.py": "URL = 'https://raw.githubusercontent.com/someone/other/main/a.py'\n",
        ".github/workflows/w.yml": "jobs:\n  a:\n    steps:\n      - run: gh repo clone a/b\n",
    })
    assert sum(v.rule == "external-code-fetch" for v in ci.run(root)) == 3


def test_own_repository_url_is_allowed(tmp_path):
    root = _make(tmp_path, {"x.py": "URL = 'https://github.com/imranrazabozdar/psx-news-intelligence'\n"})
    assert ci.run(root) == []


def test_workflow_pip_install_outside_requirements_is_rejected(tmp_path):
    root = _make(tmp_path, {".github/workflows/w.yml": (
        "jobs:\n  a:\n    steps:\n"
        "      - run: pip install -r requirements-dev.txt\n"
        "      - run: pip install some-package\n"
        "      - run: pip install git+https://example.com/x.git\n"
    )})
    assert sum(v.rule == "workflow-pip" for v in ci.run(root)) == 2


def test_only_github_owned_actions_are_allowed(tmp_path):
    root = _make(tmp_path, {".github/workflows/w.yml": (
        "jobs:\n  a:\n    steps:\n      - uses: actions/setup-python@v5\n"
        "      - uses: gitleaks/gitleaks-action@v2\n"
    )})
    assert [v.rule for v in ci.run(root)] == ["workflow-action"]


def test_policy_floor_cannot_be_silently_weakened():
    """Minimum policy. Weakening it fails here AND in CI's base-branch guard run."""
    assert {"psxintelligencenew2026"} <= set(ci.FORBIDDEN_PROJECT_TOKENS)
    assert {"fire_engine", "backend", "analysis", "android", "streamlit_app",
            "wyckoff2_ui", "vol_engine_ui"} <= ci.FORBIDDEN_MODULES
    assert ci.ALLOWED_ACTION_OWNERS == {"actions"}
    assert ci.SECRET_PREFIX == "PSXNI_"  # noqa: S105
    assert ci.NAME_ALLOWLIST == {
        "README.md",
        "docs/adr/0001-independence-from-technical-engine.md",
        "scripts/check_independence.py",
        "tests/test_independence.py",
    }
    assert len(ci.ALL_CHECKS) >= 6


def test_spec_local_packages_are_allowed_but_forbidden_names_are_not(tmp_path):
    root = _make(tmp_path, {"x.py": "from database.connection import connect\nimport engines.x\n"})
    assert ci.run(root) == []
    root2 = _make(tmp_path / "b", {"x.py": "import backend\n"})
    assert "forbidden-import" in _rules(root2)
    assert not (ci.LOCAL_MODULES & ci.FORBIDDEN_MODULES)
