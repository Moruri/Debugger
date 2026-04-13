"""
Global execution timeline reconstruction.

Reads trace logs from multiple devices, synchronizes timestamps,
and builds a unified view of what executed where and when.
Identifies task overlaps for contention analysis.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from cozaik_debugger.trace.formats import DeploymentTrace, TraceRecord


@dataclass
class TaskWindow:
    """Execution window for one SQ on one device."""
    sq_name: str
    app_id: str
    device: str
    start_ms: float
    end_ms: float
    iteration: int

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


@dataclass
class ContentionGroup:
    """A set of tasks that overlap temporally on the same device."""
    device: str
    tasks: List[TaskWindow]
    overlap_start_ms: float
    overlap_end_ms: float
    cross_application: bool = False

    @property
    def overlap_duration_ms(self) -> float:
        return self.overlap_end_ms - self.overlap_start_ms


@dataclass
class DeviceTimeline:
    """Complete execution timeline for one device."""
    device: str
    windows: List[TaskWindow] = field(default_factory=list)
    utilization_pct: float = 0.0
    idle_time_ms: float = 0.0
    contentions: List[ContentionGroup] = field(default_factory=list)


@dataclass
class GlobalTimeline:
    """Unified execution timeline across all devices."""
    device_timelines: Dict[str, DeviceTimeline] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    all_contentions: List[ContentionGroup] = field(default_factory=list)

    def get_windows_at_time(self, time_ms: float) -> List[TaskWindow]:
        """Find all tasks executing at a specific time."""
        result = []
        for dt in self.device_timelines.values():
            for w in dt.windows:
                if w.start_ms <= time_ms < w.end_ms:
                    result.append(w)
        return result


class TimelineReconstructor:
    """Builds a global execution timeline from a DeploymentTrace."""

    def __init__(self, trace: DeploymentTrace) -> None:
        self._trace = trace

    def reconstruct(
        self, iteration: Optional[int] = None
    ) -> GlobalTimeline:
        """
        Build global timeline, optionally filtered to a single iteration.

        Steps:
        1. Group execution records by device
        2. Build TaskWindows
        3. Compute per-device utilization
        4. Detect temporal overlaps (contention)
        """
        records = self._trace.execution_records
        if iteration is not None:
            records = [r for r in records if r.iteration == iteration]

        timeline = GlobalTimeline()

        # Group by device
        by_device: Dict[str, List[TraceRecord]] = {}
        for r in records:
            by_device.setdefault(r.device, []).append(r)

        global_start = min((r.start_time_ms for r in records), default=0)
        global_end = max((r.end_time_ms for r in records), default=0)
        timeline.total_duration_ms = global_end - global_start

        for device, device_records in by_device.items():
            dt = DeviceTimeline(device=device)

            # Build windows sorted by start time
            windows = []
            for r in device_records:
                windows.append(TaskWindow(
                    sq_name=r.sq_name,
                    app_id=r.app_id,
                    device=r.device,
                    start_ms=r.start_time_ms,
                    end_ms=r.end_time_ms,
                    iteration=r.iteration,
                ))
            windows.sort(key=lambda w: w.start_ms)
            dt.windows = windows

            # Compute utilization
            if timeline.total_duration_ms > 0:
                busy_time = sum(w.duration_ms for w in windows)
                dt.utilization_pct = (busy_time / timeline.total_duration_ms) * 100
                dt.idle_time_ms = timeline.total_duration_ms - busy_time

            # Detect overlaps using interval sweep
            dt.contentions = self._detect_overlaps(windows)
            timeline.all_contentions.extend(dt.contentions)

            timeline.device_timelines[device] = dt

        return timeline

    def _detect_overlaps(self, windows: List[TaskWindow]) -> List[ContentionGroup]:
        """
        Detect temporally overlapping tasks on the same device.
        Uses a sweep-line algorithm.
        """
        if len(windows) < 2:
            return []

        contentions: List[ContentionGroup] = []

        for i, w1 in enumerate(windows):
            overlapping = [w1]
            for j in range(i + 1, len(windows)):
                w2 = windows[j]
                if w2.start_ms >= w1.end_ms:
                    break
                # w2.start_ms < w1.end_ms means overlap
                overlapping.append(w2)

            if len(overlapping) > 1:
                overlap_start = max(w.start_ms for w in overlapping)
                overlap_end = min(w.end_ms for w in overlapping)
                if overlap_end > overlap_start:
                    apps = {w.app_id for w in overlapping}
                    group = ContentionGroup(
                        device=w1.device,
                        tasks=overlapping,
                        overlap_start_ms=overlap_start,
                        overlap_end_ms=overlap_end,
                        cross_application=len(apps) > 1,
                    )
                    # Avoid duplicates
                    existing = {
                        frozenset(w.sq_name for w in c.tasks)
                        for c in contentions
                    }
                    key = frozenset(w.sq_name for w in overlapping)
                    if key not in existing:
                        contentions.append(group)

        return contentions

    def find_device_for_task(
        self, sq_name: str, iteration: int = 0
    ) -> Optional[str]:
        """Look up which device ran a specific task."""
        for r in self._trace.execution_records:
            if r.sq_name == sq_name and r.iteration == iteration:
                return r.device
        return None
