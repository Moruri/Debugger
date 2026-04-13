"""
Terminal-based visualization for the Cozaik debugger.

Renders execution timelines, deadline violations, energy hotspots,
and adaptation events as colored text in the terminal.
"""

from __future__ import annotations
from typing import Dict, List, Optional

from cozaik_debugger.analysis.timeline import GlobalTimeline, TaskWindow
from cozaik_debugger.analysis.root_cause import RootCauseReport
from cozaik_debugger.analysis.energy import EnergyReport
from cozaik_debugger.analysis.counterfactual import CounterfactualReport
from cozaik_debugger.analysis.adaptation import AdaptationReport
from cozaik_debugger.debugger.core import FullDebugReport, DebuggingIssue


# ANSI color codes
class _C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_RED = "\033[41m"
    BG_YELLOW = "\033[43m"
    BG_GREEN = "\033[42m"
    BG_BLUE = "\033[44m"


# Color palette for devices
_DEVICE_COLORS = [_C.CYAN, _C.GREEN, _C.MAGENTA, _C.YELLOW, _C.BLUE, _C.WHITE]


class TerminalVisualizer:
    """Renders debugger results to the terminal with color."""

    def __init__(self, width: int = 100, use_color: bool = True) -> None:
        self._width = width
        self._color = use_color

    def render_full_report(self, report: FullDebugReport) -> str:
        """Render the complete debugging report."""
        sections = []

        sections.append(self._render_header(report))

        if report.timeline:
            sections.append(self._render_timeline(report.timeline))

        if report.issues:
            sections.append(self._render_issues(report.issues))

        if report.root_cause_reports:
            sections.append(self._render_root_causes(report.root_cause_reports))

        if report.energy_report:
            sections.append(self._render_energy(report.energy_report))

        if report.counterfactual_reports:
            sections.append(
                self._render_counterfactuals(report.counterfactual_reports)
            )

        if report.adaptation_report:
            sections.append(
                self._render_adaptations(report.adaptation_report)
            )

        return "\n".join(sections)

    # ---- Header ----

    def _render_header(self, report: FullDebugReport) -> str:
        lines = []
        lines.append(self._c(f"\n{'='*self._width}", _C.BOLD))
        lines.append(self._c(
            f"  COZAIK DEBUGGER REPORT: {report.deployment_id}",
            _C.BOLD + _C.CYAN,
        ))
        lines.append(self._c(f"{'='*self._width}", _C.BOLD))

        n_crit = len(report.critical_issues)
        n_warn = len(report.warnings)

        if n_crit > 0:
            lines.append(self._c(
                f"  {n_crit} CRITICAL issue(s)", _C.BOLD + _C.RED
            ))
        if n_warn > 0:
            lines.append(self._c(
                f"  {n_warn} warning(s)", _C.YELLOW
            ))
        if n_crit == 0 and n_warn == 0:
            lines.append(self._c("  All clear - no issues detected", _C.GREEN))

        return "\n".join(lines)

    # ---- Timeline ----

    def _render_timeline(self, timeline: GlobalTimeline) -> str:
        lines = []
        lines.append(self._section_header("EXECUTION TIMELINE"))

        if timeline.total_duration_ms <= 0:
            lines.append("  No execution data")
            return "\n".join(lines)

        # Assign colors to devices
        device_names = sorted(timeline.device_timelines.keys())
        color_map = {}
        for i, name in enumerate(device_names):
            color_map[name] = _DEVICE_COLORS[i % len(_DEVICE_COLORS)]

        # Scale: how many ms per character
        bar_width = self._width - 30  # leave room for labels
        scale = timeline.total_duration_ms / max(bar_width, 1)

        # Find global start
        global_start = float("inf")
        for dt in timeline.device_timelines.values():
            for w in dt.windows:
                global_start = min(global_start, w.start_ms)
        if global_start == float("inf"):
            global_start = 0

        lines.append(self._c(
            f"  Duration: {timeline.total_duration_ms:.1f}ms  "
            f"Scale: 1 char = {scale:.1f}ms",
            _C.DIM,
        ))
        lines.append("")

        for dev_name in device_names:
            dt = timeline.device_timelines[dev_name]
            color = color_map[dev_name]

            # Build the bar
            bar = [" "] * bar_width
            for w in dt.windows:
                start_pos = int((w.start_ms - global_start) / scale)
                end_pos = int((w.end_ms - global_start) / scale)
                start_pos = max(0, min(start_pos, bar_width - 1))
                end_pos = max(start_pos + 1, min(end_pos, bar_width))

                char = w.sq_name[0].upper() if w.sq_name else "#"
                for p in range(start_pos, end_pos):
                    bar[p] = char

            bar_str = "".join(bar)
            label = f"  {dev_name:<14}"
            lines.append(
                self._c(label, color + _C.BOLD)
                + self._c("|", _C.DIM)
                + self._c(bar_str, color)
                + self._c("|", _C.DIM)
            )
            lines.append(self._c(
                f"  {'':14} util={dt.utilization_pct:.0f}%  "
                f"tasks={len(dt.windows)}  "
                f"contentions={len(dt.contentions)}",
                _C.DIM,
            ))

        # Time axis
        axis_label = f"  {'':14} 0"
        mid = f"{timeline.total_duration_ms/2:.0f}ms"
        end = f"{timeline.total_duration_ms:.0f}ms"
        pad = bar_width - len(mid) - len(end)
        axis_label += " " * max(1, pad // 2) + mid + " " * max(1, pad - pad // 2) + end
        lines.append(self._c(axis_label, _C.DIM))

        return "\n".join(lines)

    # ---- Issues ----

    def _render_issues(self, issues: List[DebuggingIssue]) -> str:
        lines = []
        lines.append(self._section_header(f"ISSUES ({len(issues)})"))

        for issue in issues:
            if issue.severity == "critical":
                icon = self._c(" !! ", _C.BG_RED + _C.WHITE + _C.BOLD)
                title_color = _C.RED + _C.BOLD
            elif issue.severity == "warning":
                icon = self._c(" !  ", _C.BG_YELLOW + _C.WHITE)
                title_color = _C.YELLOW
            else:
                icon = self._c(" i  ", _C.BLUE)
                title_color = _C.WHITE

            lines.append(
                f"  {icon} "
                + self._c(f"[{issue.category}] ", _C.DIM)
                + self._c(issue.title, title_color)
            )
            if issue.description:
                for desc_line in issue.description.split("\n"):
                    lines.append(self._c(f"        {desc_line}", _C.DIM))

        return "\n".join(lines)

    # ---- Root Cause ----

    def _render_root_causes(self, reports: List[RootCauseReport]) -> str:
        lines = []
        lines.append(self._section_header("ROOT-CAUSE ANALYSIS"))

        for rc in reports:
            lines.append(self._c(
                f"  Violation: {rc.violated_sq} on {rc.violated_device}",
                _C.RED + _C.BOLD,
            ))
            lines.append(self._c(
                f"  Overshoot: {rc.overshoot_ms:.1f}ms",
                _C.RED,
            ))

            if rc.causal_chain:
                lines.append(self._c("  Causal chain:", _C.WHITE))
                for link in rc.causal_chain:
                    color = _C.RED if link.delay_ms > 5 else _C.YELLOW
                    lines.append(self._c(
                        f"    -> {link.explanation}", color
                    ))

            if rc.bottleneck_sq:
                lines.append(self._c(
                    f"  Primary bottleneck: {rc.bottleneck_sq} "
                    f"({rc.bottleneck_source.value})",
                    _C.BOLD + _C.YELLOW,
                ))
            lines.append("")

        return "\n".join(lines)

    # ---- Energy ----

    def _render_energy(self, report: EnergyReport) -> str:
        lines = []
        lines.append(self._section_header("ENERGY ANALYSIS"))

        lines.append(self._c(
            f"  Total: {report.total_actual_j:.4f}J actual "
            f"/ {report.total_estimated_j:.4f}J estimated "
            f"({report.total_deviation_pct:+.1f}%)",
            _C.WHITE,
        ))

        if report.device_profiles:
            lines.append(self._c("\n  Per-device breakdown:", _C.DIM))
            for dp in report.device_profiles:
                budget_str = ""
                if dp.energy_budget_j is not None:
                    if dp.budget_exceeded:
                        budget_str = self._c(
                            f" OVER BUDGET ({dp.energy_budget_j:.4f}J)",
                            _C.RED + _C.BOLD,
                        )
                    else:
                        budget_str = self._c(
                            f" within budget ({dp.energy_budget_j:.4f}J)",
                            _C.GREEN,
                        )
                lines.append(
                    f"    {dp.device:<14} "
                    f"{dp.total_actual_j:.4f}J"
                    + budget_str
                )

        if report.hotspots:
            lines.append(self._c(
                f"\n  Energy hotspots ({len(report.hotspots)}):", _C.YELLOW
            ))
            for hp in report.hotspots[:5]:
                lines.append(self._c(
                    f"    {hp.sq_name} on {hp.device}: "
                    f"{hp.deviation_pct:+.1f}% deviation",
                    _C.YELLOW,
                ))

        if report.migration_suggestions:
            lines.append(self._c("\n  Migration suggestions:", _C.GREEN))
            for ms in report.migration_suggestions[:3]:
                lines.append(self._c(
                    f"    Move '{ms.sq_name}': {ms.current_device} -> "
                    f"{ms.suggested_device} "
                    f"(save {ms.savings_j:.4f}J, "
                    f"{ms.exec_time_impact_ms:+.1f}ms time impact)",
                    _C.GREEN,
                ))

        return "\n".join(lines)

    # ---- Counterfactual ----

    def _render_counterfactuals(
        self, reports: List[CounterfactualReport]
    ) -> str:
        lines = []
        lines.append(self._section_header("COUNTERFACTUAL ANALYSIS (What-If)"))

        for cf in reports:
            lines.append(self._c(
                f"  Target: {cf.violated_sq}  "
                f"Bottleneck: {cf.bottleneck_sq}  "
                f"Deadline: {cf.deadline_ms:.1f}ms  "
                f"Actual: {cf.original_makespan_ms:.1f}ms",
                _C.WHITE,
            ))

            meeting = [a for a in cf.alternatives if a.would_meet_deadline]
            lines.append(self._c(
                f"  {len(cf.alternatives)} alternatives tested, "
                f"{len(meeting)} would meet deadline",
                _C.DIM,
            ))

            if cf.best_alternative:
                b = cf.best_alternative
                lines.append(self._c(
                    f"  BEST: {b.description}",
                    _C.GREEN + _C.BOLD,
                ))
                lines.append(self._c(
                    f"        -> {b.predicted_makespan_ms:.1f}ms "
                    f"({b.makespan_improvement_pct:+.1f}%), "
                    f"energy {b.energy_change_j:+.4f}J",
                    _C.GREEN,
                ))
            else:
                lines.append(self._c(
                    "  No single-task move can fix this violation",
                    _C.RED,
                ))

            # Show top 3 alternatives
            lines.append(self._c("  All alternatives:", _C.DIM))
            for alt in cf.alternatives[:5]:
                marker = self._c(" OK ", _C.BG_GREEN + _C.WHITE) if alt.would_meet_deadline else self._c("MISS", _C.RED)
                lines.append(
                    f"    {marker} {alt.description}: "
                    f"{alt.predicted_makespan_ms:.1f}ms "
                    f"({alt.makespan_improvement_pct:+.1f}%)"
                )
            lines.append("")

        return "\n".join(lines)

    # ---- Adaptations ----

    def _render_adaptations(self, report: AdaptationReport) -> str:
        lines = []
        lines.append(self._section_header("ADAPTATION EVENTS"))

        s = report.summary
        lines.append(self._c(
            f"  Total: {s.total_adaptations}  "
            f"Avg latency: {s.avg_adaptation_latency_ms:.2f}ms  "
            f"Success rate: {s.success_rate_pct:.0f}%",
            _C.WHITE,
        ))

        if s.by_trigger:
            parts = [f"{k}: {v}" for k, v in s.by_trigger.items()]
            lines.append(self._c(f"  By trigger: {', '.join(parts)}", _C.DIM))

        if s.false_positives_prevented > 0:
            lines.append(self._c(
                f"  False positives prevented: {s.false_positives_prevented}",
                _C.GREEN,
            ))

        if s.total_constraint_violations > 0:
            lines.append(self._c(
                f"  CONSTRAINT VIOLATIONS: {s.total_constraint_violations}",
                _C.RED + _C.BOLD,
            ))

        for exp in report.explanations[:10]:
            trigger_color = _C.RED if "failure" in exp.trigger_type else _C.YELLOW
            lines.append("")
            lines.append(self._c(
                f"  [{exp.trigger_type}] t={exp.timestamp_ms:.1f}ms",
                trigger_color + _C.BOLD,
            ))
            lines.append(self._c(f"    {exp.what_happened}", _C.WHITE))
            lines.append(self._c(f"    {exp.why_decided}", _C.DIM))
            for action_line in exp.what_changed.split("\n"):
                lines.append(self._c(f"    {action_line}", _C.CYAN))
            lines.append(self._c(f"    {exp.impact}", _C.DIM))

        return "\n".join(lines)

    # ---- Helpers ----

    def _section_header(self, title: str) -> str:
        line = f"\n  --- {title} ---"
        return self._c(line, _C.BOLD + _C.WHITE)

    def _c(self, text: str, color: str) -> str:
        if not self._color:
            return text
        return f"{color}{text}{_C.RESET}"
