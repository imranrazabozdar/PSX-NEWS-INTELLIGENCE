#!/usr/bin/env python3
"""Check the *installed* environment, not just the declared files (ADR-0001).

The check fails if any installed distribution:
  * was installed from a VCS, a URL, a local directory or an editable checkout
    (PEP 610 `direct_url.json` present), i.e. not from the package index; or
  * is a declared dependency of this project that isn't actually installed.

pip-audit (run separately in CI) checks the same installed environment for known
vulnerabilities.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def non_index_installs() -> list[str]:
    problems = []
    for dist in metadata.distributions():
        raw = dist.read_text("direct_url.json")
        if not raw:
            continue
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            info = {}
        name = dist.metadata["Name"]
        kind = ("vcs" if "vcs_info" in info
                else "editable/local dir" if "dir_info" in info
                else "archive URL")
        problems.append(f"{name}: installed from {kind} ({info.get('url', '?')})")
    return problems


def declared_dependencies(root: Path = ROOT) -> set[str]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    deps = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        deps += group
    return {_canonical(re.split(r"[<>=!~\[; ]", d, maxsplit=1)[0]) for d in deps}


def missing_declared(root: Path = ROOT) -> list[str]:
    installed = {_canonical(d.metadata["Name"]) for d in metadata.distributions()}
    return sorted(declared_dependencies(root) - installed)


def main() -> int:
    problems = non_index_installs()
    missing = missing_declared()
    for m in missing:
        problems.append(f"{m}: declared in pyproject.toml but not installed")
    if problems:
        print("Installed-dependency source check FAILED:")
        for p in problems:
            print(f"  {p}")
        return 1
    count = sum(1 for _ in metadata.distributions())
    print(f"Installed-dependency source check passed: {count} distributions, all from the index.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
