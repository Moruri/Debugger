"""`deadlines` subcommand: report deadline violations from a cluster run."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..features.deadlines import (
    Deadlines,
    check_end_to_end, check_per_sq,
    end_to_end_summary, per_sq_summary,
)
from ..ingest import read_runtime_log, read_sq_timing


def register(subs: argparse._SubParsersAction) -> None:
    p = subs.add_parser(
        "deadlines",
        help="Report deadline violations from a real cluster run.",
    )
    p.add_argument("--spec", required=True, type=Path,
                   help="YAML file declaring the deadlines for this workload")
    p.add_argument("--runtime-log", type=Path, default=None,
                   help="runtime_log_*.jsonl from sink SQs (end-to-end)")
    p.add_argument("--sq-timing", type=Path, default=None,
                   help="sq_timing_*.jsonl from Engine.py instrumentation")
    p.set_defaults(func=_run)


def _run(args) -> int:
    dl = Deadlines.load(args.spec)

    if args.runtime_log:
        recs = read_runtime_log(args.runtime_log)
        viols = check_end_to_end(recs, dl)
        print(end_to_end_summary(recs, dl, viols))

    if args.sq_timing:
        sq_recs = read_sq_timing(args.sq_timing)
        sq_viols = check_per_sq(sq_recs, dl)
        print(per_sq_summary(sq_recs, dl, sq_viols))

    if not args.runtime_log and not args.sq_timing:
        print("Nothing to check: pass --runtime-log and/or --sq-timing.")
        return 2

    return 0
