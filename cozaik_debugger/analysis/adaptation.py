"""
Adaptation analysis module.

Analyzes runtime adaptation decisions: why they happened, what was decided,
whether the decision preserved constraints, and how it affected performance.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List

from cozaik_debugger.trace.formats import (
    DeploymentTrace,
    AdaptationRecord,
    AdaptationTrigger,
)


@dataclass
class AdaptationSummary:
    """Summary statistics for all adaptations in a deployment."""
    total_adaptations: int = 0
    by_trigger: Dict[str, int] = field(default_factory=dict)
    total_constraint_violations: int = 0
    total_tasks_degraded: int = 0
    false_positives_prevented: int = 0
    avg_adaptation_latency_ms: float = 0.0
    max_adaptation_latency_ms: float = 0.0
    success_rate_pct: float = 100.0


@dataclass
class AdaptationExplanation:
    """Human-readable explanation of a single adaptation event."""
    timestamp_ms: float
    trigger_type: str
    trigger_device: str
    what_happened: str
    why_decided: str
    what_changed: str
    impact: str
    constraint_ok: bool


@dataclass
class AdaptationReport:
    """Full adaptation analysis report."""
    summary: AdaptationSummary = field(default_factory=AdaptationSummary)
    explanations: List[AdaptationExplanation] = field(default_factory=list)
    timeline_text: str = ""


class AdaptationAnalyzer:
    """Analyzes and explains runtime adaptation decisions."""

    def __init__(self, trace: DeploymentTrace) -> None:
        self._trace = trace

    def analyze(self) -> AdaptationReport:
        """Produce a full adaptation report."""
        report = AdaptationReport()
        records = self._trace.adaptation_records

        # Summary
        summary = AdaptationSummary(total_adaptations=len(records))

        total_latency = 0.0
        max_latency = 0.0
        successes = 0

        for r in records:
            trigger_name = r.trigger.value
            summary.by_trigger[trigger_name] = (
                summary.by_trigger.get(trigger_name, 0) + 1
            )
            summary.total_constraint_violations += r.constraint_violations
            summary.total_tasks_degraded += len(r.tasks_degraded)

            if r.false_positive:
                summary.false_positives_prevented += 1

            total_latency += r.adaptation_duration_ms
            max_latency = max(max_latency, r.adaptation_duration_ms)
            if r.success:
                successes += 1

            # Generate explanation
            explanation = self._explain(r)
            report.explanations.append(explanation)

        if len(records) > 0:
            summary.avg_adaptation_latency_ms = total_latency / len(records)
            summary.max_adaptation_latency_ms = max_latency
            summary.success_rate_pct = (successes / len(records)) * 100

        report.summary = summary
        report.timeline_text = self._build_timeline(report)
        return report

    def _explain(self, r: AdaptationRecord) -> AdaptationExplanation:
        """Generate a human-readable explanation for one adaptation event."""

        # What happened (Trigger)
        if r.trigger == AdaptationTrigger.DEVICE_FAILURE:
            what = f"Device '{r.trigger_device}' stopped responding"
        elif r.trigger == AdaptationTrigger.FALSE_POSITIVE:
            what = (
                f"Device '{r.trigger_device}' missed heartbeats "
                f"but recovered during grace period"
            )
        elif r.trigger == AdaptationTrigger.DEVICE_RECONNECTION:
            what = f"Previously failed device '{r.trigger_device}' came back online"
        elif r.trigger == AdaptationTrigger.NEW_DEVICE:
            what = f"New device '{r.trigger_device}' joined the cluster"
        elif r.trigger == AdaptationTrigger.DEADLINE_MISS:
            what = f"Deadline missed, triggered by device '{r.trigger_device}'"
        else:
            what = f"Energy budget exceeded on '{r.trigger_device}'"

        # Why decided (Validate + Decide)
        why_parts = []
        if r.validation_method:
            why_parts.append(f"Validated via {r.validation_method}")
            if r.validation_duration_ms > 0:
                why_parts.append(f"({r.validation_duration_ms:.1f}ms)")
        if r.selection_reason:
            why_parts.append(f"Selected because: {r.selection_reason}")
        if r.deployment_strategy:
            why_parts.append(f"Using {r.deployment_strategy} adaptation logic")
        why = ". ".join(why_parts) if why_parts else "No validation details"

        # What changed (Act)
        change_parts = []
        if r.decision:
            change_parts.append(f"Decision: {r.decision}")
        if r.affected_tasks:
            change_parts.append(f"Affected tasks: {', '.join(r.affected_tasks)}")
        for detail in r.remapping_details:
            change_parts.append(
                f"  {detail.get('sq', '?')}: "
                f"{detail.get('from_device', '?')} -> {detail.get('to_device', '?')} "
                f"(reason: {detail.get('reason', 'N/A')})"
            )
        if r.tasks_degraded:
            change_parts.append(
                f"Degraded tasks: {', '.join(r.tasks_degraded)}"
            )
        what_changed = "\n".join(change_parts) if change_parts else "No changes"

        # Impact
        impact_parts = []
        impact_parts.append(
            f"Completed in {r.adaptation_duration_ms:.2f}ms"
        )
        if r.constraint_violations > 0:
            impact_parts.append(
                f"WARNING: {r.constraint_violations} constraint violation(s)"
            )
        impact_parts.append(f"Success: {r.success}")
        impact = ". ".join(impact_parts)

        return AdaptationExplanation(
            timestamp_ms=r.timestamp_ms,
            trigger_type=r.trigger.value,
            trigger_device=r.trigger_device,
            what_happened=what,
            why_decided=why,
            what_changed=what_changed,
            impact=impact,
            constraint_ok=r.constraint_violations == 0,
        )

    def _build_timeline(self, report: AdaptationReport) -> str:
        """Build a text timeline of all adaptation events."""
        lines = [
            f"=== Adaptation Timeline ({report.summary.total_adaptations} events) ==="
        ]
        for i, exp in enumerate(report.explanations, 1):
            lines.append(f"\n[{i}] t={exp.timestamp_ms:.1f}ms  {exp.trigger_type}")
            lines.append(f"    Trigger: {exp.what_happened}")
            lines.append(f"    Reason:  {exp.why_decided}")
            lines.append(f"    Action:  {exp.what_changed}")
            lines.append(f"    Impact:  {exp.impact}")
            if not exp.constraint_ok:
                lines.append("    *** CONSTRAINT VIOLATION ***")
        return "\n".join(lines)
