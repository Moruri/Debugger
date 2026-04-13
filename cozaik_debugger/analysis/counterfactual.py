"""
Counterfactual ("what-if") analysis module.

Given a trace where a deadline was missed, evaluates alternative placements
to determine which would have met the deadline. Uses the same cost models
as QPF optimization to re-estimate makespan and energy.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from cozaik_debugger.models.graph import TTGraph
from cozaik_debugger.models.device import DeviceTopology
from cozaik_debugger.models.placement import Placement, PlacementAlternatives
from cozaik_debugger.engine.cost_models import ObjectiveCalculator, ScheduleResult


@dataclass
class AlternativePlacement:
    """One alternative placement scenario and its predicted outcome."""
    description: str
    changed_tasks: Dict[str, str]  # {sq_name: new_device}
    predicted_makespan_ms: float
    predicted_energy_j: float
    original_makespan_ms: float
    original_energy_j: float
    deadline_ms: float
    would_meet_deadline: bool
    makespan_improvement_ms: float
    makespan_improvement_pct: float
    energy_change_j: float


@dataclass
class CounterfactualReport:
    """Complete counterfactual analysis for a missed deadline."""
    violated_sq: str
    bottleneck_sq: str
    original_makespan_ms: float
    deadline_ms: float

    alternatives: List[AlternativePlacement] = field(default_factory=list)
    best_alternative: Optional[AlternativePlacement] = None

    summary: str = ""


class CounterfactualAnalyzer:
    """
    Tests alternative placements against the cost model to find
    placements that would have met a missed deadline.
    """

    def __init__(
        self,
        graph: TTGraph,
        topology: DeviceTopology,
        placement: Placement,
        alternatives: Optional[PlacementAlternatives] = None,
    ) -> None:
        self._graph = graph
        self._topology = topology
        self._placement = placement
        self._alternatives = alternatives
        self._calc = ObjectiveCalculator(graph, topology)

    def analyze(
        self,
        bottleneck_sq: str,
        deadline_ms: float,
        violated_sq: str = "",
    ) -> CounterfactualReport:
        """
        Given a bottleneck task, try moving it to each alternative device
        and recalculate makespan.

        Also tries moving predecessors and successors of the bottleneck.
        """
        original_schedule = self._calc.calculate_makespan(self._placement)
        original_energy = self._calc.calculate_energy(self._placement)

        report = CounterfactualReport(
            violated_sq=violated_sq or bottleneck_sq,
            bottleneck_sq=bottleneck_sq,
            original_makespan_ms=original_schedule.makespan,
            deadline_ms=deadline_ms,
        )

        # Strategy 1: Move the bottleneck task to each eligible device
        self._try_task_moves(
            report, [bottleneck_sq], original_schedule, original_energy, deadline_ms
        )

        # Strategy 2: Move predecessors of the bottleneck
        preds = self._graph.predecessors(bottleneck_sq)
        for pred in preds:
            self._try_task_moves(
                report, [pred], original_schedule, original_energy, deadline_ms
            )

        # Strategy 3: If QPF alternatives are available, use them
        if self._alternatives:
            self._try_qpf_alternatives(
                report, bottleneck_sq, original_schedule, original_energy, deadline_ms
            )

        # Sort alternatives by makespan improvement
        report.alternatives.sort(
            key=lambda a: a.predicted_makespan_ms
        )

        # Find best alternative that meets the deadline
        for alt in report.alternatives:
            if alt.would_meet_deadline:
                report.best_alternative = alt
                break

        report.summary = self._build_summary(report)
        return report

    def _try_task_moves(
        self,
        report: CounterfactualReport,
        sq_names: List[str],
        original_schedule: ScheduleResult,
        original_energy: float,
        deadline_ms: float,
    ) -> None:
        """Try moving each specified SQ to each eligible alternative device."""
        for sq_name in sq_names:
            sq = self._graph.sqs.get(sq_name)
            if sq is None:
                continue

            current_device = self._placement.get_device(sq_name)

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

                # Create modified placement
                new_mapping = dict(self._placement.mapping)
                new_mapping[sq_name] = dev_name
                new_placement = Placement(
                    mapping=new_mapping,
                    strategy=self._placement.strategy,
                    objective=self._placement.objective,
                )

                # Recalculate
                new_schedule = self._calc.calculate_makespan(new_placement)
                new_energy = self._calc.calculate_energy(new_placement)
                improvement = original_schedule.makespan - new_schedule.makespan
                improvement_pct = (
                    (improvement / original_schedule.makespan * 100)
                    if original_schedule.makespan > 0 else 0
                )

                alt = AlternativePlacement(
                    description=f"Move '{sq_name}' from {current_device} to {dev_name}",
                    changed_tasks={sq_name: dev_name},
                    predicted_makespan_ms=new_schedule.makespan,
                    predicted_energy_j=new_energy,
                    original_makespan_ms=original_schedule.makespan,
                    original_energy_j=original_energy,
                    deadline_ms=deadline_ms,
                    would_meet_deadline=new_schedule.makespan <= deadline_ms,
                    makespan_improvement_ms=improvement,
                    makespan_improvement_pct=improvement_pct,
                    energy_change_j=new_energy - original_energy,
                )
                report.alternatives.append(alt)

    def _try_qpf_alternatives(
        self,
        report: CounterfactualReport,
        bottleneck_sq: str,
        original_schedule: ScheduleResult,
        original_energy: float,
        deadline_ms: float,
    ) -> None:
        """Use precomputed QPF alternatives for the bottleneck task."""
        alts = self._alternatives.get_alternatives(bottleneck_sq)
        current_device = self._placement.get_device(bottleneck_sq)

        for pa in alts:
            if pa.device == current_device:
                continue

            new_mapping = dict(self._placement.mapping)
            new_mapping[bottleneck_sq] = pa.device
            new_placement = Placement(mapping=new_mapping)

            new_schedule = self._calc.calculate_makespan(new_placement)
            new_energy = self._calc.calculate_energy(new_placement)
            improvement = original_schedule.makespan - new_schedule.makespan
            improvement_pct = (
                (improvement / original_schedule.makespan * 100)
                if original_schedule.makespan > 0 else 0
            )

            alt = AlternativePlacement(
                description=(
                    f"QPF alternative rank {pa.rank}: "
                    f"move '{bottleneck_sq}' to {pa.device}"
                ),
                changed_tasks={bottleneck_sq: pa.device},
                predicted_makespan_ms=new_schedule.makespan,
                predicted_energy_j=new_energy,
                original_makespan_ms=original_schedule.makespan,
                original_energy_j=original_energy,
                deadline_ms=deadline_ms,
                would_meet_deadline=new_schedule.makespan <= deadline_ms,
                makespan_improvement_ms=improvement,
                makespan_improvement_pct=improvement_pct,
                energy_change_j=new_energy - original_energy,
            )
            report.alternatives.append(alt)

    def _build_summary(self, report: CounterfactualReport) -> str:
        lines = [
            f"Counterfactual analysis for '{report.violated_sq}' "
            f"(deadline: {report.deadline_ms:.1f}ms, "
            f"actual: {report.original_makespan_ms:.1f}ms)"
        ]
        lines.append(f"  Bottleneck: '{report.bottleneck_sq}'")
        lines.append(f"  {len(report.alternatives)} alternative placements evaluated")

        meeting = [a for a in report.alternatives if a.would_meet_deadline]
        lines.append(f"  {len(meeting)} would meet the deadline")

        if report.best_alternative:
            b = report.best_alternative
            lines.append(
                f"  Best: {b.description} -> "
                f"{b.predicted_makespan_ms:.1f}ms "
                f"({b.makespan_improvement_pct:+.1f}%)"
            )
        else:
            lines.append("  No single-task move can meet the deadline")

        return "\n".join(lines)
