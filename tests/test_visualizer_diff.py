"""Unit tests for visualizer diff engine."""

from __future__ import annotations

from src.visualizer_diff import VisualizerDiffEngine


def test_diff_engine_detects_changes() -> None:
    engine = VisualizerDiffEngine()
    diff = engine.build_diff(
        run_id="new",
        baseline_run_id="old",
        current_map={
            "nodes": [{"id": "n1"}, {"id": "n2"}],
            "edges": [{"source": "n1", "target": "n2", "edge_type": "contains"}],
        },
        baseline_map={
            "nodes": [{"id": "n1"}],
            "edges": [],
        },
        current_timeline={"events": [{"type": "spawn", "tick": 10}]},
        baseline_timeline={"events": [{"type": "spawn", "tick": 5}, {"type": "death", "tick": 12}]},
    )

    assert diff["summary"]["added_node_count"] == 1
    assert diff["summary"]["added_edge_count"] == 1
    assert "spawn" in diff["runtime"]["event_distribution_delta"]
