"""
ETL + Stats multi-application scenario from the Cozaik paper (Section 5).

ETL pipeline: spout -> parse -> range_filter -> bloom_filter ->
              interpolation -> join_bolt -> annotation -> csv_to_senml ->
              mqtt_publish -> etl_sink

Stats pipeline: spout -> parse_project -> bloom_filter_check ->
               {kalman_filter, second_order_moment, distinct_approx_count} ->
               mqtt_publish_stats -> stats_sink

Devices: edge0 (RPi4), mid0 (Jetson Nano), pc0 (NUC i5), cloud0 (Server)
"""

from cozaik_debugger.models.sq import SQ, Arc, Criticality
from cozaik_debugger.models.graph import TTGraph, ComposedGraph
from cozaik_debugger.models.device import DeviceProfile, NetworkLink, DeviceTopology
from cozaik_debugger.models.placement import Placement, PlacementAlternatives, PlacementAlternative


def build_topology() -> DeviceTopology:
    topo = DeviceTopology()

    topo.add_device(DeviceProfile(
        name="edge0", device_type="rpi4", cpu_speed=1.0, memory=4_000_000_000,
        cores=4, power_idle=2.0, power_active=5.0,
        power_transmit=0.5, power_receive=0.3,
        energy_budget=50.0, components=["sensor", "edge"],
    ))
    topo.add_device(DeviceProfile(
        name="mid0", device_type="jetson_nano", cpu_speed=1.2, memory=4_000_000_000,
        cores=4, power_idle=3.0, power_active=10.0,
        power_transmit=0.8, power_receive=0.5,
        components=["compute", "gpu", "edge"],
    ))
    topo.add_device(DeviceProfile(
        name="pc0", device_type="nuc_i5", cpu_speed=2.0, memory=16_000_000_000,
        cores=8, power_idle=8.0, power_active=30.0,
        power_transmit=1.0, power_receive=0.8,
        components=["compute", "storage"],
    ))
    topo.add_device(DeviceProfile(
        name="cloud0", device_type="server", cpu_speed=3.0, memory=64_000_000_000,
        cores=32, power_idle=50.0, power_active=100.0,
        power_transmit=2.0, power_receive=1.5,
        components=["compute", "storage", "mqtt"],
    ))

    topo.add_link(NetworkLink("edge0", "mid0", latency=0.001, bandwidth=125_000_000))
    topo.add_link(NetworkLink("edge0", "pc0", latency=0.005, bandwidth=50_000_000))
    topo.add_link(NetworkLink("mid0", "pc0", latency=0.001, bandwidth=125_000_000))
    topo.add_link(NetworkLink("edge0", "cloud0", latency=0.020, bandwidth=12_500_000))
    topo.add_link(NetworkLink("mid0", "cloud0", latency=0.020, bandwidth=12_500_000))
    topo.add_link(NetworkLink("pc0", "cloud0", latency=0.001, bandwidth=125_000_000))

    return topo


def build_etl_graph() -> TTGraph:
    g = TTGraph(app_id="etl")

    tasks = [
        ("senml_spout",      5.0,  Criticality.ESSENTIAL),
        ("senml_parse",      8.0,  Criticality.IMPORTANT),
        ("range_filter",     7.0,  Criticality.NORMAL),
        ("bloom_filter",    12.0,  Criticality.IMPORTANT),
        ("interpolation",   10.0,  Criticality.NORMAL),
        ("join_bolt",        6.0,  Criticality.NORMAL),
        ("annotation",       4.0,  Criticality.NORMAL),
        ("csv_to_senml",     5.0,  Criticality.NORMAL),
        ("mqtt_publish",     8.0,  Criticality.NORMAL),
        ("etl_sink",         3.0,  Criticality.NORMAL),
    ]

    for name, complexity, crit in tasks:
        sq = SQ(
            name=name, complexity=complexity, criticality=crit,
            execution_time_estimates={
                "edge0": complexity / 1.0,
                "mid0": complexity / 1.2,
                "pc0": complexity / 2.0,
                "cloud0": complexity / 3.0,
                "default": complexity,
            },
            energy_cost_estimates={
                "edge0": 5.0 * (complexity / 1.0) / 1000,
                "mid0": 10.0 * (complexity / 1.2) / 1000,
                "pc0": 30.0 * (complexity / 2.0) / 1000,
                "cloud0": 100.0 * (complexity / 3.0) / 1000,
            },
        )
        g.add_sq(sq)

    # Linear pipeline
    chain = [
        "senml_spout", "senml_parse", "range_filter", "bloom_filter",
        "interpolation", "join_bolt", "annotation", "csv_to_senml",
        "mqtt_publish", "etl_sink",
    ]
    for i in range(len(chain) - 1):
        g.add_arc(Arc(source=chain[i], target=chain[i + 1],
                       data_name=f"{chain[i]}_out", estimated_data_size=2048))

    return g


def build_stats_graph() -> TTGraph:
    g = TTGraph(app_id="stats")

    tasks = [
        ("stats_spout",          5.0,  Criticality.ESSENTIAL),
        ("parse_project",        6.0,  Criticality.IMPORTANT),
        ("bloom_filter_check",  10.0,  Criticality.IMPORTANT),
        ("kalman_filter",       15.0,  Criticality.ESSENTIAL),
        ("second_order_moment",  8.0,  Criticality.NORMAL),
        ("distinct_approx_count", 9.0, Criticality.NORMAL),
        ("mqtt_publish_stats",   7.0,  Criticality.NORMAL),
        ("stats_sink",           3.0,  Criticality.NORMAL),
    ]

    for name, complexity, crit in tasks:
        sq = SQ(
            name=name, complexity=complexity, criticality=crit,
            execution_time_estimates={
                "edge0": complexity / 1.0,
                "mid0": complexity / 1.2,
                "pc0": complexity / 2.0,
                "cloud0": complexity / 3.0,
                "default": complexity,
            },
            energy_cost_estimates={
                "edge0": 5.0 * (complexity / 1.0) / 1000,
                "mid0": 10.0 * (complexity / 1.2) / 1000,
                "pc0": 30.0 * (complexity / 2.0) / 1000,
                "cloud0": 100.0 * (complexity / 3.0) / 1000,
            },
        )
        g.add_sq(sq)

    # Linear portion
    g.add_arc(Arc("stats_spout", "parse_project", "raw", 2048))
    g.add_arc(Arc("parse_project", "bloom_filter_check", "parsed", 1024))

    # Fan-out: bloom_filter_check -> three parallel branches
    g.add_arc(Arc("bloom_filter_check", "kalman_filter", "checked", 1024))
    g.add_arc(Arc("bloom_filter_check", "second_order_moment", "checked", 1024))
    g.add_arc(Arc("bloom_filter_check", "distinct_approx_count", "checked", 1024))

    # Fan-in: three branches -> mqtt_publish_stats
    g.add_arc(Arc("kalman_filter", "mqtt_publish_stats", "kf_out", 512))
    g.add_arc(Arc("second_order_moment", "mqtt_publish_stats", "som_out", 512))
    g.add_arc(Arc("distinct_approx_count", "mqtt_publish_stats", "dac_out", 512))

    g.add_arc(Arc("mqtt_publish_stats", "stats_sink", "published", 256))

    return g


def build_qpf_placement() -> Placement:
    """QPF-optimized placement for the composed ETL+Stats graph."""
    return Placement(
        mapping={
            # ETL tasks
            "etl__senml_spout": "edge0",
            "etl__senml_parse": "mid0",
            "etl__range_filter": "mid0",
            "etl__bloom_filter": "pc0",
            "etl__interpolation": "pc0",
            "etl__join_bolt": "pc0",
            "etl__annotation": "cloud0",
            "etl__csv_to_senml": "cloud0",
            "etl__mqtt_publish": "cloud0",
            "etl__etl_sink": "cloud0",
            # Stats tasks
            "stats__stats_spout": "edge0",
            "stats__parse_project": "mid0",
            "stats__bloom_filter_check": "mid0",
            "stats__kalman_filter": "pc0",
            "stats__second_order_moment": "mid0",
            "stats__distinct_approx_count": "pc0",
            "stats__mqtt_publish_stats": "cloud0",
            "stats__stats_sink": "cloud0",
            # Synthetic nodes
            "SUPER_TRIGGER": "edge0",
            "BARRIER_JOIN": "cloud0",
        },
        strategy="qpf",
        objective="makespan",
    )


def build_alternatives() -> PlacementAlternatives:
    """Precomputed QPF alternatives for key tasks."""
    alts = PlacementAlternatives()
    alts.alternatives["etl__bloom_filter"] = [
        PlacementAlternative("pc0", 6.0, 0.09, 1),
        PlacementAlternative("cloud0", 4.0, 0.13, 2),
        PlacementAlternative("mid0", 10.0, 0.08, 3),
    ]
    alts.alternatives["stats__kalman_filter"] = [
        PlacementAlternative("pc0", 7.5, 0.11, 1),
        PlacementAlternative("cloud0", 5.0, 0.17, 2),
        PlacementAlternative("mid0", 12.5, 0.10, 3),
    ]
    return alts


def build_scenario():
    """Build the complete ETL+Stats scenario."""
    topology = build_topology()
    etl = build_etl_graph()
    stats = build_stats_graph()

    composed = ComposedGraph()
    composed.compose([etl, stats])

    placement = build_qpf_placement()
    alternatives = build_alternatives()

    return composed, topology, placement, alternatives
