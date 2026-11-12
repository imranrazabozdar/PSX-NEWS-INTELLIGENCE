"""Archive migration command. Dry run by default. Real DDL needs an explicit, separate approval.

Usage:
  python -m scripts.archive_migrate --purpose archive     # dry run: plan only, changes nothing
  python -m scripts.archive_migrate --purpose archive --apply
      (DDL needs PSXNI_ARCHIVE_ALLOW_MIGRATION_DDL set to the approval value, this command only)

Uses PSXNI_ARCHIVE_TURSO_URL and PSXNI_ARCHIVE_TURSO_AUTH_TOKEN only. The operational database is never
opened.
The approval value is never printed. Output is JSON with the plan, checksums and post-state verification.
"""

from __future__ import annotations

import argparse
import json
import sys

from database.archive_migrations import archive_gate as gate
from database.connection import connect_archive


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--purpose", required=True, help="must be 'archive'")
    ap.add_argument("--apply", action="store_true", help="execute DDL (requires the approval variable)")
    args = ap.parse_args(argv)
    if args.purpose != gate.PURPOSE:
        print(json.dumps({"status": "refused", "reason": f"purpose must be {gate.PURPOSE!r}"}))
        return 2
    try:
        adb = connect_archive()
    except Exception as exc:  # configuration refusal: report the type and reason, never the values
        print(json.dumps({"status": "refused", "error": type(exc).__name__, "detail": str(exc)[:300]}))
        return 2
    try:
        if not args.apply:
            out = {"status": "dry_run", "plan": gate.plan(adb), "probe": gate.probe(adb)}
        else:
            result = gate.apply(adb, dry_run=False, purpose=args.purpose)
            out = {"status": "applied", **result}
            out["probe_after"] = gate.probe(adb)
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "stopped", "error": type(exc).__name__, "detail": str(exc)[:500],
                          "action": "stop; do not re-run; diagnose with the probe first"}))
        return 1
    finally:
        adb.close()


if __name__ == "__main__":
    sys.exit(main())
