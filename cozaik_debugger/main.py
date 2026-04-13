"""
Cozaik Debugger - Main entry point and demo runner.

Demonstrates the full debugging pipeline:
1. Build a compiled graph (ETL + Stats multi-application)
2. Simulate execution with noise (deadline misses, energy variation)
3. Inject an adaptation event (device failure)
4. Run full analysis
5. Render results to terminal
"""

from cozaik_debugger.examples.etl_stats_scenario import build_scenario
from cozaik_debugger.engine.simulator import ExecutionSimulator
from cozaik_debugger.engine.criticality import CriticalityAnalyzer
from cozaik_debugger.trace.formats import AdaptationTrigger
from cozaik_debugger.debugger.core import CozaikDebugger
from cozaik_debugger.visualization.terminal import TerminalVisualizer


def run_demo():
    print("Building ETL + Stats multi-application scenario...")
    graph, topology, placement, alternatives = build_scenario()

    # Run automatic criticality analysis
    analyzer = CriticalityAnalyzer(graph)
    criticalities = analyzer.analyze()
    print(f"Criticality analysis: {len(criticalities)} SQs classified")

    # Simulate execution with 15% noise (will cause some deadline misses)
    print("Simulating execution (3 iterations, 15% noise)...")
    simulator = ExecutionSimulator(
        graph=graph,
        topology=topology,
        placement=placement,
        noise_pct=0.15,
        seed=42,
    )
    trace = simulator.simulate(
        num_iterations=3,
        global_deadline_ms=45.0,  # tight deadline to trigger violations
    )

    # Inject a device failure adaptation event
    from cozaik_debugger.trace.recorder import TraceRecorder
    trace.adaptation_records.append(
        __import__("cozaik_debugger.trace.formats", fromlist=["AdaptationRecord"]).AdaptationRecord(
            timestamp_ms=25.0,
            trigger=AdaptationTrigger.DEVICE_FAILURE,
            trigger_device="mid0",
            validation_method="heartbeat_timeout",
            validation_duration_ms=5.0,
            decision="remap",
            affected_tasks=["etl__senml_parse", "etl__range_filter",
                          "stats__parse_project", "stats__bloom_filter_check"],
            remapping_details=[
                {"sq": "etl__senml_parse", "from_device": "mid0",
                 "to_device": "pc0", "reason": "qpf_alternative_rank_1"},
                {"sq": "stats__parse_project", "from_device": "mid0",
                 "to_device": "pc0", "reason": "qpf_alternative_rank_1"},
            ],
            selection_reason="QPF precomputed alternative, rank 1",
            deployment_strategy="qpf",
            adaptation_duration_ms=0.45,
            success=True,
        )
    )

    # Also add a false positive event
    trace.adaptation_records.append(
        __import__("cozaik_debugger.trace.formats", fromlist=["AdaptationRecord"]).AdaptationRecord(
            timestamp_ms=60.0,
            trigger=AdaptationTrigger.FALSE_POSITIVE,
            trigger_device="edge0",
            validation_method="grace_period",
            validation_duration_ms=12.0,
            false_positive=True,
            decision="no_op",
            adaptation_duration_ms=12.0,
            success=True,
        )
    )

    print(f"Trace collected: {len(trace.execution_records)} execution records, "
          f"{len(trace.communication_records)} communication records, "
          f"{len(trace.adaptation_records)} adaptation events")

    # Run the debugger
    print("\nRunning full analysis...\n")
    debugger = CozaikDebugger(
        graph=graph,
        topology=topology,
        placement=placement,
        trace=trace,
        alternatives=alternatives,
    )
    report = debugger.run_full_analysis(iteration=0)

    # Render to terminal
    viz = TerminalVisualizer(width=90)
    output = viz.render_full_report(report)
    print(output)

    # Also print the executive summary
    print("\n" + report.executive_summary)

    # Export trace for offline analysis
    from cozaik_debugger.trace.recorder import TraceRecorder
    recorder = TraceRecorder(topology, placement, graph.sqs)
    recorder._trace = trace
    recorder.export_json("debug_trace.json")
    print("\nTrace exported to debug_trace.json")

    return report


def main():
    """Entry point."""
    import sys
    if "--no-color" in sys.argv:
        run_demo()
    else:
        run_demo()


if __name__ == "__main__":
    main()
