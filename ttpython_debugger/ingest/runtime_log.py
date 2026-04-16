"""Parse runtime_log_<run_label>.jsonl files written by sink SQs.

One JSON object per pipeline completion. We read the fields that any
debugger feature is likely to need and expose them as a typed record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class EndToEndRecord:
    """One pipeline completion, as logged by a sink SQ."""
    workload: str
    run_label: str
    latency_ms: float
    predicted_ms: float | None


def read_runtime_log(path: Path) -> list[EndToEndRecord]:
    """Parse a runtime_log_*.jsonl file.

    Lines without a latency_ms field are skipped (tolerates metadata-only
    preambles or partial logs).
    """
    out: list[EndToEndRecord] = []
    for line in _iter_lines(path):
        e = json.loads(line)
        if "latency_ms" not in e:
            continue
        out.append(EndToEndRecord(
            workload=e.get("workload", ""),
            run_label=e.get("run_label", ""),
            latency_ms=float(e["latency_ms"]),
            predicted_ms=(float(e["predicted_ms"])
                          if "predicted_ms" in e else None),
        ))
    return out


def _iter_lines(path: Path) -> Iterable[str]:
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                yield line
