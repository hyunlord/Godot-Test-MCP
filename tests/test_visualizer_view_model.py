"""Unit tests for visualizer view model builder."""

from __future__ import annotations

import json
from pathlib import Path

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
            {
                "id": "func::a::tick@10",
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
            {
                "source": "file::a",
                "target": "class::a",
                "edge_type": "contains",
                "confidence": 1.0,
                "inferred": False,
                "metadata": {},
            },
            {
                "source": "class::a",
                "target": "func::a::tick@10",
                "edge_type": "contains",
                "confidence": 1.0,
                "inferred": False,
                "metadata": {},
            },
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
    assert vm["stats"]["node_count"] == 3
    assert vm["stats"]["edge_count"] == 2
    assert vm["stats"]["cluster_count"] >= 1
    assert "class::a" in vm["nodesById"]
    assert vm["nodesById"]["class::a"]["diff_state"] == "added"
    assert "file::a" in vm["adjacency"]["out"]
    assert vm["filters"]["languages"] == ["gdscript"]
    assert vm["ui_defaults"]["default_layer"] == "cluster"
    assert "cluster_layout_health" in vm
    assert vm["cluster_layout_health"]["overlap_count"] == 0
    assert vm["cluster_layout_health"]["duplicate_anchor_count"] == 0
    assert "board_model" in vm
    assert "clusters" in vm["board_model"]
    assert "links" in vm["board_model"]
    assert "hotspots" in vm["board_model"]
    assert vm["board_model"]["clusters"][0]["cards"]
    first_card = vm["board_model"]["clusters"][0]["cards"][0]
    assert first_card["kind"] in {"file", "class"}
    assert int(first_card["stats"]["functions"]) >= 1
    assert "layers" in vm
    assert "cluster" in vm["layers"]
    assert "structural" in vm["layers"]
    assert "detail" in vm["layers"]
    assert "board_model_v2" in vm
    assert "lanes" in vm["board_model_v2"]
    assert "links" in vm["board_model_v2"]
    assert "legend" in vm["board_model_v2"]
    assert vm["classification"]["lane_strategy"] == "hybrid"
    assert vm["ui_defaults"]["detail_requires_anchor"] is True
    assert vm["ui_defaults"]["structural_autoselect"] == "top_file_card"
    assert int(vm["ui_defaults"]["cluster_preview_card_limit"]) == 4
    assert vm["ui_defaults"]["structural_show_all_on_more"] is True
    lane_summary = vm["board_model_v2"]["lanes"][0]["summary"]
    assert int(lane_summary["total_card_count"]) >= int(lane_summary["preview_card_count"])


def test_view_model_builder_v2_replaces_anonymous_with_filename_and_emits_link_evidence() -> None:
    builder = VisualizerViewModelBuilder()
    map_payload = {
        "project_path": "/tmp/project",
        "nodes": [
            {
                "id": "class::res://core/save_manager.gd::anonymous",
                "kind": "class",
                "label": "(anonymous)",
                "path": "res://core/save_manager.gd",
                "language": "gdscript",
                "folder_category": "core",
                "loc": 20,
                "metadata": {},
            },
            {
                "id": "file::res://ui/hud_panel.gd",
                "kind": "file",
                "label": "hud_panel.gd",
                "path": "res://ui/hud_panel.gd",
                "language": "gdscript",
                "folder_category": "ui",
                "loc": 30,
                "metadata": {},
            },
        ],
        "edges": [
            {
                "source": "class::res://core/save_manager.gd::anonymous",
                "target": "file::res://ui/hud_panel.gd",
                "edge_type": "contains",
                "confidence": 1.0,
                "inferred": False,
                "metadata": {},
            }
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

    lanes = vm["board_model_v2"]["lanes"]
    all_titles = [card["title"] for lane in lanes for card in lane.get("cards", [])]
    assert "(anonymous)" not in all_titles
    assert "save_manager.gd" in all_titles

    links = vm["board_model_v2"]["links"]
    assert len(links) >= 1
    first_link = links[0]
    assert "type_breakdown" in first_link
    assert "evidence_refs" in first_link
    assert isinstance(first_link["evidence_refs"], list)


def test_view_model_builder_v2_applies_domain_override_rules(tmp_path: Path) -> None:
    project = tmp_path / "game"
    rules_dir = project / ".godot-test-mcp"
    rules_dir.mkdir(parents=True)
    (rules_dir / "visualizer_domains.json").write_text(
        json.dumps(
            {
                "rules": [
                    {"path": "res://scripts/systems", "lane": "systems"},
                    {"filename": "ui_hud.gd", "lane": "ui"},
                ],
                "aliases": {"systems": "Systems", "ui": "UI"},
            }
        ),
        encoding="utf-8",
    )

    builder = VisualizerViewModelBuilder()
    map_payload = {
        "project_path": str(project),
        "nodes": [
            {
                "id": "file::res://scripts/systems/chronicle_system.gd",
                "kind": "file",
                "label": "chronicle_system.gd",
                "path": "res://scripts/systems/chronicle_system.gd",
                "language": "gdscript",
                "folder_category": "systems",
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
        default_layer="cluster",
        focus_cluster="",
    )

    lanes = vm["board_model_v2"]["lanes"]
    assert len(lanes) == 1
    assert lanes[0]["key"] == "systems"
    assert lanes[0]["title"] == "Systems"
    signals = vm["classification"]["source_signals"]["systems"]
    assert any(str(item).startswith("override:") for item in signals)
