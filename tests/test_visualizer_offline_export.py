"""Unit tests for renderer offline export artifacts."""

from __future__ import annotations

import json

from src.visualizer_renderer import VisualizerRenderer


def test_renderer_writes_view_model_and_offline(tmp_path) -> None:
    renderer = VisualizerRenderer()

    artifacts = renderer.write_bundle(
        project_path=str(tmp_path),
        run_id="run-1",
        map_payload={
            "nodes": [
                {
                    "id": "file::a",
                    "kind": "file",
                    "label": "a.gd",
                    "path": "res://scripts/a.gd",
                    "language": "gdscript",
                    "folder_category": "scripts",
                    "loc": 12,
                    "metadata": {},
                }
            ],
            "edges": [],
            "summary": {},
        },
        timeline_payload={"events": [], "event_count": 0},
        causality_payload={"links": []},
        diff_payload={"summary": {}},
        meta_payload={
            "run_id": "run-1",
            "runtime_source": "fallback",
            "locale": "ko",
            "scenario": "test",
            "runtime_diagnostics": [{"level": "error", "code": "script_parse_error", "message": "x"}],
        },
        locale="ko",
    )

    view_model_path = tmp_path / ".godot-test-mcp" / "runs" / "run-1" / "visualizer" / "view_model.json"
    offline_path = tmp_path / ".godot-test-mcp" / "runs" / "run-1" / "visualizer" / "offline.html"
    index_path = tmp_path / ".godot-test-mcp" / "runs" / "run-1" / "visualizer" / "index.html"

    assert view_model_path.is_file()
    assert offline_path.is_file()
    assert index_path.is_file()

    vm = json.loads(view_model_path.read_text(encoding="utf-8"))
    assert "clusters" in vm
    assert "nodesById" in vm

    html = offline_path.read_text(encoding="utf-8")
    assert "Godot Visualizer Offline Snapshot" in html
    assert "run-1" in html

    index_html = index_path.read_text(encoding="utf-8")
    assert "visualizer-inline-data" in index_html
    assert "\"run_id\": \"run-1\"" in index_html
    assert "\"view_model\"" in index_html
    assert "\"runtime_diagnostics\"" in index_html

    assert artifacts.view_model_path.endswith("view_model.json")
    assert artifacts.offline_html_path.endswith("offline.html")
