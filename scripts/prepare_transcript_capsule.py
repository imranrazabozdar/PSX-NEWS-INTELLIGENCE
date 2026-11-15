"""Turn extracted transcript rows into ONE validated capsule for scripts/absorb_sector_capsule.py.

The archive these rows come from carries NO publication dates. That is handled explicitly rather than
papered over:

* `source_date` is the date the ARCHIVE WAS CAPTURED, not the date the video was published, and
  `source_name` says "undated" so the two are never confused.
* `period` carries the era the CLAIM belongs to, when the speaker stated one ("FY25", "Budget 2026").
  A time-bound claim with no stated period was dropped at extraction: an undated snapshot of a price
  or a policy rate would quietly mix eras, which is the one thing this archive must not do.

Near-duplicates are collapsed. One analyst repeating a point across 200 videos should leave ONE row,
so a later capsule about the same company adds knowledge instead of restating it.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from engines import research_facts as rf

ARCHIVE_CAPTURE_DATE = "2026-11-14"
SCHEMA_KEYS = set(rf.COLUMNS)
_WORD = re.compile(r"[a-z0-9]+")
# absorb_sector_capsule refuses a source that looks like a placeholder; a real title may contain "..."
_ELLIPSIS = re.compile(r"\.{3,}")


_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def normalise(text: str) -> frozenset[str]:
    """The comparison key for near-duplicate detection: significant words, plus every number as "#<n>".

    Numbers are kept on purpose. A key that dropped them could not tell "the policy rate is 22%" from "the
    policy rate is 11%", and a newer figure would be thrown away as a repeat of the older one.
    """
    words = {w for w in _WORD.findall(text.lower()) if len(w) > 3 and not w.isdigit()}
    numbers = {"#" + n.replace(",", "").rstrip(".") for n in _NUMBER.findall(text)}
    return frozenset(words | numbers)


def is_near_duplicate(a: frozenset[str], b: frozenset[str], threshold: float = 0.75) -> bool:
    """A restatement, not a change: the same numbers and mostly the same words.

    Two rows that disagree on any number are different facts however alike they read, so both are kept.
    """
    if not a or not b:
        return False
    if {t for t in a if t.startswith("#")} != {t for t in b if t.startswith("#")}:
        return False
    wa, wb = {t for t in a if not t.startswith("#")}, {t for t in b if not t.startswith("#")}
    if not wa or not wb:
        return a == b
    return len(wa & wb) / min(len(wa), len(wb)) >= threshold


# A company must have ONE entity key or its profile splits in two. Auto-captions and free-text naming
# produce variants ("HALEON" vs "Haleon Pakistan"), so a name is folded onto a ticker already in use
# when it reduces to the same word. Only these suffixes are stripped: nothing is guessed from scratch.
_COMPANY_SUFFIX = re.compile(
    r"\b(pakistan|limited|ltd|plc|company|corporation|corp|industries|industry|group)\b", re.I)


def entity_key(name: str) -> str:
    """The comparison key for deciding two spellings are the same company."""
    return re.sub(r"[^a-z0-9]", "", _COMPANY_SUFFIX.sub("", name.lower()))


def build_alias_map(companies: list[str]) -> dict[str, str]:
    """Fold each company name onto the shortest spelling that reduces to the same key.

    The shortest form is preferred because a ticker ("HALEON") is shorter than the prose name it was
    written out as ("Haleon Pakistan"), and a ticker is what every other part of this system queries by.
    """
    groups: dict[str, list[str]] = {}
    for name in set(companies):
        key = entity_key(name)
        if key:
            groups.setdefault(key, []).append(name)
    alias: dict[str, str] = {}
    for variants in groups.values():
        if len(variants) < 2:
            continue
        canonical = sorted(variants, key=lambda n: (len(n), n))[0]
        for name in variants:
            if name != canonical:
                alias[name] = canonical
    return alias


# The archive is one CHANNEL, not one speaker. Some videos are hosted by someone else ("Shafy's Weekly") or
# feature a guest ("Irfan Khan explains", "ft. Ammar Siddiqui"), and a transcript does not say who is talking.
# So provenance states what is certain (the channel) and flags titles where the speaker may differ, instead
# of crediting every view to the channel's owner.
_OTHER_SPEAKER = re.compile(r"shafy|\bft\b\.?|@|explains|interview|guest|masterclass|alumni", re.I)
_TITLE_IN_SOURCE = re.compile(r"'(.+)'")


def attribution(source_name: str) -> str:
    match = _TITLE_IN_SOURCE.search(source_name)
    title = match.group(1) if match else source_name
    note = "; speaker may be a host or guest, not the channel owner" if _OTHER_SPEAKER.search(title) else ""
    return f"Abdul Rehman Najam channel, '{title}' (YouTube transcript, undated{note})"


def convert(row: dict[str, Any], dated: dict[str, Any] | None = None) -> dict[str, Any]:
    """One extracted row to one research_fact row. Raises ResearchFactError on anything malformed.

    `dated` switches to a channel whose videos carry VERIFIED upload dates: {"channel": name, "videos":
    {video_id: (title, "YYYY-MM-DD")}}. The row then takes the real video date as `source_date` and the
    source says so, instead of the "undated" archive handling below.
    """
    if dated is not None:
        return _convert_dated(row, dated)
    source = _ELLIPSIS.sub("…", str(row.get("source_name", "")).strip())
    out = {
        "company": str(row.get("company", "")).strip(),
        "topic": str(row.get("topic", "")).strip(),
        "fact_text": " ".join(str(row.get("fact_text", "")).split()),
        "value": row.get("value") if isinstance(row.get("value"), (int, float)) else None,
        "unit": (str(row["unit"]).strip() or None) if row.get("unit") else None,
        "period": (str(row["period"]).strip() or None) if row.get("period") else None,
        "source_name": source,
        "source_url": (str(row["source_url"]).strip() or None) if row.get("source_url") else None,
        "source_date": ARCHIVE_CAPTURE_DATE,
        "as_of": None,
        "confidence": str(row.get("confidence", "analyst_view")).strip(),
        "created_at": f"{ARCHIVE_CAPTURE_DATE}T00:00:00Z",
    }
    if "undated" not in out["source_name"].lower():
        raise rf.ResearchFactError(f"source must declare it is undated: {out['source_name'][:60]!r}")
    out["source_name"] = attribution(out["source_name"])
    return rf.validate_fact(out)


def _convert_dated(row: dict[str, Any], dated: dict[str, Any]) -> dict[str, Any]:
    vid = str(row.get("video_id", "")).strip()
    if vid not in dated["videos"]:
        raise rf.ResearchFactError(f"video {vid!r} has no verified date: row refused")
    title, day = dated["videos"][vid]
    title = _ELLIPSIS.sub("…", title)
    return rf.validate_fact({
        "company": str(row.get("company", "")).strip(),
        "topic": str(row.get("topic", "")).strip(),
        "fact_text": " ".join(str(row.get("fact_text", "")).split()),
        "value": row.get("value") if isinstance(row.get("value"), (int, float)) else None,
        "unit": (str(row["unit"]).strip() or None) if row.get("unit") else None,
        "period": (str(row["period"]).strip() or None) if row.get("period") else None,
        "source_name": f"{dated['channel']}, '{title}' (YouTube, {day})",
        "source_url": f"https://www.youtube.com/watch?v={vid}",
        "source_date": day,
        "as_of": None,
        "confidence": str(row.get("confidence", "analyst_view")).strip(),
        "created_at": f"{day}T00:00:00Z",
    })


def _exclusions(path: Path | None) -> set[tuple[str, frozenset[str]]]:
    """Rows a person has ruled out, as (video_id, word bag). Matching on words, not exact text, survives
    the whitespace normalisation the rows go through."""
    if path is None:
        return set()
    return {(str(e["video_id"]), normalise(str(e["fact_text"]))) for e in json.loads(path.read_text("utf-8"))}


def build(in_dir: Path | list[Path], out_path: Path, exclude: Path | None = None,
          dated: dict[str, Any] | None = None) -> int:
    dirs = [in_dir] if isinstance(in_dir, Path) else list(in_dir)
    files = sorted(f for d in dirs for f in glob.glob(str(d / "*.json")))
    if not files:
        print(f"no extracted rows found in {', '.join(str(d) for d in dirs)}")
        return 1
    excluded = _exclusions(exclude)
    dropped_excluded = 0
    kept: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], list[frozenset[str]]] = {}
    read = dropped_dup = dropped_bad = 0
    problems: Counter[str] = Counter()
    raw_companies = [str(r.get("company", "")) for path in files
                     for r in json.loads(Path(path).read_text(encoding="utf-8"))]
    alias = build_alias_map([c for c in raw_companies if c])
    from scripts import apply_entity_aliases

    official = apply_entity_aliases.load()
    if alias:
        print(f"folded {len(alias)} company name variant(s) onto one spelling:")
        for variant, canonical in sorted(alias.items())[:12]:
            print(f"   {variant!r} -> {canonical!r}")
    for path in files:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
        for raw in rows:
            read += 1
            try:
                row = convert(raw, dated)
            except rf.ResearchFactError as exc:
                dropped_bad += 1
                problems[str(exc)[:70]] += 1
                continue
            row["company"] = alias.get(row["company"], row["company"])
            row["company"] = official.get(row["company"], row["company"])  # name -> PSX ticker
            key = (row["company"], row["topic"].split(".", 1)[0])
            words = normalise(row["fact_text"])
            vid = str(raw.get("video_id", ""))
            if any(v == vid and w == words for v, w in excluded):
                dropped_excluded += 1
                continue
            if any(is_near_duplicate(words, prior) for prior in seen.get(key, [])):
                dropped_dup += 1
                continue
            seen.setdefault(key, []).append(words)
            kept.append(row)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(kept, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"read {read} row(s) from {len(files)} file(s)")
    print(f"  dropped as malformed : {dropped_bad}")
    for reason, n in problems.most_common(5):
        print(f"      {n:4d} x {reason}")
    print(f"  dropped as near-dupe : {dropped_dup}")
    print(f"  dropped as excluded  : {dropped_excluded}")
    print(f"  kept                 : {len(kept)}  ->  {out_path}")
    print("\ntop entities:")
    for company, n in Counter(r["company"] for r in kept).most_common(25):
        print(f"   {company:28} {n}")
    print("\ntopic families:")
    for fam, n in Counter(r["topic"].split(".", 1)[0] for r in kept).most_common():
        print(f"   {fam:28} {n}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--in-dir", required=True, type=Path, action="append",
                        help="folder of extracted rows; repeat to combine several")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--exclude", type=Path, default=None,
                        help="JSON list of {video_id, fact_text} rows to leave out")
    parser.add_argument("--channel", default=None, help="channel name, for a dated channel")
    parser.add_argument("--dates", type=Path, default=None, help="'<id> <YYYYMMDD>' lines (dated channel)")
    parser.add_argument("--titles", type=Path, default=None, help="JSON {id: {title}} (dated channel)")
    args = parser.parse_args(argv)
    dated = None
    if args.channel or args.dates or args.titles:
        if not (args.channel and args.dates and args.titles):
            parser.error("--channel, --dates and --titles go together")
        titles = json.loads(args.titles.read_text(encoding="utf-8"))
        dated = {"channel": args.channel, "videos": {
            v: (titles[v]["title"], f"{d[:4]}-{d[4:6]}-{d[6:]}")
            for v, d in (line.split() for line in args.dates.read_text().splitlines() if line.strip())
            if v in titles and "title" in titles[v]}}
    return build(args.in_dir, args.out, args.exclude, dated)


if __name__ == "__main__":
    sys.exit(main())
