"""
Dataflow graph models: TTGraph and ComposedGraph.

TTGraph represents a single application's compiled dataflow graph.
ComposedGraph implements SSPG unordered parallel composition
(Section 5 of Cozaik paper) for multi-application deployments.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Set

from cozaik_debugger.models.sq import SQ, Arc


class TTGraph:
    """
    A compiled TTPython/Cozaik application graph.

    Contains SQs (nodes) and Arcs (edges) forming a DAG.
    Provides networkx-compatible DAG construction.
    """

    def __init__(self, app_id: str = "default") -> None:
        self.app_id = app_id
        self.sqs: Dict[str, SQ] = {}
        self.arcs: List[Arc] = []
        self._source: Optional[str] = None
        self._sink: Optional[str] = None

    def add_sq(self, sq: SQ) -> None:
        sq.app_id = self.app_id
        self.sqs[sq.name] = sq

    def add_arc(self, arc: Arc) -> None:
        self.arcs.append(arc)

    def set_source(self, name: str) -> None:
        self._source = name

    def set_sink(self, name: str) -> None:
        self._sink = name

    @property
    def source(self) -> Optional[str]:
        """Find the source node (no incoming edges)."""
        if self._source:
            return self._source
        targets = {a.target for a in self.arcs}
        for name in self.sqs:
            if name not in targets:
                return name
        return None

    @property
    def sink(self) -> Optional[str]:
        """Find the sink node (no outgoing edges)."""
        if self._sink:
            return self._sink
        sources = {a.source for a in self.arcs}
        for name in self.sqs:
            if name not in sources:
                return name
        return None

    def predecessors(self, sq_name: str) -> List[str]:
        return [a.source for a in self.arcs if a.target == sq_name]

    def successors(self, sq_name: str) -> List[str]:
        return [a.target for a in self.arcs if a.source == sq_name]

    def get_arc(self, source: str, target: str) -> Optional[Arc]:
        for a in self.arcs:
            if a.source == source and a.target == target:
                return a
        return None

    def topological_order(self) -> List[str]:
        """Kahn's algorithm for topological sort."""
        in_degree: Dict[str, int] = {name: 0 for name in self.sqs}
        for arc in self.arcs:
            if arc.target in in_degree:
                in_degree[arc.target] += 1

        queue = [n for n, d in in_degree.items() if d == 0]
        result = []
        while queue:
            queue.sort()
            node = queue.pop(0)
            result.append(node)
            for arc in self.arcs:
                if arc.source == node and arc.target in in_degree:
                    in_degree[arc.target] -= 1
                    if in_degree[arc.target] == 0:
                        queue.append(arc.target)
        return result

    def get_all_paths(self, source: str, target: str) -> List[List[str]]:
        """Find all paths from source to target in the DAG."""
        paths = []
        self._dfs_paths(source, target, [source], paths)
        return paths

    def _dfs_paths(
        self, current: str, target: str, path: List[str], paths: List[List[str]]
    ) -> None:
        if current == target:
            paths.append(list(path))
            return
        for succ in self.successors(current):
            path.append(succ)
            self._dfs_paths(succ, target, path, paths)
            path.pop()

    def critical_path_sqs(self) -> Set[str]:
        """Identify SQs on the longest path through the graph."""
        topo = self.topological_order()
        if not topo:
            return set()

        longest_to: Dict[str, float] = {n: 0.0 for n in topo}
        pred_on_path: Dict[str, Optional[str]] = {n: None for n in topo}

        for node in topo:
            sq = self.sqs[node]
            default_time = sq.execution_time_estimates.get("default", sq.complexity)
            for succ in self.successors(node):
                dist = longest_to[node] + default_time
                if dist > longest_to[succ]:
                    longest_to[succ] = dist
                    pred_on_path[succ] = node

        # Walk back from the node with the longest finish time
        end_node = max(topo, key=lambda n: longest_to[n])
        cp = set()
        current: Optional[str] = end_node
        while current is not None:
            cp.add(current)
            current = pred_on_path[current]
        return cp


class ComposedGraph(TTGraph):
    """
    A multi-application composed graph using SSPG unordered parallel composition.

    Adds SUPER_TRIGGER (source) and BARRIER_JOIN (sink) synthetic nodes,
    prefixes all SQ names with app_id, and merges clock/constraint metadata.
    """

    def __init__(self) -> None:
        super().__init__(app_id="composed")
        self._app_graphs: Dict[str, TTGraph] = {}

    def compose(self, graphs: List[TTGraph]) -> None:
        """
        Compose multiple application graphs using SSPG Rule 4
        (unordered parallel composition).
        """
        # Create SUPER_TRIGGER
        trigger = SQ(name="SUPER_TRIGGER", app_id="composed")
        self.add_sq(trigger)
        self.set_source("SUPER_TRIGGER")

        # Create BARRIER_JOIN
        barrier = SQ(name="BARRIER_JOIN", app_id="composed")
        self.add_sq(barrier)
        self.set_sink("BARRIER_JOIN")

        for graph in graphs:
            self._app_graphs[graph.app_id] = graph

            # Step 1: Prefix all SQ names and add to composed graph
            for sq_name, sq in graph.sqs.items():
                prefixed = SQ(
                    name=f"{graph.app_id}__{sq_name}",
                    app_id=graph.app_id,
                    execution_time_estimates=sq.execution_time_estimates.copy(),
                    energy_cost_estimates=sq.energy_cost_estimates.copy(),
                    criticality=sq.criticality,
                    constraints=sq.constraints.copy(),
                    complexity=sq.complexity,
                    deadline_budget_us=sq.deadline_budget_us,
                    deadline_type=sq.deadline_type,
                    has_planb=sq.has_planb,
                    structural_importance=sq.structural_importance,
                    priority=sq.priority,
                )
                self.add_sq(prefixed)

            # Step 2: Connect SUPER_TRIGGER to app source
            source = graph.source
            if source:
                self.add_arc(Arc(
                    source="SUPER_TRIGGER",
                    target=f"{graph.app_id}__{source}",
                    data_name="trigger",
                ))

            # Step 3: Add prefixed internal arcs
            for arc in graph.arcs:
                self.add_arc(Arc(
                    source=f"{graph.app_id}__{arc.source}",
                    target=f"{graph.app_id}__{arc.target}",
                    data_name=arc.data_name,
                    estimated_data_size=arc.estimated_data_size,
                ))

            # Step 4: Connect app sink to BARRIER_JOIN
            sink = graph.sink
            if sink:
                self.add_arc(Arc(
                    source=f"{graph.app_id}__{sink}",
                    target="BARRIER_JOIN",
                    data_name="result",
                ))

    @staticmethod
    def get_app_for_sq(prefixed_name: str) -> str:
        if "__" in prefixed_name:
            return prefixed_name.split("__")[0]
        return "composed"

    @staticmethod
    def get_original_sq_name(prefixed_name: str) -> str:
        if "__" in prefixed_name:
            return prefixed_name.split("__", 1)[1]
        return prefixed_name

    def decompose_mapping(
        self, flat_mapping: Dict[str, str]
    ) -> Dict[str, Dict[str, str]]:
        """Convert {prefixed_sq: device} to {app_id: {sq: device}}."""
        result: Dict[str, Dict[str, str]] = {}
        for prefixed_sq, device in flat_mapping.items():
            app_id = self.get_app_for_sq(prefixed_sq)
            original = self.get_original_sq_name(prefixed_sq)
            if app_id not in result:
                result[app_id] = {}
            result[app_id][original] = device
        return result
