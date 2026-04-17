from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Deadlines:
    """Programmer-declared deadlines for one workload, loaded from YAML."""
    workload: str
    end_to_end_ms: float | None
    per_sq_ms: dict[str, float]

    @classmethod
    def load(cls, path: Path) -> "Deadlines":
        d = yaml.safe_load(path.read_text())
        return cls(
            workload=d["workload"],
            end_to_end_ms=d.get("end_to_end_deadline_ms"),
            per_sq_ms=d.get("per_sq_deadlines", {}) or {},
        )
