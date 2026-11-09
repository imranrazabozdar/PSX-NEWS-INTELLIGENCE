"""Bounded OCR evaluation (Tesseract only), for review. Not part of the intake pipeline.

Renders chosen PDF pages with the poppler `pdftoppm` binary, runs the Tesseract command line in TSV mode
(word-level confidence), and compares the recognised words with manually verified figures supplied as JSON.

Nothing is promoted and nothing is written to the project database. Processing is local: no network access.

Usage:
  python scripts/ocr_evaluation.py --pdf PATH --pages 2 3 --truth TRUTH.json --out OUTDIR [--dpi 300]
TRUTH.json: [{"page": 2, "label": "Cash and bank balances", "figure": "62,143,448"}, ...]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
from difflib import SequenceMatcher
from pathlib import Path


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"{name} is not installed; see docs/OCR_DESIGN.md for the required local binary")
    return path


def version(binary: str) -> str:
    # fixed local binary, argument list, no shell: S603 reviewed
    out = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)  # noqa: S603
    return (out.stdout or out.stderr).splitlines()[0].strip()


def render(pdf: Path, page: int, dpi: int, out_dir: Path) -> Path:
    prefix = out_dir / f"page{page}"
    cmd = [_tool("pdftoppm"), "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", "-singlefile",
           str(pdf), str(prefix)]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 - fixed local binary, no shell
    return prefix.with_suffix(".png")


def recognise(png: Path, out_dir: Path, psm: int = 6) -> list[dict]:
    tess = _tool("tesseract")
    cmd = [tess, str(png), str(out_dir / png.stem), "-l", "eng", "--psm", str(psm), "tsv"]
    subprocess.run(cmd, check=True, capture_output=True)  # noqa: S603 - fixed local binary, no shell
    words = []
    with open(out_dir / f"{png.stem}.tsv", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t", quoting=csv.QUOTE_NONE):
            text = (row.get("text") or "").strip()
            if text and row.get("conf") not in (None, "-1"):
                words.append({"text": text, "conf": float(row["conf"]), "left": int(row["left"]),
                              "top": int(row["top"])})
    return words


def _norm(s: str) -> str:
    return re.sub(r"[^0-9.]", "", s)


def compare(words: list[dict], truth: list[dict]) -> list[dict]:
    """Classify each manually verified figure as exact, misread (a close but wrong word) or missed.
    Brackets are kept in the OCR text and checked separately, so a dropped sign is visible in the record."""
    out = []
    for t in truth:
        want = _norm(t["figure"])
        exact = [w for w in words if _norm(w["text"]) == want]
        if exact:
            best = max(exact, key=lambda w: w["conf"])
            out.append({**t, "outcome": "exact", "ocr_text": best["text"], "word_confidence": best["conf"]})
            continue
        scored = [(SequenceMatcher(None, want, _norm(w["text"])).ratio(), w)
                  for w in words if _norm(w["text"])]
        ratio, near = max(scored, key=lambda x: x[0]) if scored else (0.0, None)
        if near is not None and ratio >= 0.8:
            out.append({**t, "outcome": "misread", "ocr_text": near["text"], "word_confidence": near["conf"],
                        "similarity": round(ratio, 3)})
        else:
            out.append({**t, "outcome": "missed", "ocr_text": None, "word_confidence": None})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True, type=Path)
    ap.add_argument("--pages", required=True, type=int, nargs="+")
    ap.add_argument("--truth", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--dpi", type=int, default=300)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True, mode=0o700)
    truth = json.loads(a.truth.read_text(encoding="utf-8"))
    report = {"engine": version(_tool("tesseract")), "renderer": "pdftoppm", "dpi": a.dpi, "psm": 6,
              "languages": "eng", "pages": {}}
    # renders and word-level TSV files are kept beside the report, so every result can be re-checked
    for p in a.pages:
        png = render(a.pdf, p, a.dpi, a.out)
        words = recognise(png, a.out)
        page_truth = [t for t in truth if t["page"] == p]
        res = compare(words, page_truth)
        report["pages"][str(p)] = {"words": len(words), "figures": res,
                                   "exact": sum(r["outcome"] == "exact" for r in res),
                                   "misread": sum(r["outcome"] == "misread" for r in res),
                                   "missed": sum(r["outcome"] == "missed" for r in res),
                                   "checked": len(res)}
    (a.out / "ocr_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: {x: v[x] for x in ("exact", "misread", "missed", "checked")}
                      for k, v in report["pages"].items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
