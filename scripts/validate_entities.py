"""Check every entity name in psx-library against the listed-company snapshot. Pure Python, no model.

Classes: ok (a listed ticker), pseudo (SECTOR:/MACRO:), known (already handled in entity_aliases.json),
bad_ticker (looks like a ticker but is not listed), exact (name equals a listed company's name),
near (name is a close spelling of a listed name; needs the owner's yes), name_only (no match).
Nothing is changed: this only reports. Fold confirmed names through docs/research/arn/entity_aliases.json.
"""
from __future__ import annotations

import collections
import difflib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DROP = re.compile(r"\b(limited|ltd|pvt|private|company|corporation|corp|co|pakistan|pak|the|of|and)\b")


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _DROP.sub(" ", name.lower())).strip()


def classify(entities: dict[str, int], listing: dict[str, str], aliases: dict) -> dict[str, list]:
    known = set(aliases.get("aliases", {})) | set(aliases.get("not_listed", []))
    known |= set(aliases.get("keep_as_name", []))
    delisted = aliases.get("delisted", [])
    known |= set(delisted)
    by_name = {norm(v): k for k, v in listing.items()}
    classes = ("ok", "pseudo", "known", "bad_ticker", "exact", "near", "name_only")
    out: dict[str, list] = {k: [] for k in classes}
    for ent, rows in entities.items():
        if ent.startswith(("SECTOR:", "MACRO:")):
            out["pseudo"].append((ent, rows))
        elif ent in listing:
            out["ok"].append((ent, rows))
        elif ent in known:
            out["known"].append((ent, rows))
        elif re.fullmatch(r"[A-Z0-9]{2,9}", ent):
            out["bad_ticker"].append((ent, rows))
        elif norm(ent) in by_name:
            out["exact"].append((ent, by_name[norm(ent)], rows))
        else:
            close = difflib.get_close_matches(norm(ent), list(by_name), n=1, cutoff=0.88)
            if close:
                out["near"].append((ent, by_name[close[0]], rows))
            else:
                out["name_only"].append((ent, rows))
    return out


def load_listing(path: Path) -> dict[str, str]:
    """Listed companies from the snapshot, plus symbols the owner confirmed are registered on PSX."""
    data = json.loads(path.read_text("utf-8"))
    listing = dict(data["companies"])
    for symbol, note in data.get("owner_confirmed", {}).items():
        if not symbol.startswith("_"):
            listing.setdefault(symbol, note)
    return listing


def main() -> int:
    from engines import library_db

    listing = load_listing(ROOT / "docs/research/psx_listed_companies.json")
    aliases = json.loads((ROOT / "docs/research/arn/entity_aliases.json").read_text("utf-8"))
    db = library_db.get_library_connection().db
    counts = collections.Counter(r["company"] for r in db.execute("SELECT company FROM research_fact"))
    result = classify(dict(counts), listing, aliases)
    for key, items in result.items():
        print(f"{key}: {len(items)}")
    for key in ("bad_ticker", "exact", "near"):
        for item in sorted(result[key], key=lambda x: -x[-1]):
            print(f"  {key}: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
