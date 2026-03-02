"""Unit tests for visualizer view model builder."""

from __future__ import annotations

from src.visualizer_view_model import VisualizerViewModelBuilder


def test_view_model_builder_generates_stats_and_adjacency() -> None:
    builder = VisualizerViewModelBuilder()

    map_payload = {
        "nodes": [
            {
                "id": "file::a",
                "kind": "file",
                "label": "a.gd",
                "path": "res://scripts/a.gd",
                "language": "gdscript",
                "folder_category": "scripts",
                "loc": 20,
                "metadata": {},
            },
            {
                "id": "class::a",
                "kind": "class",
                "label": "A",
                "path": "res://scripts/a.gd",
                "language": "gdscript",
                "folder_category": "scripts",
                "loc": 20,
                "metadata": {},
            },
        ],
        "edges": [
            {
                "source": "file::a",
                "target": "class::a",
                "edge_type": "contains",
                "confidence": 1.0,
                "inferred": False,
                "metadata": {},
            }
        ],
    }

    diff_payload = {
        "added_nodes": ["class::a"],
        "removed_nodes": [],
        "added_edges": ["file::a->class::a:contains"],
        "removed_edges": [],
        "summary": {"added_node_count": 1},
    }

    vm = builder.build(
        map_payload=map_payload,
        timeline_payload={"events": [], "event_count": 0},
        causality_payload={"links": []},
        diff_payload=diff_payload,
        default_layer="cluster",
        focus_cluster="",
    )

    assert vm["version"] == 2
    assert vm["stats"]["node_count"] == 2
    assert vm["stats"]["edge_count"] == 1
    assert vm["stats"]["cluster_count"] >= 1
    assert "class::a" in vm["nodesById"]
    assert vm["nodesById"]["class::a"]["diff_state"] == "added"
    assert "file::a" in vm["adjacency"]["out"]
    assert vm["filters"]["languages"] == ["gdscript"]
    assert vm["ui_defaults"]["default_layer"] == "cluster"
    assert "cluster_layout_health" in vm
    assert vm["cluster_layout_health"]["overlap_count"] == 0
    assert vm["cluster_layout_health"]["duplicate_anchor_count"] == 0
    assert "layers" in vm
    assert "cluster" in vm["layers"]
    assert "structural" in vm["layers"]
    assert "detail" in vm["layers"]
