from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ...ingest import EndToEndRecord, SqRecord
from .spec import Deadlines


@dataclass
class Violation:
    kind: str          
    name: str          
    deadline_ms: float
    actual_ms: float
    overrun_ms: float  


def check_end_to_end(records: Sequence[EndToEndRecord],
                        deadlines: Deadlines) -> list[Violation]:
    """One Violation per pipeline completion that exceeded the budget."""
    if deadlines.end_to_end_ms is None:
        return []
    out: list[Violation] = []
    for r in records:
        if r.latency_ms > deadlines.end_to_end_ms:
            out.append(Violation(
                kind="end_to_end",
                name=r.workload or deadlines.workload,
                deadline_ms=deadlines.end_to_end_ms,
                actual_ms=r.latency_ms,
                overrun_ms=r.latency_ms - deadlines.end_to_end_ms,
            ))
    return out


def check_per_sq(records: Sequence[SqRecord],
                    deadlines: Deadlines) -> list[Violation]:
    """One Violation per SQ execution that exceeded its declared budget.

    SQs without a declared deadline are silently ignored — the spec is
    that not every SQ has a deadline, only the ones the programmer
    wrapped in PreemptiveFinishByOtherwise.
    """
    out: list[Violation] = []
    for r in records:
        d = deadlines.per_sq_ms.get(r.sq_name)
        if d is None:
            continue
        if r.execution_ms > d:
            out.append(Violation(
                kind="per_sq",
                name=r.sq_name,
                deadline_ms=d,
                actual_ms=r.execution_ms,
                overrun_ms=r.execution_ms - d,
            ))
    return out
