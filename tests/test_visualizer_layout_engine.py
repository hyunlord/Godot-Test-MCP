"""Unit tests for visualizer layout engine."""

from __future__ import annotations

from src.visualizer_layout_engine import VisualizerLayoutEngine


def test_layout_engine_builds_clusters_and_edges() -> None:
    engine = VisualizerLayoutEngine()
    nodes = [
        {"id": "file::a", "label": "a.gd", "kind": "file", "folder_category": "scripts"},
        {"id": "class::a", "label": "A", "kind": "class", "folder_category": "scripts"},
        {"id": "file::b", "label": "b.tres", "kind": "file", "folder_category": "resources"},
    ]
    edges = [
        {"source": "file::a", "target": "class::a", "edge_type": "contains", "confidence": 1.0},
        {"source": "class::a", "target": "file::b", "edge_type": "loads", "confidence": 0.8},
    ]

    payload = engine.build(nodes=nodes, edges=edges)

    assert len(payload["clusters"]) >= 2
    assert "file::a" in payload["node_positions"]
    assert "class::a" in payload["node_positions"]
    assert payload["viewport"]["width"] > 0
    assert payload["viewport"]["height"] > 0
    assert len(payload["edge_layouts"]) == 2
    first = payload["edge_layouts"][0]
    assert "points" in first
    assert "sx" in first["points"]
