"""Unit tests for visualizer performance policy."""

from __future__ import annotations

from src.visualizer_performance_policy import VisualizerPerformancePolicy


def test_policy_thresholds_are_monotonic() -> None:
    policy = VisualizerPerformancePolicy()
    assert policy.max_dom_nodes(0.3) < policy.max_dom_nodes(0.7)
    assert policy.max_dom_nodes(0.7) <= policy.max_dom_nodes(1.2)

    assert policy.edge_stride(0.3) > policy.edge_stride(0.7)
    assert policy.edge_stride(0.7) >= policy.edge_stride(1.2)


def test_spatial_index_and_visibility() -> None:
    policy = VisualizerPerformancePolicy()
    positions = {
        "n1": {"x": 10.0, "y": 10.0, "w": 100.0, "h": 70.0},
        "n2": {"x": 600.0, "y": 20.0, "w": 100.0, "h": 70.0},
    }
    index = policy.build_spatial_index(node_positions=positions, cell_size=256)
    assert len(index) >= 2

    visible = policy.visible_node_ids(node_positions=positions, viewport={"width": 800.0, "height": 600.0}, zoom=1.0)
    assert "n1" in visible
    assert "n2" in visible

    sampled = policy.sampled_edges(edges=[{"id": f"e{i}"} for i in range(20)], zoom=0.3)
    assert len(sampled) < 20
