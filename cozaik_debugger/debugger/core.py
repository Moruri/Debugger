"""
Unified debugger interface for Cozaik DTS applications.

Combines all analysis modules into a single entry point.
Loads traces, runs analysis, and produces structured reports.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from cozaik_debugger.models.graph import TTGraph
from cozaik_debugger.models.device import DeviceTopology
from cozaik_debugger.models.placement import Placement, PlacementAlternatives
from cozaik_debugger.trace.formats import DeploymentTrace
from cozaik_debugger.analysis.timeline import TimelineReconstructor, GlobalTimeline
from cozaik_debugger.analysis.root_cause import RootCauseAnalyzer, RootCauseReport
from cozaik_debugger.analysis.energy import EnergyAnalyzer, EnergyReport
from cozaik_debugger.analysis.counterfactual import (
    CounterfactualAnalyzer,
    CounterfactualReport,
)
from cozaik_debugger.analysis.adaptation import AdaptationAnalyzer, AdaptationReport
from cozaik_debugger.engine.cost_models import ObjectiveCalculator, ScheduleResult


@dataclass
class DebuggingIssue:
    """A flagged issue found during analysis."""
    severity: str  # "critical", "warning", "info"
    category: str  # "deadline", "energy", "contention", "adaptation"
    title: str
    description: str
    sq_name: str = ""
    device: str = ""
    iteration: int = 0


@dataclass
class FullDebugReport:
    """Complete debugging report for a deployment."""
    deployment_id: str = ""

    # Analysis results
    schedule: Optional[ScheduleResult] = None
    timeline: Optional[GlobalTimeline] = None
    root_cause_reports: List[RootCauseReport] = field(default_factory=list)
    energy_report: Optional[EnergyReport] = None
    counterfactual_reports: List[CounterfactualReport] = field(default_factory=list)
    adaptation_report: Optional[AdaptationReport] = None

    # Flagged issues
    issues: List[DebuggingIssue] = field(default_factory=list)

    # Summaries
    executive_summary: str = ""

    @property
    def critical_issues(self) -> List[DebuggingIssue]:
        return [i for i in self.issues if i.severity == "critical"]

    @property
    def warnings(self) -> List[DebuggingIssue]:
        return [i for i in self.issues if i.severity == "warning"]


class CozaikDebugger:
    """
    Main debugger entry point.

    Usage:
        debugger = CozaikDebugger(graph, topology, placement, trace)
        report = debugger.run_full_analysis()
        print(report.executive_summary)

        # Or query specific things:
        violations = debugger.find_deadline_violations()
        timeline = debugger.reconstruct_timeline(iteration=0)
        counterfactual = debugger.what_if("bottleneck_sq", deadline_ms=100)
    """

    def __init__(
        self,
        graph: TTGraph,
        topology: DeviceTopology,
        placement: Placement,
        trace: DeploymentTrace,
        alternatives: Optional[PlacementAlternatives] = None,
    ) -> None:
        self._graph = graph
        self._topology = topology
        self._placement = placement
        self._trace = trace
        self._alternatives = alternatives

        # Analyzers (lazy init)
        self._calc = ObjectiveCalculator(graph, topology)
        self._timeline_analyzer = TimelineReconstructor(trace)
        self._root_cause_analyzer = RootCauseAnalyzer(graph, trace, placement)
        self._energy_analyzer = EnergyAnalyzer(graph, topology, trace, placement)
        self._counterfactual_analyzer = CounterfactualAnalyzer(
            graph, topology, placement, alternatives
        )
        self._adaptation_analyzer = AdaptationAnalyzer(trace)

    # ---- Full analysis ----

    def run_full_analysis(
        self, iteration: Optional[int] = None
    ) -> FullDebugReport:
        """Run all analyses and produce a complete debugging report."""
        report = FullDebugReport(
            deployment_id=self._trace.deployment_id,
        )

        # 1. Estimated schedule from cost model
        report.schedule = self._calc.calculate_makespan(self._placement)

        # 2. Actual timeline from traces
        report.timeline = self._timeline_analyzer.reconstruct(iteration)

        # 3. Find and analyze deadline violations
        target_iter = iteration if iteration is not None else 0
        violations = self._trace.missed_deadlines()
        if iteration is not None:
            violations = [v for v in violations if v.iteration == iteration]

        for v in violations:
            rc = self._root_cause_analyzer.analyze_violation(
                v.sq_name, v.iteration
            )
            report.root_cause_reports.append(rc)

            report.issues.append(DebuggingIssue(
                severity="critical",
                category="deadline",
                title=f"Deadline missed: {v.sq_name}",
                description=rc.summary,
                sq_name=v.sq_name,
                device=v.device,
                iteration=v.iteration,
            ))

            # Run counterfactual on the bottleneck
            if rc.bottleneck_sq and v.deadline_ms:
                cf = self._counterfactual_analyzer.analyze(
                    bottleneck_sq=rc.bottleneck_sq,
                    deadline_ms=v.deadline_ms,
                    violated_sq=v.sq_name,
                )
                report.counterfactual_reports.append(cf)

        # 4. Energy analysis
        report.energy_report = self._energy_analyzer.analyze(iteration)
        for hp in report.energy_report.hotspots:
            report.issues.append(DebuggingIssue(
                severity="warning",
                category="energy",
                title=f"Energy hotspot: {hp.sq_name}",
                description=(
                    f"{hp.sq_name} on {hp.device}: "
                    f"{hp.actual_energy_j:.4f}J actual vs "
                    f"{hp.estimated_energy_j:.4f}J estimated "
                    f"({hp.deviation_pct:+.1f}%)"
                ),
                sq_name=hp.sq_name,
                device=hp.device,
            ))
        for bv in report.energy_report.budget_violations:
            report.issues.append(DebuggingIssue(
                severity="critical",
                category="energy",
                title=f"Energy budget exceeded: {bv.device}",
                description=(
                    f"Device {bv.device}: {bv.total_actual_j:.4f}J used "
                    f"vs {bv.energy_budget_j:.4f}J budget"
                ),
                device=bv.device,
            ))

        # 5. Contention issues
        if report.timeline:
            for cg in report.timeline.all_contentions:
                task_names = [t.sq_name for t in cg.tasks]
                report.issues.append(DebuggingIssue(
                    severity="warning" if not cg.cross_application else "critical",
                    category="contention",
                    title=f"Contention on {cg.device}",
                    description=(
                        f"Tasks {task_names} overlap for "
                        f"{cg.overlap_duration_ms:.1f}ms on {cg.device}"
                        + (" (CROSS-APP)" if cg.cross_application else "")
                    ),
                    device=cg.device,
                ))

        # 6. Adaptation analysis
        report.adaptation_report = self._adaptation_analyzer.analyze()
        ada = report.adaptation_report
        if ada.summary.total_constraint_violations > 0:
            report.issues.append(DebuggingIssue(
                severity="critical",
                category="adaptation",
                title="Constraint violations during adaptation",
                description=(
                    f"{ada.summary.total_constraint_violations} "
                    f"constraint violation(s) across "
                    f"{ada.summary.total_adaptations} adaptation events"
                ),
            ))

        # Executive summary
        report.executive_summary = self._build_executive_summary(report)
        return report

    # ---- Individual queries ----

    def reconstruct_timeline(
        self, iteration: Optional[int] = None
    ) -> GlobalTimeline:
        return self._timeline_analyzer.reconstruct(iteration)

    def find_deadline_violations(
        self, iteration: Optional[int] = None
    ) -> List[RootCauseReport]:
        violations = self._trace.missed_deadlines()
        if iteration is not None:
            violations = [v for v in violations if v.iteration == iteration]
        return [
            self._root_cause_analyzer.analyze_violation(v.sq_name, v.iteration)
            for v in violations
        ]

    def analyze_energy(
        self, iteration: Optional[int] = None
    ) -> EnergyReport:
        return self._energy_analyzer.analyze(iteration)

    def what_if(
        self,
        bottleneck_sq: str,
        deadline_ms: float,
        violated_sq: str = "",
    ) -> CounterfactualReport:
        return self._counterfactual_analyzer.analyze(
            bottleneck_sq, deadline_ms, violated_sq
        )

    def explain_adaptations(self) -> AdaptationReport:
        return self._adaptation_analyzer.analyze()

    def get_estimated_schedule(self) -> ScheduleResult:
        return self._calc.calculate_makespan(self._placement)

    # ---- Summary ----

    def _build_executive_summary(self, report: FullDebugReport) -> str:
        lines = [
            f"{'='*60}",
            f"  COZAIK DEBUGGER REPORT: {report.deployment_id}",
            f"{'='*60}",
        ]

        n_critical = len(report.critical_issues)
        n_warnings = len(report.warnings)
        n_info = len(report.issues) - n_critical - n_warnings

        if n_critical > 0:
            lines.append(f"\n  !! {n_critical} CRITICAL issue(s)")
        if n_warnings > 0:
            lines.append(f"  !  {n_warnings} warning(s)")
        if n_info > 0:
            lines.append(f"     {n_info} informational")

        # Timing
        if report.schedule:
            lines.append(f"\n  Estimated makespan: {report.schedule.makespan:.1f}ms")
        if report.timeline:
            lines.append(
                f"  Actual duration:   {report.timeline.total_duration_ms:.1f}ms"
            )

        # Deadlines
        missed = self._trace.missed_deadlines()
        total_with_deadline = [
            r for r in self._trace.execution_records if r.deadline_ms is not None
        ]
        if total_with_deadline:
            met = len(total_with_deadline) - len(missed)
            pct = (met / len(total_with_deadline)) * 100
            lines.append(
                f"  Deadlines met: {met}/{len(total_with_deadline)} ({pct:.0f}%)"
            )

        # Energy
        if report.energy_report:
            er = report.energy_report
            lines.append(
                f"  Energy: {er.total_actual_j:.4f}J "
                f"(estimated {er.total_estimated_j:.4f}J, "
                f"{er.total_deviation_pct:+.1f}%)"
            )

        # Adaptations
        if report.adaptation_report:
            ar = report.adaptation_report.summary
            lines.append(
                f"  Adaptations: {ar.total_adaptations} "
                f"(avg latency {ar.avg_adaptation_latency_ms:.2f}ms)"
            )

        # Top issues
        if report.issues:
            lines.append(f"\n  --- Top Issues ---")
            for issue in report.issues[:5]:
                icon = "!!" if issue.severity == "critical" else "! " if issue.severity == "warning" else "  "
                lines.append(f"  {icon} [{issue.category}] {issue.title}")

        # Counterfactual suggestions
        for cf in report.counterfactual_reports:
            if cf.best_alternative:
                b = cf.best_alternative
                lines.append(f"\n  --- Suggested Fix ---")
                lines.append(f"  {b.description}")
                lines.append(
                    f"  Would achieve {b.predicted_makespan_ms:.1f}ms "
                    f"({b.makespan_improvement_pct:+.1f}%)"
                )

        lines.append(f"\n{'='*60}")
        return "\n".join(lines)
