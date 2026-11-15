"""Turn raw YouTube auto-caption .vtt files into clean, timestamped text, and cut work chunks. Pure Python.

Auto-captions are 'rolling': each cue repeats the previous line and adds a few words, and carries inline
timing tags. This collapses those repeats so every spoken line appears once. Chunks for extraction carry NO
timestamps (they only cost tokens); the full timestamped text stays in the per-video .txt files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_TS = re.compile(r"^\d\d:\d\d:\d\d\.\d{3} --> ")
_TAG = re.compile(r"<[^>]+>")
_SKIP = ("WEBVTT", "Kind:", "Language:", "NOTE")


def clean_vtt(text: str) -> list[tuple[str, str]]:
    """[(HH:MM:SS, line)] with rolling repeats collapsed."""
    lines: list[tuple[str, str]] = []
    cur, last = "00:00:00", ""
    for raw in text.splitlines():
        if _TS.match(raw):
            cur = raw[:8]
            continue
        if not raw.strip() or raw.startswith(_SKIP):
            continue
        t = _TAG.sub("", raw).strip()
        if not t or t == last:
            continue
        if lines and t.startswith(lines[-1][1]):
            lines[-1] = (lines[-1][0], t)  # the same sentence, now longer
        else:
            lines.append((cur, t))
        last = t
    return lines


def convert_dir(raw_dir: Path, out_dir: Path, dates: dict[str, str]) -> dict[str, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    info: dict[str, dict] = {}
    for f in sorted(raw_dir.glob("*.vtt")):
        vid, lang = f.name[:-4].rsplit(".", 1)
        lines = clean_vtt(f.read_text(encoding="utf-8", errors="replace"))
        body = "\n".join(f"[{c}] {t}" for c, t in lines)
        (out_dir / f"{vid}.txt").write_text(
            f"id: {vid}\ndate: {dates.get(vid, '?')}\nlang: {lang}\n\n{body}\n", encoding="utf-8")
        info[vid] = {"lang": lang, "chars": len(body), "plain": " ".join(t for _, t in lines)}
    return info


def make_chunks(videos: list[dict], max_chars: int) -> list[list[dict]]:
    """Group whole videos into chunks of at most max_chars of plain text. A video bigger than the limit
    gets a chunk of its own (never split: a split video loses its title and date context)."""
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for v in videos:
        n = len(v["plain"])
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(v)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


def render_chunk(videos: list[dict]) -> str:
    parts = []
    for v in videos:
        d = v["date"]
        parts.append("===== VIDEO =====\n"
                     f"TITLE: {v['title']}\nVIDEO_ID: {v['video_id']}\nURL: https://www.youtube.com/watch?v={v['video_id']}\n"
                     f"PUBLICATION_DATE: {d[:4]}-{d[4:6]}-{d[6:]}\n\n{v['plain']}\n")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, required=True, help="folder with <id>.<lang>.vtt files")
    parser.add_argument("--dates", type=Path, required=True, help="'<id> <YYYYMMDD>' lines")
    parser.add_argument("--titles", type=Path, required=True, help="JSON {id: {title: ...}}")
    parser.add_argument("--out", type=Path, required=True, help="work folder (clean/, chunks/)")
    parser.add_argument("--max-chars", type=int, default=30000)
    args = parser.parse_args(argv)
    dates = dict(line.split() for line in args.dates.read_text().splitlines() if line.strip())
    titles = json.loads(args.titles.read_text(encoding="utf-8"))
    info = convert_dir(args.raw, args.out / "clean", dates)
    videos = [{"video_id": v, "date": dates[v], "title": titles.get(v, {}).get("title", ""),
               "plain": i["plain"]} for v, i in sorted(info.items(), key=lambda kv: dates.get(kv[0], ""))]
    missing = [v["video_id"] for v in videos if not v["title"] or v["video_id"] not in dates]
    if missing:
        print(f"refused: {len(missing)} video(s) lack a title or a date, e.g. {missing[:3]}")
        return 2
    chunks = make_chunks(videos, args.max_chars)
    (args.out / "chunks").mkdir(exist_ok=True)
    for n, ch in enumerate(chunks, start=1):
        (args.out / "chunks" / f"c{n:03d}.md").write_text(render_chunk(ch), encoding="utf-8")
    (args.out / "chunks" / "manifest.json").write_text(json.dumps(
        {f"c{n:03d}": [v["video_id"] for v in ch] for n, ch in enumerate(chunks, start=1)}, indent=1))
    print(f"{len(videos)} videos -> {len(chunks)} chunk(s) of up to {args.max_chars} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
