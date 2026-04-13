"""
Trace record formats for the Cozaik debugger.

These lightweight structures capture actual runtime behavior and compare it
against compile-time estimates embedded in SQ objects. Designed for
production use with minimal overhead.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


@dataclass
class TraceRecord:
    """
    One SQ execution record. Captures actual vs estimated performance.

    Recorded each time an SQ fires on a device.
    """

    # Identity
    sq_name: str
    app_id: str
    device: str
    iteration: int  # which firing of the periodic graph

    # Timing (milliseconds)
    start_time_ms: float
    end_time_ms: float
    estimated_exec_time_ms: float

    # Energy (joules)
    actual_energy_j: float = 0.0
    estimated_energy_j: float = 0.0

    # Deadline
    deadline_ms: Optional[float] = None
    deadline_met: Optional[bool] = None
    planb_triggered: bool = False

    # Placement context
    assigned_device: str = ""
    alternative_devices: List[str] = field(default_factory=list)

    # Criticality at time of execution
    criticality: str = "normal"

    # Contention: other SQs running on same device during this window
    concurrent_sqs: List[str] = field(default_factory=list)
    execution_mode: str = "unconstrained"  # unconstrained, concurrent, timesliced

    @property
    def actual_exec_time_ms(self) -> float:
        return self.end_time_ms - self.start_time_ms

    @property
    def time_deviation_ms(self) -> float:
        """Positive = slower than estimated, negative = faster."""
        return self.actual_exec_time_ms - self.estimated_exec_time_ms

    @property
    def time_deviation_pct(self) -> float:
        if self.estimated_exec_time_ms == 0:
            return 0.0
        return (self.time_deviation_ms / self.estimated_exec_time_ms) * 100

    @property
    def energy_deviation_j(self) -> float:
        return self.actual_energy_j - self.estimated_energy_j

    @property
    def energy_deviation_pct(self) -> float:
        if self.estimated_energy_j == 0:
            return 0.0
        return (self.energy_deviation_j / self.estimated_energy_j) * 100


@dataclass
class CommunicationRecord:
    """Records actual data transfer between SQs on different devices."""

    source_sq: str
    target_sq: str
    source_device: str
    target_device: str
    data_size_bytes: int
    estimated_data_size_bytes: int

    # Timing
    send_time_ms: float
    receive_time_ms: float
    estimated_transfer_time_ms: float

    iteration: int = 0

    @property
    def actual_transfer_time_ms(self) -> float:
        return self.receive_time_ms - self.send_time_ms

    @property
    def transfer_deviation_ms(self) -> float:
        return self.actual_transfer_time_ms - self.estimated_transfer_time_ms


class AdaptationTrigger(Enum):
    DEVICE_FAILURE = "device_failure"
    FALSE_POSITIVE = "false_positive"
    DEVICE_RECONNECTION = "device_reconnection"
    NEW_DEVICE = "new_device"
    DEADLINE_MISS = "deadline_miss"
    ENERGY_BUDGET_EXCEEDED = "energy_budget_exceeded"


@dataclass
class AdaptationRecord:
    """
    Records a runtime adaptation decision with full causal context.

    Captures the Trigger -> Validate -> Decide -> Act spine
    from Section 3 of the Cozaik paper (Figure 4).
    """

    timestamp_ms: float
    trigger: AdaptationTrigger
    trigger_device: str

    # Validate phase
    validation_method: str = ""  # e.g. "grace_period", "stability_check"
    validation_duration_ms: float = 0.0
    false_positive: bool = False

    # Decide phase
    decision: str = ""  # e.g. "remap", "no_op", "degrade"
    affected_tasks: List[str] = field(default_factory=list)

    # For each remapped task: {sq_name: {from_device, to_device, reason}}
    remapping_details: List[Dict] = field(default_factory=list)

    # Why the target device was chosen
    selection_reason: str = ""  # e.g. "qpf_alternative_rank_1", "first_fit"
    deployment_strategy: str = ""

    # Act phase
    adaptation_duration_ms: float = 0.0
    tasks_degraded: List[str] = field(default_factory=list)
    success: bool = True

    # Constraint compliance
    constraint_violations: int = 0


@dataclass
class DeploymentTrace:
    """
    Complete trace of a single deployment run.
    Aggregates all records from all devices and applications.
    """

    deployment_id: str = ""
    start_time_ms: float = 0.0
    end_time_ms: float = 0.0

    # The core trace data
    execution_records: List[TraceRecord] = field(default_factory=list)
    communication_records: List[CommunicationRecord] = field(default_factory=list)
    adaptation_records: List[AdaptationRecord] = field(default_factory=list)

    # Metadata
    num_apps: int = 0
    num_devices: int = 0
    placement_strategy: str = ""
    optimization_objective: str = ""

    def records_for_sq(self, sq_name: str) -> List[TraceRecord]:
        return [r for r in self.execution_records if r.sq_name == sq_name]

    def records_for_device(self, device: str) -> List[TraceRecord]:
        return [r for r in self.execution_records if r.device == device]

    def records_for_app(self, app_id: str) -> List[TraceRecord]:
        return [r for r in self.execution_records if r.app_id == app_id]

    def records_for_iteration(self, iteration: int) -> List[TraceRecord]:
        return [r for r in self.execution_records if r.iteration == iteration]

    def missed_deadlines(self) -> List[TraceRecord]:
        return [r for r in self.execution_records if r.deadline_met is False]

    def planb_activations(self) -> List[TraceRecord]:
        return [r for r in self.execution_records if r.planb_triggered]

    @property
    def total_duration_ms(self) -> float:
        return self.end_time_ms - self.start_time_ms

    @property
    def iterations(self) -> List[int]:
        return sorted({r.iteration for r in self.execution_records})
