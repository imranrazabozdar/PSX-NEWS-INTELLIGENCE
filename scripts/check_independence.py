#!/usr/bin/env python3
"""Enforce ADR-0001: this project stays independent of the existing technical engine.

The check fails (exit code 1) if the repository contains any of these:
  1. A reference to the technical-engine repository name, outside an allowlist of
     documents that describe the separation itself.
  2. A Python import that isn't the standard library, a local package, or a declared
     dependency. This includes any import of the technical engine's modules.
  3. Changes to sys.path, or PYTHONPATH set in a workflow (ways to load outside code).
  4. A dependency installed from a URL, VCS, local path or custom package index.
  5. A GitHub Actions workflow that checks out another repository, uses an action from a
     non-allowlisted owner, or reads a secret without the PSXNI_ prefix.
  6. Git submodules.
  7. Dynamic imports / loading code from file paths, and cloning or fetching code from
     other repositories in scripts or workflows; workflow pip installs other than
     requirements*.txt.

In pull requests, CI also runs the copy of this script from the *base* branch, so a PR
cannot weaken the rules and pass the check with the weakened copy at the same time.

Run it with:  python scripts/check_independence.py [repo_root]
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

# --- Policy ---------------------------------------------------------------------------

# Normalised (lower-case, alphanumerics only) forms of forbidden project identifiers.
FORBIDDEN_PROJECT_TOKENS = ("psxintelligencenew2026",)

# Files allowed to *name* the technical engine, to document and enforce the separation.
NAME_ALLOWLIST = {
    "README.md",
    "docs/adr/0001-independence-from-technical-engine.md",
    "scripts/check_independence.py",
    "tests/test_independence.py",
}

# Top-level module names of the technical engine. Importing them is always forbidden,
# even if a module with that name were added to this repo later.
FORBIDDEN_MODULES = {
    "fire_engine",
    "wyckoff2_ui",
    "vol_engine_ui",
    "streamlit_app",
    "backend",
    "analysis",
    "android",
}

# Declared third-party distribution name -> importable top-level module names.
THIRD_PARTY_IMPORTS = {
    "streamlit": {"streamlit"},
    "python-dotenv": {"dotenv"},
    "pytest": {"pytest", "_pytest"},
    "ruff": set(),
    "pip-audit": set(),
}

# Local top-level packages/modules of THIS project (spec section 13 layout). Adding a new
# top-level package requires changing this list in its own PR, because CI also runs the
# base branch's copy of this guard.
LOCAL_MODULES = {"app", "config", "scripts", "tests",
                 "database", "collectors", "engines", "models", "prompts", "pages"}

ALLOWED_ACTION_OWNERS = {"actions"}
ALLOWED_SECRETS = {"GITHUB_TOKEN"}
SECRET_PREFIX = "PSXNI_"  # noqa: S105 - a name prefix, not a secret

TEXT_SUFFIXES = {
    ".py", ".md", ".txt", ".toml", ".yml", ".yaml", ".cfg", ".ini", ".json",
    ".sh", ".bat", ".env", ".example", ".sql", "",
}

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: [{self.rule}] {self.detail}"


# --- File discovery -------------------------------------------------------------------


def list_files(root: Path) -> list[str]:
    """Tracked + untracked-but-not-ignored files (git), or a filesystem walk."""
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],  # noqa: S607
            cwd=root, capture_output=True, text=True, check=True,
        ).stdout
        files = [f for f in out.splitlines() if f and (root / f).is_file()]
        if files:
            return sorted(files)
    except (OSError, subprocess.CalledProcessError):
        pass
    result = []
    for p in root.rglob("*"):
        if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            result.append(p.relative_to(root).as_posix())
    return sorted(result)


def _read(root: Path, rel: str) -> str | None:
    try:
        return (root / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# --- Rules ----------------------------------------------------------------------------


def check_project_references(root: Path, files: list[str]) -> list[Violation]:
    out = []
    for rel in files:
        if rel in NAME_ALLOWLIST or Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = _read(root, rel)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            norm = _normalise(line)
            for token in FORBIDDEN_PROJECT_TOKENS:
                if token in norm:
                    out.append(Violation(rel, i, "project-reference",
                                         "reference to the independent technical engine"))
    return out


def _stdlib() -> set[str]:
    return set(sys.stdlib_module_names) | {"__future__"}


def _allowed_imports() -> set[str]:
    allowed = set(LOCAL_MODULES) | _stdlib()
    for mods in THIRD_PARTY_IMPORTS.values():
        allowed |= mods
    return allowed


def check_python_imports(root: Path, files: list[str]) -> list[Violation]:
    out = []
    allowed = _allowed_imports()
    for rel in files:
        if not rel.endswith(".py"):
            continue
        text = _read(root, rel)
        if text is None:
            continue
        try:
            tree = ast.parse(text, filename=rel)
        except SyntaxError as exc:
            out.append(Violation(rel, exc.lineno or 0, "syntax", str(exc)))
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name in FORBIDDEN_MODULES:
                    out.append(Violation(rel, node.lineno, "forbidden-import",
                                         f"'{name}' is a technical-engine module"))
                elif name not in allowed:
                    out.append(Violation(rel, node.lineno, "undeclared-import",
                                         f"'{name}' is not stdlib, local or a declared dependency"))
            # Dynamic imports and loading code from file paths
            if isinstance(node, ast.Call):
                fname = _call_name(node.func)
                if fname in {"importlib.import_module", "import_module", "__import__"}:
                    arg = node.args[0] if node.args else None
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        mod = arg.value.split(".")[0]
                        if mod in FORBIDDEN_MODULES or mod not in allowed:
                            out.append(Violation(rel, node.lineno, "dynamic-import",
                                                 f"dynamic import of '{mod}' is not allowed"))
                    else:
                        out.append(Violation(rel, node.lineno, "dynamic-import",
                                             "non-literal dynamic import is forbidden"))
                elif fname in {"runpy.run_path", "run_path", "spec_from_file_location",
                               "importlib.util.spec_from_file_location", "SourceFileLoader",
                               "importlib.machinery.SourceFileLoader", "site.addsitedir",
                               "addsitedir"}:
                    out.append(Violation(rel, node.lineno, "path-loading",
                                         f"'{fname}' loads code from a path and is forbidden"))
            # sys.path manipulation
            if isinstance(node, ast.Attribute) and node.attr in {"insert", "append", "extend"}:
                v = node.value
                if (isinstance(v, ast.Attribute) and v.attr == "path"
                        and isinstance(v.value, ast.Name) and v.value.id == "sys"):
                    out.append(Violation(rel, node.lineno, "sys-path",
                                         "modifying sys.path is forbidden"))
    return out


def _call_name(func: ast.expr) -> str:
    parts = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    return ".".join(reversed(parts))


_REQ_BAD =re.compile(r"(://|^\s*-e\s|^\s*--(extra-)?index-url|^\s*--find-links|^\s*\.{0,2}/|\s@\s)")


def check_dependencies(root: Path, files: list[str]) -> list[Violation]:
    out = []
    for rel in files:
        name = Path(rel).name
        if not (name.startswith("requirements") and name.endswith(".txt")):
            continue
        text = _read(root, rel) or ""
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.split("#", 1)[0].strip()
            if not stripped or stripped.startswith("-r "):
                continue
            if _REQ_BAD.search(stripped):
                out.append(Violation(rel, i, "non-pypi-dependency", stripped))
    if "pyproject.toml" in files:
        data = tomllib.loads(_read(root, "pyproject.toml") or "")
        project = data.get("project", {})
        deps = list(project.get("dependencies", []))
        for group in project.get("optional-dependencies", {}).values():
            deps += group
        declared = set(THIRD_PARTY_IMPORTS)
        for dep in deps:
            if "://" in dep or " @ " in dep or "@" in dep.split(";")[0]:
                out.append(Violation("pyproject.toml", 0, "non-pypi-dependency", dep))
            dist = re.split(r"[<>=!~\[; ]", dep, maxsplit=1)[0].strip().lower()
            if dist not in declared:
                out.append(Violation("pyproject.toml", 0, "unmapped-dependency",
                                     f"'{dist}' must be added to THIRD_PARTY_IMPORTS after review"))
        if "tool" in data and "uv" in data["tool"] and "sources" in data["tool"]["uv"]:
            out.append(Violation("pyproject.toml", 0, "non-pypi-dependency", "[tool.uv.sources]"))
    return out


_USES = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)")
_REPOSITORY = re.compile(r"^\s*repository:\s*\S")
_SECRET = re.compile(r"secrets\.([A-Za-z_][A-Za-z0-9_]*)")
_PYTHONPATH = re.compile(r"PYTHONPATH")


def check_workflows(root: Path, files: list[str]) -> list[Violation]:
    out = []
    for rel in files:
        if not rel.startswith(".github/workflows/") or not rel.endswith((".yml", ".yaml")):
            continue
        text = _read(root, rel) or ""
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            m = _USES.match(line)
            if m:
                ref = m.group(1)
                if ref.startswith("./"):
                    pass
                else:
                    owner = ref.split("/", 1)[0].lower()
                    if owner not in ALLOWED_ACTION_OWNERS:
                        out.append(Violation(rel, i, "workflow-action",
                                             f"action owner '{owner}' is not allowlisted"))
            if _REPOSITORY.match(line):
                out.append(Violation(rel, i, "workflow-checkout",
                                     "checking out another repository is forbidden"))
            for secret in _SECRET.findall(line):
                if secret not in ALLOWED_SECRETS and not secret.startswith(SECRET_PREFIX):
                    out.append(Violation(rel, i, "workflow-secret",
                                         f"secret '{secret}' must use the {SECRET_PREFIX} prefix"))
            if _PYTHONPATH.search(line):
                out.append(Violation(rel, i, "pythonpath", "setting PYTHONPATH is forbidden"))
            if _PIP_INSTALL.search(line) and not _PIP_ALLOWED.search(line):
                out.append(Violation(rel, i, "workflow-pip",
                                     "workflows may only pip install from requirements*.txt"))
    return out


_PIP_INSTALL = re.compile(r"\bpip3?\s+install\b")
_PIP_ALLOWED = re.compile(
    r"\bpip3?\s+install\s+(-q\s+)?(--upgrade\s+pip\s*$|-r\s+requirements(-[a-z]+)?\.txt\s*$)"
)
_FETCH_CODE = re.compile(
    r"(\bgit\s+(clone|submodule|subtree|remote\s+add|fetch\s+https?://)|\bgh\s+repo\s+clone\b"
    r"|https?://(raw\.)?github(usercontent)?\.com/(?!imranrazabozdar/psx-news-intelligence\b)"
    r"[\w.-]+/[\w.-]+)",
    re.IGNORECASE,
)
_FETCH_ALLOWLIST = NAME_ALLOWLIST | {"README.md", "docs/SPECIFICATION.md"}


def check_external_code_fetch(root: Path, files: list[str]) -> list[Violation]:
    """No cloning/fetching other repositories in scripts, workflows or code."""
    out = []
    for rel in files:
        if rel in _FETCH_ALLOWLIST or Path(rel).suffix.lower() not in TEXT_SUFFIXES:
            continue
        if rel.endswith(".md"):
            continue  # prose may cite URLs; executable files may not fetch code
        text = _read(root, rel) or ""
        for i, line in enumerate(text.splitlines(), 1):
            if _FETCH_CODE.search(line):
                out.append(Violation(rel, i, "external-code-fetch",
                                     "fetching code from another repository is forbidden"))
    return out


def check_submodules(root: Path, files: list[str]) -> list[Violation]:
    if (root / ".gitmodules").exists():
        return [Violation(".gitmodules", 0, "submodule", "git submodules are forbidden")]
    return []


ALL_CHECKS = (
    check_project_references,
    check_python_imports,
    check_dependencies,
    check_workflows,
    check_submodules,
    check_external_code_fetch,
)


def run(root: Path) -> list[Violation]:
    files = list_files(root)
    violations: list[Violation] = []
    for check in ALL_CHECKS:
        violations.extend(check(root, files))
    return violations


def main(argv: list[str]) -> int:
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parents[1]
    violations = run(root)
    if violations:
        print("Independence check FAILED (see docs/adr/0001-*.md):")
        for v in violations:
            print(f"  {v}")
        return 1
    print("Independence check passed: no cross-project dependencies found.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
