"""
Automatic criticality classification (Section 6.1.3 of Cozaik paper).

Computes structural importance based on:
- Convergence: number of input edges (fan-in)
- Fan-out: number of output edges
- Bridge score: whether removal disconnects the graph
- Pipeline position: source bonus, sink penalty

structural_importance = 0.4 * bottleneck_score + 0.4 * convergence + 0.2 * position_score

Thresholds: >= 7.0 -> essential, >= 3.0 -> important, else normal
"""

from __future__ import annotations
from typing import Dict

from cozaik_debugger.models.graph import TTGraph
from cozaik_debugger.models.sq import Criticality


class CriticalityAnalyzer:
    """Computes criticality for all SQs in a graph via structural analysis."""

    def __init__(self, graph: TTGraph) -> None:
        self._graph = graph

    def analyze(self) -> Dict[str, Criticality]:
        """Compute criticality for every SQ in the graph."""
        scores = self._compute_structural_importance()
        result = {}
        for sq_name, score in scores.items():
            if score >= 7.0:
                crit = Criticality.ESSENTIAL
            elif score >= 3.0:
                crit = Criticality.IMPORTANT
            else:
                crit = Criticality.NORMAL
            result[sq_name] = crit
            self._graph.sqs[sq_name].criticality = crit
            self._graph.sqs[sq_name].structural_importance = score
        return result

    def _compute_structural_importance(self) -> Dict[str, float]:
        scores: Dict[str, float] = {}

        for sq_name in self._graph.sqs:
            preds = self._graph.predecessors(sq_name)
            succs = self._graph.successors(sq_name)

            convergence = len(preds)
            fan_out = len(succs)

            # Bottleneck score: combination of convergence and fan-out
            bottleneck = convergence + fan_out

            # Bridge detection: simplified - SQs that are sole connections
            bridge_score = 0.0
            if convergence >= 2 and fan_out >= 2:
                bridge_score = 2.0
            elif convergence >= 1 and fan_out >= 1:
                bridge_score = 1.0
            bottleneck += bridge_score

            # Position score
            position = 0.0
            if convergence == 0:  # source node
                position = 2.0
            elif fan_out == 0:  # sink node
                position = -1.0

            importance = 0.4 * bottleneck + 0.4 * convergence + 0.2 * position
            scores[sq_name] = importance

        return scores
