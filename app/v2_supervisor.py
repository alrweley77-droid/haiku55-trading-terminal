"""V2 PAPER repeated-cycle supervisor, opt-in only.

A dry run is the default. The optional PAPER execution mode is restricted
to an isolated V2 SQLite database and cannot place real exchange orders.
"""
import argparse
import json
import os
import sys
import time

from app.v2_execution_cycle import execute_paper_cycle
from app.v2_paper_broker import V2PaperBroker


def run_cycles(*, broker, cycles=1, interval_seconds=60,
               execute=False, cycle_fn=execute_paper_cycle, sleep_fn=time.sleep,
               **cycle_kwargs):
    if not isinstance(cycles, int) or not 1 <= cycles <= 10000:
        raise ValueError("INVALID_CYCLE_COUNT")
    if not isinstance(interval_seconds, (int, float)) or not 1 <= interval_seconds <= 86400:
        raise ValueError("INVALID_INTERVAL")
    if execute and os.environ.get("HAIKU55_V2_PAPER_EXECUTE") != "YES":
        raise PermissionError("PAPER_EXECUTION_NOT_ENABLED")
    reports = []
    for index in range(cycles):
        report = cycle_fn(broker=broker, execute=execute, **cycle_kwargs)
        reports.append(report)
        if not report.get("ok", False):
            break
        if index + 1 < cycles:
            sleep_fn(interval_seconds)
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description="HAIKU55 V2 independent PAPER supervisor")
    parser.add_argument("--db", default="haiku55-v2.db")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--interval", type=float, default=60)
    parser.add_argument("--execute-paper", action="store_true")
    args = parser.parse_args(argv)
    try:
        broker = V2PaperBroker(args.db)
        reports = run_cycles(broker=broker, cycles=args.cycles,
                             interval_seconds=args.interval,
                             execute=args.execute_paper)
    except (ValueError, PermissionError, OSError) as exc:
        print(json.dumps({"ok": False, "mode": "PAPER",
                          "error": str(exc)}), file=sys.stderr)
        return 1
    for report in reports:
        print(json.dumps(report, ensure_ascii=False))
    return 0 if reports and all(r.get("ok") for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
