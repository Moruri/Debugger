"""
Scheduling Quantum (SQ) and Arc models.

An SQ is the fundamental unit of computation in TTPython/Cozaik.
It carries compile-time metadata: execution time estimates, energy cost
estimates, criticality, constraints, and deadline information.

An Arc represents a directed data-flow edge between two SQs,
carrying estimated data size for communication cost calculation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class Criticality(Enum):
    ESSENTIAL = "essential"
    IMPORTANT = "important"
    NORMAL = "normal"


@dataclass
class SQ:
    """A Scheduling Quantum - one node in the compiled dataflow graph."""

    name: str
    app_id: str = "default"

    # Compile-time characterization (Section 6.1.2 of Cozaik paper)
    execution_time_estimates: Dict[str, float] = field(default_factory=dict)
    energy_cost_estimates: Dict[str, float] = field(default_factory=dict)

    criticality: Criticality = Criticality.NORMAL
    constraints: List[Dict] = field(default_factory=list)

    # Complexity metric (used for T_exec = complexity / cpu_speed)
    complexity: float = 1.0

    # Deadline metadata
    deadline_budget_us: Optional[int] = None
    deadline_type: Optional[str] = None
    has_planb: bool = False

    # Structural importance score (Section 6.1.3)
    structural_importance: float = 0.0

    # Priority (for multitenancy contention resolution)
    priority: int = 0

    @property
    def prefixed_name(self) -> str:
        """Return app_id__name format used in composed graphs."""
        if self.app_id and self.app_id != "default":
            return f"{self.app_id}__{self.name}"
        return self.name

    def get_exec_time(self, device: str) -> float:
        """Get estimated execution time for a specific device."""
        return self.execution_time_estimates.get(
            device, self.execution_time_estimates.get("default", self.complexity)
        )

    def get_energy_cost(self, device: str) -> float:
        """Get estimated energy cost for a specific device."""
        return self.energy_cost_estimates.get(
            device, self.energy_cost_estimates.get("default", 0.0)
        )

    def is_constrained_to(self, device_type: str) -> bool:
        """Check if this SQ has a type constraint matching the given device type."""
        for c in self.constraints:
            if "type" in c and device_type not in c["type"]:
                return False
        return True


@dataclass
class Arc:
    """A directed edge in the dataflow graph representing data flow between SQs."""

    source: str  # source SQ name
    target: str  # target SQ name
    data_name: str = ""
    estimated_data_size: int = 1024  # bytes, default 1KB
