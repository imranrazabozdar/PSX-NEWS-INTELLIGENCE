"""PSX News Intelligence Council V1: the DRY-RUN runner. No analytical result is written to production.

    python -m scripts.council_news_dryrun --mode auto      # one execution (after each collector run)
    python -m scripts.council_news_dryrun --mode ten       # the 10-real-headline review (writes files only)
    python -m scripts.council_news_dryrun --mode report    # the seven-day report from the ledger

The database connection is read only (any non-SELECT statement raises) and must be recognisably psx-library,
or the run stops. Budgets, the queue and the LLM call log live in the council ledger file
(PSXNI_COUNCIL_LEDGER).
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from engines import announcement_events, library_db, market_calendar
from engines import council_ledger as cl
from engines import council_news as cn
from engines import news_importance as ni
from scripts import build_news_capsule as bnc
from scripts import council_run


def _calendar():
    try:
        return market_calendar.load_calendar()
    except Exception:  # noqa: BLE001 - no usable calendar leaves holiday and hours unknown, never guessed
        return None


def _step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def _connect():
    conn = library_db.get_library_connection()  # the target guard runs here and refuses any other database
    return cn.ReadOnlyDB(conn.db), conn.host


def _records_path(ledger_file: Path) -> Path:
    return ledger_file.with_name("records.jsonl")


def run_auto(args: argparse.Namespace, ledger: cl.Ledger) -> int:
    now = datetime.now(UTC)
    db, host = _connect()
    cn.assert_library_identity(db)
    print(f"database: {host} (read only)")
    out = cn.execution(
        db=db,
        env=os.environ,
        ledger=ledger,
        now=now,
        exec_id=args.exec_id or f"exec-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}",
        vocab=bnc.load_vocabulary(db),
        signals_for=lambda d, n: cn.baseline_signals(d, n, bnc.build),
        build_pack=council_run.build_pack,
        calendar=_calendar(),
        pack_db=lambda: _connect()[0],
        announcement_events=lambda _d, n: announcement_events.build(_connect()[0], n),
    )
    rec_file = _records_path(ledger.path)
    with open(rec_file, "a", encoding="utf-8") as fh:
        for r in out["records"]:
            fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
            print("COUNCIL_DRYRUN_RECORD " + json.dumps(r, ensure_ascii=False, sort_keys=True))
    s = out["summary"]
    print("COUNCIL_DRYRUN_EXECUTION " + json.dumps(s, sort_keys=True))
    lines = [
        f"### Council dry run: {s['time']['pkt_day']} {s['time'].get('pkt_time', '')} PKT",
        f"- headlines read {s['headlines_read']}, events {s['events']}, flagged {s['flagged']}, "
        f"queue changes {s['queue_changes']}",
        f"- council runs this execution {s['ran']} (cap {s['cap_exec']}); "
        f"today {s['runs_today']} of {s['cap_day']}",
        f"- waiting in queue {s['pending_after']} (needing review {s['needs_review']}); baseline: "
        f"{s['baseline'].get('baseline')}",
    ]
    for r in out["records"]:
        a = r.get("assessment") or {}
        names = (
            ", ".join(f"{c['entity']}={c['consensus']}" for c in a.get("affected_companies", [])) or "none"
        )
        lines.append(
            f"- {r['outcome']}: {r['event']['headline'][:90]} | {names} | "
            f"{r['models'].get('claim', 'no models')}"
        )
    g = s.get("announcement_gate") or {}
    if g.get("scanned"):
        lines.append(f"- announcement gate: {g['events']} event(s) queued; error: {g.get('error') or 'none'}")
    _step_summary("\n".join(lines))
    print("no production writes were made (read-only connection)")
    return 0


def run_ten(args: argparse.Namespace, ledger: cl.Ledger) -> int:
    now = datetime.now(UTC)
    db, host = _connect()
    cn.assert_library_identity(db)
    print(f"database: {host} (read only)")
    headlines = cn.load_headlines(db, now - timedelta(days=args.days), now)
    vocab = bnc.load_vocabulary(db)
    events = ni.cluster(headlines, (), vocab)
    ni.classify(vocab, events)
    signals, baseline = cn.baseline_signals(db, now, bnc.build)
    events += ni.concentration_events(events) + ni.signal_events(signals, ni.local_day(now))
    focus = {s.strip().upper() for s in (args.focus or "").split(",") if s.strip()}
    if focus:
        picked = cn.pick_focus(events, now, focus, args.count)
        if not picked:
            print(f"no event in the last {args.days} days names {sorted(focus)}")
            return 0
    else:
        picked = cn.pick_ten(events, now, args.count)
    print(f"{len(headlines)} headlines -> {len(events)} events; picked {len(picked)}; baseline: {baseline}")
    records, labels = [], {}
    exec_id = args.exec_id or f"ten-{now:%Y%m%dT%H%M%S}"
    for e, label in picked:
        item = {
            "key": e.key,
            "event_id": e.event_id,
            "version": e.version,
            "priority": ni.priority(e, now),
            "payload": cn.payload_for(e),
            "flagged_at": None,
            "attempts": 1,
        }
        labels[e.key] = label
        rec = cn.execute_item(
            item,
            db=db,
            env=os.environ,
            ledger=ledger,
            clock=lambda: datetime.now(UTC),
            build_pack=(
                functools.partial(council_run.build_pack, mapped_first=True)
                if focus
                else council_run.build_pack
            ),
            calendar=_calendar(),
            exec_id=exec_id,
            mode="ten",
            pack_db=lambda: _connect()[0],
        )
        rec["review_label"] = label
        records.append(rec)
        print(f"[{label}] {rec['outcome']}: {rec['event']['headline'][:80]}")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ten_headline_review.jsonl").write_text(cn.jsonl(records) + "\n", encoding="utf-8")
    md = cn.review_markdown(records, labels)
    (out_dir / "ten_headline_review.md").write_text(md, encoding="utf-8")
    _step_summary(md)
    print(md)
    print(f"review files written to {out_dir}; no production writes were made (read-only connection)")
    return 0


def run_report(args: argparse.Namespace, ledger: cl.Ledger) -> int:
    text = cn.seven_day_report(ledger.snapshot(), datetime.now(UTC), args.days)
    print(text)
    _step_summary(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=("auto", "ten", "report"), default="auto")
    ap.add_argument("--ledger", type=Path, default=None)
    ap.add_argument("--exec-id", default=None)
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--focus", default="", help="comma-separated symbols: assess the events that name them")
    ap.add_argument(
        "--days", type=int, default=7, help="headline window for --mode ten; report length for report"
    )
    ap.add_argument("--out-dir", default=".council_dryrun/review")
    args = ap.parse_args(argv)
    ledger = cl.Ledger(args.ledger or cn.ledger_path())
    try:
        return {"auto": run_auto, "ten": run_ten, "report": run_report}[args.mode](args, ledger)
    except library_db.LibraryConfigError as exc:
        print(f"REFUSED: {exc}")
        return 2
    except (cn.IdentityError, cn.ReadOnlyViolation, cl.LedgerError) as exc:
        print(f"REFUSED (fail closed): {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
