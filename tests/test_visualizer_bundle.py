"""Unit tests for visualizer graph bundle generation."""

from __future__ import annotations

from src.visualizer_bundle import VisualizerBundleBuilder


def test_bundle_builder_splits_calls_and_builds_cluster_aggregate() -> None:
    builder = VisualizerBundleBuilder()
    map_payload = {
        "run_id": "run-1",
        "project_path": "/tmp/project",
        "runtime_source": "fallback",
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
            },
            {
                "id": "file::b",
                "kind": "file",
                "label": "b.gd",
                "path": "res://ui/b.gd",
                "language": "gdscript",
                "folder_category": "ui",
                "loc": 20,
                "metadata": {},
            },
        ],
        "edges": [
            {"source": "file::a", "target": "file::b", "edge_type": "imports", "confidence": 0.8},
            {"source": "file::a", "target": "file::b", "edge_type": "calls", "confidence": 0.7},
        ],
        "summary": {},
    }
    view_model = {
        "nodesById": {
            "file::a": {"layout": {"x": 10.0, "y": 20.0, "cluster_id": "cluster::core"}, "metrics": {"in_degree": 0, "out_degree": 2}},
            "file::b": {"layout": {"x": 40.0, "y": 60.0, "cluster_id": "cluster::ui"}, "metrics": {"in_degree": 2, "out_degree": 0}},
        },
        "clusters": [
            {"id": "cluster::core", "key": "core", "title": "Core"},
            {"id": "cluster::ui", "key": "ui", "title": "UI"},
        ],
        "layers": {
            "cluster": {
                "node_ids": ["cluster::core", "cluster::ui"],
                "edge_ids": ["cluster_edge::0"],
                "nodesById": {},
                "edgesById": {
                    "cluster_edge::0": {
                        "id": "cluster_edge::0",
                        "source": "cluster::core",
                        "target": "cluster::ui",
                        "metadata": {"count": 2, "edge_types": {"imports": 1, "calls": 1}},
                    }
                },
            },
            "structural": {"node_ids": ["file::a", "file::b"], "edge_ids": [], "nodesById": {}, "edgesById": {}},
            "detail": {"node_ids": ["file::a", "file::b"], "edge_ids": [], "nodesById": {}, "edgesById": {}},
        },
        "cluster_metrics": [
            {"key": "core", "node_count": 1, "edge_count": 2, "hotspot_score": 1.0},
            {"key": "ui", "node_count": 1, "edge_count": 2, "hotspot_score": 1.0},
        ],
        "ui_defaults": {"default_layer": "cluster"},
    }

    bundle = builder.build(
        map_payload=map_payload,
        view_model=view_model,
        timeline_payload={"events": []},
        causality_payload={"links": []},
        diff_payload={"summary": {}},
        meta_payload={"run_id": "run-1"},
    )

    assert bundle["schema_version"] == "1.0"
    assert len(bundle["edges"]) == 1
    assert len(bundle["calls_edges"]) == 1
    assert len(bundle["clusters"]) == 2
    assert len(bundle["cluster_edges"]) == 1
    assert bundle["search_index"]["items"][0]["node_id"] == "file::a"
