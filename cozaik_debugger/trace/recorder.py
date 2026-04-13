"""
Trace recorder for instrumenting Cozaik runtime execution.

Drop-in instrumentation: wrap SQ execution calls to automatically
capture timing, energy, and placement data. Compares actuals against
compile-time estimates already embedded in SQ objects.
"""

from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

from cozaik_debugger.models.sq import SQ
from cozaik_debugger.models.device import DeviceProfile, DeviceTopology
from cozaik_debugger.models.placement import Placement
from cozaik_debugger.trace.formats import (
    TraceRecord,
    CommunicationRecord,
    AdaptationRecord,
    AdaptationTrigger,
    DeploymentTrace,
)


class TraceRecorder:
    """
    Records execution traces during Cozaik runtime operation.

    Usage:
        recorder = TraceRecorder(topology, placement, graph_sqs)
        recorder.start_deployment("run_001")

        # For each SQ execution:
        recorder.record_sq_start("senml_parse", "edge0", iteration=1)
        # ... SQ executes ...
        recorder.record_sq_end("senml_parse", "edge0", iteration=1,
                               actual_energy=0.05)

        # For communications:
        recorder.record_communication("spout", "parse", "edge0", "mid0",
                                       data_size=2048, iteration=1)

        # For adaptations:
        recorder.record_adaptation(trigger=AdaptationTrigger.DEVICE_FAILURE, ...)

        trace = recorder.finish_deployment()
    """

    def __init__(
        self,
        topology: DeviceTopology,
        placement: Placement,
        sqs: Dict[str, SQ],
    ) -> None:
        self._topology = topology
        self._placement = placement
        self._sqs = sqs

        self._trace = DeploymentTrace()
        self._pending_starts: Dict[str, float] = {}
        self._active = False

    def start_deployment(self, deployment_id: str = "") -> None:
        self._trace = DeploymentTrace(
            deployment_id=deployment_id,
            start_time_ms=time.time() * 1000,
            num_devices=len(self._topology.devices),
            placement_strategy=self._placement.strategy,
            optimization_objective=self._placement.objective,
        )
        app_ids = {sq.app_id for sq in self._sqs.values()}
        self._trace.num_apps = len(app_ids - {"default", "composed"}) or 1
        self._active = True

    def record_sq_start(
        self, sq_name: str, device: str, iteration: int
    ) -> None:
        key = f"{sq_name}:{device}:{iteration}"
        self._pending_starts[key] = time.time() * 1000

    def record_sq_end(
        self,
        sq_name: str,
        device: str,
        iteration: int,
        actual_energy: float = 0.0,
        deadline_ms: Optional[float] = None,
        planb_triggered: bool = False,
        concurrent_sqs: Optional[List[str]] = None,
        execution_mode: str = "unconstrained",
    ) -> TraceRecord:
        """Record SQ completion. Automatically compares against estimates."""
        key = f"{sq_name}:{device}:{iteration}"
        start_ms = self._pending_starts.pop(key, time.time() * 1000)
        end_ms = time.time() * 1000

        sq = self._sqs.get(sq_name)
        estimated_time = sq.get_exec_time(device) if sq else 0.0
        estimated_energy = sq.get_energy_cost(device) if sq else 0.0
        criticality = sq.criticality.value if sq else "normal"

        actual_exec = end_ms - start_ms
        deadline_met = None
        if deadline_ms is not None:
            deadline_met = actual_exec <= deadline_ms

        # Get alternative devices from placement
        alt_devices = []
        if sq and sq.name in self._sqs:
            for d in self._topology.device_names:
                if d != device and d in sq.execution_time_estimates:
                    alt_devices.append(d)

        record = TraceRecord(
            sq_name=sq_name,
            app_id=sq.app_id if sq else "unknown",
            device=device,
            iteration=iteration,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            estimated_exec_time_ms=estimated_time,
            actual_energy_j=actual_energy,
            estimated_energy_j=estimated_energy,
            deadline_ms=deadline_ms,
            deadline_met=deadline_met,
            planb_triggered=planb_triggered,
            assigned_device=device,
            alternative_devices=alt_devices,
            criticality=criticality,
            concurrent_sqs=concurrent_sqs or [],
            execution_mode=execution_mode,
        )
        self._trace.execution_records.append(record)
        return record

    def record_sq_execution(
        self,
        sq_name: str,
        device: str,
        iteration: int,
        start_time_ms: float,
        end_time_ms: float,
        actual_energy: float = 0.0,
        deadline_ms: Optional[float] = None,
        planb_triggered: bool = False,
        concurrent_sqs: Optional[List[str]] = None,
        execution_mode: str = "unconstrained",
    ) -> TraceRecord:
        """Directly record an SQ execution with explicit times (for simulation)."""
        sq = self._sqs.get(sq_name)
        estimated_time = sq.get_exec_time(device) if sq else 0.0
        estimated_energy = sq.get_energy_cost(device) if sq else 0.0
        criticality = sq.criticality.value if sq else "normal"

        actual_exec = end_time_ms - start_time_ms
        deadline_met = None
        if deadline_ms is not None:
            deadline_met = actual_exec <= deadline_ms

        alt_devices = []
        for d in self._topology.device_names:
            if d != device and sq and d in sq.execution_time_estimates:
                alt_devices.append(d)

        record = TraceRecord(
            sq_name=sq_name,
            app_id=sq.app_id if sq else "unknown",
            device=device,
            iteration=iteration,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            estimated_exec_time_ms=estimated_time,
            actual_energy_j=actual_energy,
            estimated_energy_j=estimated_energy,
            deadline_ms=deadline_ms,
            deadline_met=deadline_met,
            planb_triggered=planb_triggered,
            assigned_device=device,
            alternative_devices=alt_devices,
            criticality=criticality,
            concurrent_sqs=concurrent_sqs or [],
            execution_mode=execution_mode,
        )
        self._trace.execution_records.append(record)
        return record

    def record_communication(
        self,
        source_sq: str,
        target_sq: str,
        source_device: str,
        target_device: str,
        data_size: int,
        send_time_ms: float,
        receive_time_ms: float,
        iteration: int = 0,
    ) -> CommunicationRecord:
        """Record a data transfer between SQs."""
        # Get estimated data size from the graph arc
        estimated_size = data_size  # default to actual if no arc info
        estimated_transfer = self._topology.calculate_transfer_time(
            source_device, target_device, estimated_size
        ) * 1000  # convert to ms

        record = CommunicationRecord(
            source_sq=source_sq,
            target_sq=target_sq,
            source_device=source_device,
            target_device=target_device,
            data_size_bytes=data_size,
            estimated_data_size_bytes=estimated_size,
            send_time_ms=send_time_ms,
            receive_time_ms=receive_time_ms,
            estimated_transfer_time_ms=estimated_transfer,
            iteration=iteration,
        )
        self._trace.communication_records.append(record)
        return record

    def record_adaptation(
        self,
        trigger: AdaptationTrigger,
        trigger_device: str,
        timestamp_ms: Optional[float] = None,
        **kwargs,
    ) -> AdaptationRecord:
        """Record a runtime adaptation event."""
        record = AdaptationRecord(
            timestamp_ms=timestamp_ms or (time.time() * 1000),
            trigger=trigger,
            trigger_device=trigger_device,
            **kwargs,
        )
        self._trace.adaptation_records.append(record)
        return record

    def finish_deployment(self) -> DeploymentTrace:
        self._trace.end_time_ms = time.time() * 1000
        self._active = False
        return self._trace

    def export_json(self, path: str) -> None:
        """Export the trace to a JSON file for offline analysis."""
        data = {
            "deployment_id": self._trace.deployment_id,
            "start_time_ms": self._trace.start_time_ms,
            "end_time_ms": self._trace.end_time_ms,
            "num_apps": self._trace.num_apps,
            "num_devices": self._trace.num_devices,
            "placement_strategy": self._trace.placement_strategy,
            "execution_records": [
                {
                    "sq_name": r.sq_name,
                    "app_id": r.app_id,
                    "device": r.device,
                    "iteration": r.iteration,
                    "start_time_ms": r.start_time_ms,
                    "end_time_ms": r.end_time_ms,
                    "estimated_exec_time_ms": r.estimated_exec_time_ms,
                    "actual_energy_j": r.actual_energy_j,
                    "estimated_energy_j": r.estimated_energy_j,
                    "deadline_ms": r.deadline_ms,
                    "deadline_met": r.deadline_met,
                    "planb_triggered": r.planb_triggered,
                    "criticality": r.criticality,
                    "execution_mode": r.execution_mode,
                }
                for r in self._trace.execution_records
            ],
            "communication_records": [
                {
                    "source_sq": r.source_sq,
                    "target_sq": r.target_sq,
                    "source_device": r.source_device,
                    "target_device": r.target_device,
                    "data_size_bytes": r.data_size_bytes,
                    "send_time_ms": r.send_time_ms,
                    "receive_time_ms": r.receive_time_ms,
                    "estimated_transfer_time_ms": r.estimated_transfer_time_ms,
                    "iteration": r.iteration,
                }
                for r in self._trace.communication_records
            ],
            "adaptation_records": [
                {
                    "timestamp_ms": r.timestamp_ms,
                    "trigger": r.trigger.value,
                    "trigger_device": r.trigger_device,
                    "decision": r.decision,
                    "affected_tasks": r.affected_tasks,
                    "adaptation_duration_ms": r.adaptation_duration_ms,
                    "success": r.success,
                    "constraint_violations": r.constraint_violations,
                }
                for r in self._trace.adaptation_records
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2))
