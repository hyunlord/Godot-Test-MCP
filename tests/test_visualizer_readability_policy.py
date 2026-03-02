"""Tests for overview-first readability policy in visualizer view model."""

from __future__ import annotations

from src.visualizer_view_model import VisualizerViewModelBuilder


def test_structural_layer_hides_function_nodes_and_calls_edges() -> None:
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
                "loc": 10,
                "metadata": {},
            },
            {
                "id": "class::a",
                "kind": "class",
                "label": "A",
                "path": "res://scripts/a.gd",
                "language": "gdscript",
                "folder_category": "scripts",
                "loc": 10,
                "metadata": {},
            },
            {
                "id": "func::a",
                "kind": "function",
                "label": "tick",
                "path": "res://scripts/a.gd",
                "language": "gdscript",
                "folder_category": "scripts",
                "loc": 1,
                "metadata": {},
            },
        ],
        "edges": [
            {"source": "file::a", "target": "class::a", "edge_type": "contains", "confidence": 1.0},
            {"source": "class::a", "target": "func::a", "edge_type": "contains", "confidence": 1.0},
            {"source": "func::a", "target": "func::a", "edge_type": "calls", "confidence": 0.6, "inferred": True},
        ],
    }
    vm = builder.build(
        map_payload=map_payload,
        timeline_payload={"events": [], "event_count": 0},
        causality_payload={"links": []},
        diff_payload={"summary": {}},
        default_layer="cluster",
        focus_cluster="",
    )

    structural = vm["layers"]["structural"]
    structural_node_ids = set(structural["node_ids"])
    structural_edge_ids = set(structural["edge_ids"])

    assert "func::a" not in structural_node_ids
    assert all(vm["edgesById"][edge_id]["edge_type"] != "calls" for edge_id in structural_edge_ids)
    assert vm["ui_defaults"]["hidden_edge_types"] == ["calls"]


def test_default_layer_and_focus_cluster_are_stored() -> None:
    builder = VisualizerViewModelBuilder()
    map_payload = {
        "nodes": [
            {
                "id": "file::a",
                "kind": "file",
                "label": "a.gd",
                "path": "res://core/a.gd",
                "language": "gdscript",
                "folder_category": "core",
                "loc": 10,
                "metadata": {},
            }
        ],
        "edges": [],
    }
    vm = builder.build(
        map_payload=map_payload,
        timeline_payload={"events": [], "event_count": 0},
        causality_payload={"links": []},
        diff_payload={"summary": {}},
        default_layer="detail",
        focus_cluster="core",
    )
    assert vm["ui_defaults"]["default_layer"] == "detail"
    assert vm["ui_defaults"]["focus_cluster"] == "core"
