"""
Trace reader: loads trace files from disk and reconstructs DeploymentTrace objects.
Supports reading from multiple device log files and merging them.
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import List, Optional

from cozaik_debugger.trace.formats import (
    TraceRecord,
    CommunicationRecord,
    AdaptationRecord,
    AdaptationTrigger,
    DeploymentTrace,
)


class TraceReader:
    """Reads and merges trace files from a deployment."""

    @staticmethod
    def read_json(path: str) -> DeploymentTrace:
        """Load a complete deployment trace from a JSON file."""
        data = json.loads(Path(path).read_text())
        trace = DeploymentTrace(
            deployment_id=data.get("deployment_id", ""),
            start_time_ms=data.get("start_time_ms", 0),
            end_time_ms=data.get("end_time_ms", 0),
            num_apps=data.get("num_apps", 0),
            num_devices=data.get("num_devices", 0),
            placement_strategy=data.get("placement_strategy", ""),
        )

        for r in data.get("execution_records", []):
            trace.execution_records.append(TraceRecord(
                sq_name=r["sq_name"],
                app_id=r.get("app_id", ""),
                device=r["device"],
                iteration=r.get("iteration", 0),
                start_time_ms=r["start_time_ms"],
                end_time_ms=r["end_time_ms"],
                estimated_exec_time_ms=r.get("estimated_exec_time_ms", 0),
                actual_energy_j=r.get("actual_energy_j", 0),
                estimated_energy_j=r.get("estimated_energy_j", 0),
                deadline_ms=r.get("deadline_ms"),
                deadline_met=r.get("deadline_met"),
                planb_triggered=r.get("planb_triggered", False),
                criticality=r.get("criticality", "normal"),
                execution_mode=r.get("execution_mode", "unconstrained"),
            ))

        for r in data.get("communication_records", []):
            trace.communication_records.append(CommunicationRecord(
                source_sq=r["source_sq"],
                target_sq=r["target_sq"],
                source_device=r["source_device"],
                target_device=r["target_device"],
                data_size_bytes=r.get("data_size_bytes", 0),
                estimated_data_size_bytes=r.get("estimated_data_size_bytes", 0),
                send_time_ms=r["send_time_ms"],
                receive_time_ms=r["receive_time_ms"],
                estimated_transfer_time_ms=r.get("estimated_transfer_time_ms", 0),
                iteration=r.get("iteration", 0),
            ))

        for r in data.get("adaptation_records", []):
            trace.adaptation_records.append(AdaptationRecord(
                timestamp_ms=r["timestamp_ms"],
                trigger=AdaptationTrigger(r["trigger"]),
                trigger_device=r["trigger_device"],
                decision=r.get("decision", ""),
                affected_tasks=r.get("affected_tasks", []),
                adaptation_duration_ms=r.get("adaptation_duration_ms", 0),
                success=r.get("success", True),
                constraint_violations=r.get("constraint_violations", 0),
            ))

        return trace

    @staticmethod
    def merge_device_logs(
        log_paths: List[str],
        clock_offsets: Optional[dict] = None,
    ) -> DeploymentTrace:
        """
        Merge per-device log files into a single DeploymentTrace.

        Args:
            log_paths: Paths to per-device JSON trace files.
            clock_offsets: {device_name: offset_ms} for timestamp synchronization.
                           Applied as: corrected_time = raw_time - offset.
        """
        offsets = clock_offsets or {}
        merged = DeploymentTrace()
        all_starts = []
        all_ends = []

        for path in log_paths:
            device_trace = TraceReader.read_json(path)

            for r in device_trace.execution_records:
                offset = offsets.get(r.device, 0.0)
                r.start_time_ms -= offset
                r.end_time_ms -= offset
                merged.execution_records.append(r)

            for r in device_trace.communication_records:
                src_offset = offsets.get(r.source_device, 0.0)
                dst_offset = offsets.get(r.target_device, 0.0)
                r.send_time_ms -= src_offset
                r.receive_time_ms -= dst_offset
                merged.communication_records.append(r)

            for r in device_trace.adaptation_records:
                offset = offsets.get(r.trigger_device, 0.0)
                r.timestamp_ms -= offset
                merged.adaptation_records.append(r)

            if device_trace.start_time_ms:
                all_starts.append(device_trace.start_time_ms)
            if device_trace.end_time_ms:
                all_ends.append(device_trace.end_time_ms)

        if all_starts:
            merged.start_time_ms = min(all_starts)
        if all_ends:
            merged.end_time_ms = max(all_ends)

        devices = set()
        apps = set()
        for r in merged.execution_records:
            devices.add(r.device)
            apps.add(r.app_id)
        merged.num_devices = len(devices)
        merged.num_apps = len(apps - {"unknown", "composed", "default"}) or 1

        return merged
