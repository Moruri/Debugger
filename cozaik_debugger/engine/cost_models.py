"""
Objective calculators for makespan and energy.

Implements the formulas from Cozaik paper Section 6.3 and 6.4:

    Makespan(M) = max over all SQs { finish_time(sq, M) }
    finish_time(sq, M) = start_time(sq, M) + T_exec(sq, M(sq))
    start_time(sq, M) = max(ready_time(sq, M), device_avail(M(sq)))

    Energy(M) = sum(E_exec) + sum(E_comm for cross-device arcs)
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple

from cozaik_debugger.models.graph import TTGraph
from cozaik_debugger.models.device import DeviceTopology
from cozaik_debugger.models.placement import Placement


class ScheduleResult:
    """Detailed scheduling result with per-SQ timing breakdown."""

    def __init__(self) -> None:
        self.start_time: Dict[str, float] = {}
        self.finish_time: Dict[str, float] = {}
        self.ready_time: Dict[str, float] = {}
        self.device_avail_at_start: Dict[str, float] = {}
        self.exec_time: Dict[str, float] = {}
        self.comm_delays: Dict[str, List[Tuple[str, float]]] = {}
        self.bottleneck_predecessor: Dict[str, Optional[str]] = {}
        self.makespan: float = 0.0
        self.critical_path: List[str] = []


class ObjectiveCalculator:
    """
    Calculates makespan and energy for a given placement.

    This is the core calculation used by QPF optimization (Algorithm 1 in the paper)
    and by the debugger's counterfactual analysis.
    """

    def __init__(self, graph: TTGraph, topology: DeviceTopology) -> None:
        self._graph = graph
        self._topology = topology

    def calculate_makespan(self, placement: Placement) -> ScheduleResult:
        """
        Compute makespan following topological order.

        For each SQ:
            ready_time = max over predecessors of (finish_time[pred] + comm_cost)
            start_time = max(ready_time, device_avail[assigned_device])
            finish_time = start_time + exec_time(sq, assigned_device)

        Returns detailed ScheduleResult for debugging.
        """
        result = ScheduleResult()
        device_avail: Dict[str, float] = {}
        topo_order = self._graph.topological_order()

        for sq_name in topo_order:
            sq = self._graph.sqs[sq_name]
            device = placement.get_device(sq_name)
            if device is None:
                device = "unknown"

            # Calculate execution time on assigned device
            exec_time = sq.get_exec_time(device)
            result.exec_time[sq_name] = exec_time

            # Calculate ready_time: max over all predecessors
            ready = 0.0
            bottleneck_pred = None
            bottleneck_time = 0.0
            comm_delays = []

            for pred_name in self._graph.predecessors(sq_name):
                pred_finish = result.finish_time.get(pred_name, 0.0)
                pred_device = placement.get_device(pred_name) or "unknown"

                if pred_device != device:
                    arc = self._graph.get_arc(pred_name, sq_name)
                    data_size = arc.estimated_data_size if arc else 1024
                    comm_time = self._topology.calculate_transfer_time(
                        pred_device, device, data_size
                    ) * 1000  # to ms
                    arrival = pred_finish + comm_time
                    comm_delays.append((pred_name, comm_time))
                else:
                    arrival = pred_finish
                    comm_delays.append((pred_name, 0.0))

                if arrival > ready:
                    ready = arrival
                    bottleneck_pred = pred_name
                    bottleneck_time = arrival

            result.ready_time[sq_name] = ready
            result.comm_delays[sq_name] = comm_delays
            result.bottleneck_predecessor[sq_name] = bottleneck_pred

            # Device availability (FIFO sequential on same device)
            dev_avail = device_avail.get(device, 0.0)
            result.device_avail_at_start[sq_name] = dev_avail

            start = max(ready, dev_avail)
            finish = start + exec_time

            result.start_time[sq_name] = start
            result.finish_time[sq_name] = finish

            device_avail[device] = finish

        # Makespan = max finish time
        if result.finish_time:
            result.makespan = max(result.finish_time.values())

        # Reconstruct critical path by walking back from latest-finishing SQ
        if topo_order:
            last_sq = max(topo_order, key=lambda n: result.finish_time.get(n, 0))
            path = []
            current: Optional[str] = last_sq
            while current is not None:
                path.append(current)
                current = result.bottleneck_predecessor.get(current)
            result.critical_path = list(reversed(path))

        return result

    def calculate_energy(self, placement: Placement) -> float:
        """
        Energy(M) = sum(E_exec(sq, M(sq))) + sum(E_comm for cross-device arcs)

        Returns total energy in joules.
        """
        total_energy = 0.0

        # Execution energy
        for sq_name, sq in self._graph.sqs.items():
            device_name = placement.get_device(sq_name)
            if device_name is None:
                continue
            total_energy += sq.get_energy_cost(device_name)

        # Communication energy (only for cross-device arcs)
        for arc in self._graph.arcs:
            src_device = placement.get_device(arc.source)
            dst_device = placement.get_device(arc.target)
            if src_device and dst_device and src_device != dst_device:
                total_energy += self._topology.calculate_transfer_energy(
                    src_device, dst_device, arc.estimated_data_size
                )

        return total_energy

    def calculate_device_energy(self, placement: Placement) -> Dict[str, float]:
        """Per-device energy breakdown."""
        device_energy: Dict[str, float] = {}

        for sq_name, sq in self._graph.sqs.items():
            device_name = placement.get_device(sq_name)
            if device_name is None:
                continue
            energy = sq.get_energy_cost(device_name)
            device_energy[device_name] = device_energy.get(device_name, 0.0) + energy

        for arc in self._graph.arcs:
            src_device = placement.get_device(arc.source)
            dst_device = placement.get_device(arc.target)
            if src_device and dst_device and src_device != dst_device:
                comm_energy = self._topology.calculate_transfer_energy(
                    src_device, dst_device, arc.estimated_data_size
                )
                # Split comm energy between sender and receiver
                device_energy[src_device] = (
                    device_energy.get(src_device, 0.0) + comm_energy / 2
                )
                device_energy[dst_device] = (
                    device_energy.get(dst_device, 0.0) + comm_energy / 2
                )

        return device_energy
