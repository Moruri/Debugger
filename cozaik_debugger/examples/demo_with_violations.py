"""
Demo that deliberately creates deadline violations and energy hotspots
to showcase the full debugging pipeline.
"""

from cozaik_debugger.examples.etl_stats_scenario import build_scenario
from cozaik_debugger.engine.simulator import ExecutionSimulator
from cozaik_debugger.engine.criticality import CriticalityAnalyzer
from cozaik_debugger.trace.formats import AdaptationTrigger, AdaptationRecord
from cozaik_debugger.debugger.core import CozaikDebugger
from cozaik_debugger.visualization.terminal import TerminalVisualizer


def run():
    print("Building ETL + Stats scenario with tight deadlines...\n")
    graph, topology, placement, alternatives = build_scenario()

    # Set tight deadlines on sink nodes and key tasks to force violations
    for sq_name, sq in graph.sqs.items():
        if "sink" in sq_name or "BARRIER" in sq_name:
            sq.deadline_budget_us = 35_000  # 35ms - very tight
        if "bloom_filter" in sq_name:
            sq.deadline_budget_us = 15_000  # 15ms
            sq.has_planb = True

    # Give edge0 a tight energy budget
    topology.devices["edge0"].energy_budget = 0.03  # 30mJ

    # Run criticality
    CriticalityAnalyzer(graph).analyze()

    # Simulate with high noise to guarantee some violations
    print("Simulating with 25% noise to trigger violations...")
    simulator = ExecutionSimulator(
        graph=graph,
        topology=topology,
        placement=placement,
        noise_pct=0.25,
        seed=99,  # chosen to produce interesting violations
    )
    trace = simulator.simulate(num_iterations=2)

    # Inject adaptation events
    trace.adaptation_records.append(AdaptationRecord(
        timestamp_ms=20.0,
        trigger=AdaptationTrigger.DEVICE_FAILURE,
        trigger_device="mid0",
        validation_method="heartbeat_timeout",
        validation_duration_ms=4.0,
        decision="remap",
        affected_tasks=["etl__senml_parse", "etl__range_filter",
                       "stats__parse_project", "stats__bloom_filter_check",
                       "stats__second_order_moment"],
        remapping_details=[
            {"sq": "etl__senml_parse", "from_device": "mid0",
             "to_device": "pc0", "reason": "qpf_alternative_rank_1"},
            {"sq": "stats__bloom_filter_check", "from_device": "mid0",
             "to_device": "pc0", "reason": "qpf_alternative_rank_1"},
            {"sq": "stats__second_order_moment", "from_device": "mid0",
             "to_device": "edge0", "reason": "first_available"},
        ],
        selection_reason="QPF precomputed alternatives",
        deployment_strategy="qpf",
        adaptation_duration_ms=0.38,
        success=True,
        constraint_violations=0,
    ))

    trace.adaptation_records.append(AdaptationRecord(
        timestamp_ms=55.0,
        trigger=AdaptationTrigger.DEVICE_RECONNECTION,
        trigger_device="mid0",
        validation_method="stability_window",
        validation_duration_ms=120_000,
        decision="evaluate_migration",
        affected_tasks=["stats__second_order_moment"],
        remapping_details=[
            {"sq": "stats__second_order_moment", "from_device": "edge0",
             "to_device": "mid0", "reason": "migration_benefit_18pct"},
        ],
        selection_reason="Migration benefit 18% exceeds 10% threshold",
        deployment_strategy="qpf",
        adaptation_duration_ms=0.52,
        success=True,
    ))

    print(f"Trace: {len(trace.execution_records)} executions, "
          f"{len(trace.communication_records)} comms, "
          f"{len(trace.adaptation_records)} adaptations\n")

    # Run debugger
    debugger = CozaikDebugger(
        graph=graph,
        topology=topology,
        placement=placement,
        trace=trace,
        alternatives=alternatives,
    )
    report = debugger.run_full_analysis(iteration=0)

    # Render
    viz = TerminalVisualizer(width=90)
    print(viz.render_full_report(report))
    print("\n" + report.executive_summary)

    # Show detailed root-cause for first violation
    if report.root_cause_reports:
        print("\n\n=== DETAILED ROOT-CAUSE (first violation) ===")
        rc = report.root_cause_reports[0]
        print(rc.summary)
        if rc.causal_chain:
            print("\nFull causal chain:")
            for i, link in enumerate(rc.causal_chain, 1):
                print(f"  {i}. [{link.delay_source.value}] {link.explanation}")

    # Show counterfactual detail
    if report.counterfactual_reports:
        print("\n\n=== COUNTERFACTUAL DETAIL (first violation) ===")
        cf = report.counterfactual_reports[0]
        print(cf.summary)

    return report


if __name__ == "__main__":
    run()
