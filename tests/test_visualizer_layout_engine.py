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


def test_layout_engine_normalizes_cluster_origin_and_keeps_relative_node_spacing() -> None:
    engine = VisualizerLayoutEngine()
    nodes = [
        {"id": "func::1", "label": "f1", "kind": "function", "folder_category": "ai"},
        {"id": "func::2", "label": "f2", "kind": "function", "folder_category": "ai"},
    ]

    payload = engine.build(nodes=nodes, edges=[])

    clusters = payload["clusters"]
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["y"] == 40.0

    positions = payload["node_positions"]
    dx = positions["func::2"]["x"] - positions["func::1"]["x"]
    assert dx > 0
    assert positions["func::1"]["y"] == positions["func::2"]["y"]


def test_layout_engine_avoids_duplicate_cluster_anchors_after_wrap() -> None:
    engine = VisualizerLayoutEngine()
    nodes = []
    for index in range(20):
        category = f"cat_{index:02d}"
        nodes.append({"id": f"file::{index}:a", "label": f"{category}_a.gd", "kind": "file", "folder_category": category})
        nodes.append({"id": f"file::{index}:b", "label": f"{category}_b.gd", "kind": "file", "folder_category": category})

    payload = engine.build(nodes=nodes, edges=[])
    clusters = payload["clusters"]
    anchors = {(float(cluster["x"]), float(cluster["y"])) for cluster in clusters}

    assert len(clusters) == len(anchors)
    assert max(float(cluster["y"]) for cluster in clusters) > 40.0
