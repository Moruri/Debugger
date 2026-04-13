"""
Root-cause analysis for timing violations.

Given a missed deadline, walks backwards through the DAG to find:
- Which predecessor was the bottleneck (latest to finish)
- Whether delay was from execution time or communication
- Whether device contention contributed
- The full causal chain from root cause to missed deadline
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from cozaik_debugger.models.graph import TTGraph
from cozaik_debugger.models.placement import Placement
from cozaik_debugger.trace.formats import DeploymentTrace, TraceRecord


class DelaySource(Enum):
    EXECUTION_SLOWER_THAN_ESTIMATED = "execution_slower"
    COMMUNICATION_DELAY = "communication_delay"
    DEVICE_CONTENTION = "device_contention"
    PREDECESSOR_LATE = "predecessor_late"
    DATA_LARGER_THAN_ESTIMATED = "data_larger"
    UNKNOWN = "unknown"


@dataclass
class CausalLink:
    """One link in the causal chain from root to deadline miss."""
    sq_name: str
    device: str
    delay_source: DelaySource
    delay_ms: float
    expected_ms: float
    actual_ms: float
    explanation: str


@dataclass
class RootCauseReport:
    """Complete root-cause analysis for a single deadline violation."""
    violated_sq: str
    violated_device: str
    deadline_ms: float
    actual_finish_ms: float
    overshoot_ms: float

    # The SQ that was the primary bottleneck
    bottleneck_sq: str = ""
    bottleneck_device: str = ""
    bottleneck_source: DelaySource = DelaySource.UNKNOWN

    # Full causal chain from root cause to deadline miss
    causal_chain: List[CausalLink] = field(default_factory=list)

    # Contributing factors
    execution_delay_total_ms: float = 0.0
    communication_delay_total_ms: float = 0.0
    contention_delay_total_ms: float = 0.0

    # Summary
    summary: str = ""


class RootCauseAnalyzer:
    """
    Analyzes timing violations by walking the DAG backwards from
    the missed-deadline task to find the root cause.
    """

    def __init__(
        self,
        graph: TTGraph,
        trace: DeploymentTrace,
        placement: Placement,
    ) -> None:
        self._graph = graph
        self._trace = trace
        self._placement = placement

    def analyze_violation(
        self, sq_name: str, iteration: int = 0
    ) -> RootCauseReport:
        """
        Trace back from a missed-deadline SQ to find root cause.

        Walks backwards through the DAG, at each step identifying
        whether the delay came from execution, communication, or contention.
        """
        records = self._build_record_map(iteration)
        target = records.get(sq_name)
        if target is None:
            return RootCauseReport(
                violated_sq=sq_name, violated_device="unknown",
                deadline_ms=0, actual_finish_ms=0, overshoot_ms=0,
                summary=f"No trace record found for {sq_name} iteration {iteration}",
            )

        deadline = target.deadline_ms or 0.0
        overshoot = target.actual_exec_time_ms - deadline if deadline else 0.0

        report = RootCauseReport(
            violated_sq=sq_name,
            violated_device=target.device,
            deadline_ms=deadline,
            actual_finish_ms=target.end_time_ms,
            overshoot_ms=max(0, overshoot),
        )

        # Walk backwards through the DAG
        chain = self._walk_backwards(sq_name, records, iteration)
        report.causal_chain = chain

        # Aggregate delay sources
        for link in chain:
            if link.delay_source == DelaySource.EXECUTION_SLOWER_THAN_ESTIMATED:
                report.execution_delay_total_ms += link.delay_ms
            elif link.delay_source == DelaySource.COMMUNICATION_DELAY:
                report.communication_delay_total_ms += link.delay_ms
            elif link.delay_source == DelaySource.DEVICE_CONTENTION:
                report.contention_delay_total_ms += link.delay_ms

        # Find the single biggest bottleneck
        if chain:
            worst = max(chain, key=lambda l: l.delay_ms)
            report.bottleneck_sq = worst.sq_name
            report.bottleneck_device = worst.device
            report.bottleneck_source = worst.delay_source

        # Build summary
        report.summary = self._build_summary(report)
        return report

    def analyze_all_violations(
        self, iteration: int = 0
    ) -> List[RootCauseReport]:
        """Analyze all missed deadlines in the given iteration."""
        reports = []
        for record in self._trace.records_for_iteration(iteration):
            if record.deadline_met is False:
                reports.append(self.analyze_violation(record.sq_name, iteration))
        return reports

    def _walk_backwards(
        self,
        sq_name: str,
        records: Dict[str, TraceRecord],
        iteration: int,
    ) -> List[CausalLink]:
        """Walk the DAG backwards from sq_name, identifying delays at each step."""
        chain: List[CausalLink] = []
        visited = set()
        stack = [sq_name]

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)

            record = records.get(current)
            if record is None:
                continue

            # Check if this SQ ran slower than estimated
            time_dev = record.time_deviation_ms
            if time_dev > 0.5:  # more than 0.5ms slower
                chain.append(CausalLink(
                    sq_name=current,
                    device=record.device,
                    delay_source=DelaySource.EXECUTION_SLOWER_THAN_ESTIMATED,
                    delay_ms=time_dev,
                    expected_ms=record.estimated_exec_time_ms,
                    actual_ms=record.actual_exec_time_ms,
                    explanation=(
                        f"{current} on {record.device}: "
                        f"exec took {record.actual_exec_time_ms:.1f}ms "
                        f"vs estimated {record.estimated_exec_time_ms:.1f}ms "
                        f"(+{time_dev:.1f}ms)"
                    ),
                ))

            # Check device contention
            if record.concurrent_sqs:
                # Estimate contention overhead (simple model: proportional sharing)
                n_concurrent = len(record.concurrent_sqs) + 1
                if n_concurrent > 1 and record.execution_mode == "timesliced":
                    overhead = record.actual_exec_time_ms * (n_concurrent - 1) / n_concurrent
                    chain.append(CausalLink(
                        sq_name=current,
                        device=record.device,
                        delay_source=DelaySource.DEVICE_CONTENTION,
                        delay_ms=overhead,
                        expected_ms=record.estimated_exec_time_ms,
                        actual_ms=record.actual_exec_time_ms,
                        explanation=(
                            f"{current} on {record.device}: "
                            f"contended with {record.concurrent_sqs} "
                            f"({record.execution_mode} mode, ~{overhead:.1f}ms overhead)"
                        ),
                    ))

            # Check communication delays from predecessors
            predecessors = self._graph.predecessors(current)
            for pred in predecessors:
                comm_records = [
                    c for c in self._trace.communication_records
                    if c.source_sq == pred and c.target_sq == current
                    and c.iteration == iteration
                ]
                for comm in comm_records:
                    comm_dev = comm.transfer_deviation_ms
                    if comm_dev > 0.5:
                        chain.append(CausalLink(
                            sq_name=pred,
                            device=comm.source_device,
                            delay_source=DelaySource.COMMUNICATION_DELAY,
                            delay_ms=comm_dev,
                            expected_ms=comm.estimated_transfer_time_ms,
                            actual_ms=comm.actual_transfer_time_ms,
                            explanation=(
                                f"{pred}->{current} "
                                f"({comm.source_device}->{comm.target_device}): "
                                f"transfer took {comm.actual_transfer_time_ms:.1f}ms "
                                f"vs estimated {comm.estimated_transfer_time_ms:.1f}ms"
                            ),
                        ))

                stack.append(pred)

        return chain

    def _build_record_map(self, iteration: int) -> Dict[str, TraceRecord]:
        records = {}
        for r in self._trace.records_for_iteration(iteration):
            records[r.sq_name] = r
        return records

    def _build_summary(self, report: RootCauseReport) -> str:
        parts = [
            f"Deadline violation at '{report.violated_sq}' on {report.violated_device}: "
            f"missed by {report.overshoot_ms:.1f}ms"
        ]
        if report.execution_delay_total_ms > 0:
            parts.append(
                f"  Execution delays: {report.execution_delay_total_ms:.1f}ms total"
            )
        if report.communication_delay_total_ms > 0:
            parts.append(
                f"  Communication delays: {report.communication_delay_total_ms:.1f}ms total"
            )
        if report.contention_delay_total_ms > 0:
            parts.append(
                f"  Contention overhead: {report.contention_delay_total_ms:.1f}ms total"
            )
        if report.bottleneck_sq:
            parts.append(
                f"  Primary bottleneck: '{report.bottleneck_sq}' on "
                f"{report.bottleneck_device} ({report.bottleneck_source.value})"
            )
        return "\n".join(parts)
