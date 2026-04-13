"""
Execution simulator for the debugger.

Simulates execution of a compiled graph on a device topology with a given
placement. Produces a DeploymentTrace that can be analyzed by the debugger.

Used for:
- Testing the debugger with synthetic data
- Counterfactual analysis ("what if we used this placement?")
- Offline replay with perturbed parameters
"""

from __future__ import annotations
import random
from typing import Dict, Optional

from cozaik_debugger.models.graph import TTGraph
from cozaik_debugger.models.device import DeviceTopology
from cozaik_debugger.models.placement import Placement
from cozaik_debugger.engine.cost_models import ObjectiveCalculator
from cozaik_debugger.trace.formats import DeploymentTrace
from cozaik_debugger.trace.recorder import TraceRecorder


class ExecutionSimulator:
    """
    Simulates execution of a Cozaik application and produces traces.

    Adds configurable noise to execution times and communication delays
    to model real-world variability.
    """

    def __init__(
        self,
        graph: TTGraph,
        topology: DeviceTopology,
        placement: Placement,
        noise_pct: float = 0.1,
        seed: Optional[int] = None,
    ) -> None:
        self._graph = graph
        self._topology = topology
        self._placement = placement
        self._noise_pct = noise_pct
        self._rng = random.Random(seed)
        self._calc = ObjectiveCalculator(graph, topology)

    def simulate(
        self,
        num_iterations: int = 1,
        global_deadline_ms: Optional[float] = None,
    ) -> DeploymentTrace:
        """
        Run the simulation and return a trace.

        For each iteration, walks the DAG in topological order,
        computes actual times with noise, and records everything.
        """
        recorder = TraceRecorder(
            self._topology, self._placement, self._graph.sqs
        )
        recorder.start_deployment(f"sim_{self._rng.randint(1000, 9999)}")

        for iteration in range(num_iterations):
            self._simulate_iteration(recorder, iteration, global_deadline_ms)

        return recorder.finish_deployment()

    def _simulate_iteration(
        self,
        recorder: TraceRecorder,
        iteration: int,
        global_deadline_ms: Optional[float],
    ) -> None:
        topo = self._graph.topological_order()
        finish_time: Dict[str, float] = {}
        device_avail: Dict[str, float] = {}
        iteration_start = 0.0

        for sq_name in topo:
            sq = self._graph.sqs[sq_name]
            device = self._placement.get_device(sq_name) or "unknown"

            # Estimated execution time
            est_time = sq.get_exec_time(device)
            # Add noise: actual = estimated * (1 + uniform(-noise, +noise))
            noise = self._rng.uniform(-self._noise_pct, self._noise_pct)
            actual_time = est_time * (1 + noise)
            actual_time = max(actual_time, 0.01)

            # Ready time: max over predecessors
            ready = 0.0
            for pred in self._graph.predecessors(sq_name):
                pred_finish = finish_time.get(pred, 0.0)
                pred_device = self._placement.get_device(pred) or "unknown"

                if pred_device != device:
                    arc = self._graph.get_arc(pred, sq_name)
                    data_size = arc.estimated_data_size if arc else 1024
                    comm_time = self._topology.calculate_transfer_time(
                        pred_device, device, data_size
                    ) * 1000
                    # Add noise to communication
                    comm_noise = self._rng.uniform(0, self._noise_pct * 2)
                    comm_time *= (1 + comm_noise)
                    arrival = pred_finish + comm_time

                    recorder.record_communication(
                        source_sq=pred,
                        target_sq=sq_name,
                        source_device=pred_device,
                        target_device=device,
                        data_size=data_size,
                        send_time_ms=pred_finish,
                        receive_time_ms=arrival,
                        iteration=iteration,
                    )
                else:
                    arrival = pred_finish

                ready = max(ready, arrival)

            dev_avail = device_avail.get(device, 0.0)
            start = max(ready, dev_avail)
            end = start + actual_time

            # Find concurrent SQs on same device
            concurrent = []
            for other_sq, other_finish in finish_time.items():
                other_device = self._placement.get_device(other_sq)
                if other_device == device:
                    other_start = other_finish - (
                        self._graph.sqs[other_sq].get_exec_time(device)
                    )
                    if other_start < end and other_finish > start:
                        concurrent.append(other_sq)

            # Determine deadline for this SQ
            deadline = None
            if sq.deadline_budget_us is not None:
                deadline = sq.deadline_budget_us / 1000.0
            elif global_deadline_ms is not None and not self._graph.successors(sq_name):
                # Apply global deadline to sink nodes
                deadline = global_deadline_ms

            # Compute actual energy with noise
            est_energy = sq.get_energy_cost(device)
            actual_energy = est_energy * (1 + noise)

            recorder.record_sq_execution(
                sq_name=sq_name,
                device=device,
                iteration=iteration,
                start_time_ms=start,
                end_time_ms=end,
                actual_energy=actual_energy,
                deadline_ms=deadline,
                planb_triggered=False,
                concurrent_sqs=concurrent,
            )

            finish_time[sq_name] = end
            device_avail[device] = end
