"""Format violation results as plain-text tables.

Text-only on purpose. Richer output (HTML, plots) is a separate concern
and will live in a future report module when we need it.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Sequence

from ...ingest import EndToEndRecord, SqRecord
from .detect import Violation
from .spec import Deadlines


def end_to_end_summary(records: Sequence[EndToEndRecord],
                        deadlines: Deadlines,
                        violations: Sequence[Violation]) -> str:
    if deadlines.end_to_end_ms is None:
        return "No end-to-end deadline declared.\n"
    if not records:
        return "No end-to-end records found.\n"

    lats = [r.latency_ms for r in records]
    n = len(lats)
    n_viol = len(violations)
    rate = n_viol / n * 100
    p50 = statistics.median(lats)
    p95 = _percentile(lats, 0.95)

    return (
        f"End-to-end deadline ({deadlines.workload}): "
        f"{deadlines.end_to_end_ms:.1f} ms\n"
        f"  runs={n}  violations={n_viol} ({rate:.1f}%)  "
        f"p50={p50:.1f}ms  p95={p95:.1f}ms  max={max(lats):.1f}ms\n"
    )


def per_sq_summary(records: Sequence[SqRecord],
                    deadlines: Deadlines,
                    violations: Sequence[Violation]) -> str:
    if not deadlines.per_sq_ms:
        return "No per-SQ deadlines declared.\n"

    by_sq_records: dict[str, list[float]] = defaultdict(list)
    for r in records:
        by_sq_records[r.sq_name].append(r.execution_ms)

    by_sq_violations: dict[str, list[Violation]] = defaultdict(list)
    for v in violations:
        by_sq_violations[v.name].append(v)

    lines = ["Per-SQ deadlines:"]
    lines.append(
        f"  {'sq_name':<28} {'deadline':>10} {'runs':>6} "
        f"{'viol':>6} {'rate':>7} {'p95':>10}"
    )
    for sq, deadline in deadlines.per_sq_ms.items():
        runs = by_sq_records.get(sq, [])
        n = len(runs)
        nv = len(by_sq_violations.get(sq, []))
        rate = (nv / n * 100) if n else 0.0
        p95 = _percentile(runs, 0.95) if runs else 0.0
        lines.append(
            f"  {sq:<28} {deadline:>9.2f}ms {n:>6} "
            f"{nv:>6} {rate:>6.1f}% {p95:>9.2f}ms"
        )
    return "\n".join(lines) + "\n"


def _percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(len(s) * p)
    if idx >= len(s):
        idx = len(s) - 1
    return s[idx]
