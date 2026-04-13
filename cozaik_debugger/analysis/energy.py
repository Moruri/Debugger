"""
Energy analysis module.

Compares predicted vs actual energy per task and device.
Identifies hotspots, budget violations, and suggests task migrations.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from cozaik_debugger.models.graph import TTGraph
from cozaik_debugger.models.device import DeviceTopology
from cozaik_debugger.models.placement import Placement
from cozaik_debugger.trace.formats import DeploymentTrace


@dataclass
class TaskEnergyProfile:
    """Energy analysis for a single SQ."""
    sq_name: str
    device: str
    estimated_energy_j: float
    actual_energy_j: float
    deviation_pct: float
    is_hotspot: bool = False


@dataclass
class DeviceEnergyProfile:
    """Energy analysis for a single device."""
    device: str
    total_estimated_j: float
    total_actual_j: float
    energy_budget_j: Optional[float]
    budget_exceeded: bool = False
    utilization_pct: float = 0.0
    tasks: List[TaskEnergyProfile] = field(default_factory=list)


@dataclass
class MigrationSuggestion:
    """Suggestion to move a task to a lower-energy device."""
    sq_name: str
    current_device: str
    suggested_device: str
    current_energy_j: float
    suggested_energy_j: float
    savings_j: float
    savings_pct: float
    exec_time_impact_ms: float  # positive = slower


@dataclass
class EnergyReport:
    """Complete energy analysis report."""
    total_estimated_j: float = 0.0
    total_actual_j: float = 0.0
    total_deviation_pct: float = 0.0

    task_profiles: List[TaskEnergyProfile] = field(default_factory=list)
    device_profiles: List[DeviceEnergyProfile] = field(default_factory=list)
    hotspots: List[TaskEnergyProfile] = field(default_factory=list)
    budget_violations: List[DeviceEnergyProfile] = field(default_factory=list)
    migration_suggestions: List[MigrationSuggestion] = field(default_factory=list)

    summary: str = ""


class EnergyAnalyzer:
    """Analyzes energy consumption across a deployment."""

    def __init__(
        self,
        graph: TTGraph,
        topology: DeviceTopology,
        trace: DeploymentTrace,
        placement: Placement,
        hotspot_threshold_pct: float = 50.0,
    ) -> None:
        self._graph = graph
        self._topology = topology
        self._trace = trace
        self._placement = placement
        self._hotspot_threshold = hotspot_threshold_pct

    def analyze(self, iteration: Optional[int] = None) -> EnergyReport:
        """Run full energy analysis."""
        report = EnergyReport()

        records = self._trace.execution_records
        if iteration is not None:
            records = [r for r in records if r.iteration == iteration]

        # Per-task analysis
        for r in records:
            est = r.estimated_energy_j
            act = r.actual_energy_j
            dev_pct = ((act - est) / est * 100) if est > 0 else 0.0
            is_hotspot = abs(dev_pct) > self._hotspot_threshold

            tp = TaskEnergyProfile(
                sq_name=r.sq_name,
                device=r.device,
                estimated_energy_j=est,
                actual_energy_j=act,
                deviation_pct=dev_pct,
                is_hotspot=is_hotspot,
            )
            report.task_profiles.append(tp)
            if is_hotspot:
                report.hotspots.append(tp)

            report.total_estimated_j += est
            report.total_actual_j += act

        if report.total_estimated_j > 0:
            report.total_deviation_pct = (
                (report.total_actual_j - report.total_estimated_j)
                / report.total_estimated_j * 100
            )

        # Per-device analysis
        device_tasks: Dict[str, List[TaskEnergyProfile]] = {}
        for tp in report.task_profiles:
            device_tasks.setdefault(tp.device, []).append(tp)

        for device_name, tasks in device_tasks.items():
            dev = self._topology.devices.get(device_name)
            total_est = sum(t.estimated_energy_j for t in tasks)
            total_act = sum(t.actual_energy_j for t in tasks)
            budget = dev.energy_budget if dev else None
            exceeded = budget is not None and total_act > budget

            dp = DeviceEnergyProfile(
                device=device_name,
                total_estimated_j=total_est,
                total_actual_j=total_act,
                energy_budget_j=budget,
                budget_exceeded=exceeded,
                tasks=tasks,
            )
            report.device_profiles.append(dp)
            if exceeded:
                report.budget_violations.append(dp)

        # Migration suggestions
        report.migration_suggestions = self._suggest_migrations(report)

        # Summary
        report.summary = self._build_summary(report)
        return report

    def _suggest_migrations(
        self, report: EnergyReport
    ) -> List[MigrationSuggestion]:
        """Suggest moving high-energy tasks to lower-power devices."""
        suggestions = []

        # Sort hotspots by actual energy (descending)
        hotspots = sorted(
            report.hotspots, key=lambda t: t.actual_energy_j, reverse=True
        )

        for hp in hotspots[:10]:  # top 10 hotspots
            sq = self._graph.sqs.get(hp.sq_name)
            if sq is None:
                continue

            current_device = hp.device
            current_energy = hp.actual_energy_j

            # Check all alternative devices
            for dev_name, dev_profile in self._topology.devices.items():
                if dev_name == current_device:
                    continue

                # Check constraints
                if sq.constraints:
                    compatible = True
                    for c in sq.constraints:
                        if "type" in c and dev_profile.device_type not in c["type"]:
                            compatible = False
                            break
                    if not compatible:
                        continue

                alt_energy = sq.get_energy_cost(dev_name)
                if alt_energy < current_energy:
                    savings = current_energy - alt_energy
                    savings_pct = (savings / current_energy * 100) if current_energy > 0 else 0

                    # Time impact
                    current_time = sq.get_exec_time(current_device)
                    alt_time = sq.get_exec_time(dev_name)
                    time_impact = alt_time - current_time

                    suggestions.append(MigrationSuggestion(
                        sq_name=hp.sq_name,
                        current_device=current_device,
                        suggested_device=dev_name,
                        current_energy_j=current_energy,
                        suggested_energy_j=alt_energy,
                        savings_j=savings,
                        savings_pct=savings_pct,
                        exec_time_impact_ms=time_impact,
                    ))

        # Sort by savings
        suggestions.sort(key=lambda s: s.savings_j, reverse=True)
        return suggestions

    def _build_summary(self, report: EnergyReport) -> str:
        lines = [
            f"Energy Analysis: {report.total_actual_j:.4f}J actual "
            f"vs {report.total_estimated_j:.4f}J estimated "
            f"({report.total_deviation_pct:+.1f}%)"
        ]
        if report.hotspots:
            lines.append(f"  {len(report.hotspots)} energy hotspot(s) detected")
        if report.budget_violations:
            devs = [d.device for d in report.budget_violations]
            lines.append(f"  Budget violations on: {', '.join(devs)}")
        if report.migration_suggestions:
            best = report.migration_suggestions[0]
            lines.append(
                f"  Top suggestion: move '{best.sq_name}' from {best.current_device} "
                f"to {best.suggested_device} (save {best.savings_j:.4f}J, "
                f"{best.exec_time_impact_ms:+.1f}ms time impact)"
            )
        return "\n".join(lines)
