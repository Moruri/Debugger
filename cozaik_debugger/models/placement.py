"""
Placement and placement alternatives models.

A Placement maps SQ names to device names.
PlacementAlternatives stores ranked fallback devices per SQ,
precomputed by QPF during optimization (Section 6.5 of Cozaik paper).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class PlacementAlternative:
    """A ranked alternative device for a specific SQ."""
    device: str
    estimated_exec_time: float
    estimated_energy: float
    rank: int


@dataclass
class Placement:
    """A task-to-device mapping."""

    mapping: Dict[str, str] = field(default_factory=dict)
    strategy: str = "qpf"  # qpf, static, random, trivial
    objective: str = "makespan"  # makespan or energy
    objective_value: float = 0.0

    def get_device(self, sq_name: str) -> Optional[str]:
        return self.mapping.get(sq_name)

    def set_device(self, sq_name: str, device: str) -> None:
        self.mapping[sq_name] = device

    def tasks_on_device(self, device: str) -> List[str]:
        return [sq for sq, d in self.mapping.items() if d == device]

    def device_load(self) -> Dict[str, int]:
        """Count of tasks per device."""
        loads: Dict[str, int] = {}
        for device in self.mapping.values():
            loads[device] = loads.get(device, 0) + 1
        return loads


@dataclass
class PlacementAlternatives:
    """
    Precomputed ranked fallback devices per SQ, built during QPF optimization.
    Used by the RuntimeAdapter for fast adaptation without re-optimization.
    """

    # {sq_name: [PlacementAlternative sorted by rank]}
    alternatives: Dict[str, List[PlacementAlternative]] = field(default_factory=dict)

    def get_alternatives(self, sq_name: str) -> List[PlacementAlternative]:
        return self.alternatives.get(sq_name, [])

    def best_alternative(
        self, sq_name: str, exclude_devices: Optional[List[str]] = None
    ) -> Optional[PlacementAlternative]:
        """Get best alternative device, optionally excluding failed devices."""
        exclude = set(exclude_devices or [])
        for alt in self.get_alternatives(sq_name):
            if alt.device not in exclude:
                return alt
        return None
