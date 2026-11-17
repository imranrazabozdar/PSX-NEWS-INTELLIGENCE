"""Schema discovery for the technical-engine link (ADR-0008): table and column NAMES only. Stores nothing,
reads no data tables. Prints a compact schema for the owner to approve as Schedule A."""

from __future__ import annotations

import sys

from engines import technical_link as tl


def main() -> int:
    try:
        link = tl.connect()
    except tl.LinkError as exc:
        print(f"refused: {exc}")
        return 1
    print(f"target host: {link.host} (read only; schema names only; nothing stored)")
    tables = link.tables()
    print(f"{len(tables)} tables/views")
    for name, kind in tables:
        cols = link.columns(name)
        print(f"TECH_SCHEMA {kind} {name}: " + ", ".join(
            f"{c['name']}:{c['type'] or '?'}{'*' if c['pk'] else ''}" for c in cols))
    print(f"usage: {link.db.usage()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
