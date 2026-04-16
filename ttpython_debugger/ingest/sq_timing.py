"""Parse sq_timing_<run_label>.jsonl files written by Engine.py.

One JSON object per SQ execution on a given device. Produced by the
per-SQ instrumentation in ticktalkpython/Engine.py (see INSTRUCTIONS.md
Section 7 in the upstream TTPython repo).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class SqRecord:
    """One SQ execution, as logged by Engine.py instrumentation."""
    sq_name: str
    device: str
    execution_ms: float
    mode: str  # "concurrent", "timesliced", or ""


def read_sq_timing(path: Path) -> list[SqRecord]:
    """Parse an sq_timing_*.jsonl file.

    Lines without sq_name or execution_ms are skipped.
    """
    out: list[SqRecord] = []
    for line in _iter_lines(path):
        e = json.loads(line)
        if "execution_ms" not in e or "sq_name" not in e:
            continue
        out.append(SqRecord(
            sq_name=e["sq_name"],
            device=e.get("device", ""),
            execution_ms=float(e["execution_ms"]),
            mode=e.get("mode", ""),
        ))
    return out


def _iter_lines(path: Path) -> Iterable[str]:
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                yield line
