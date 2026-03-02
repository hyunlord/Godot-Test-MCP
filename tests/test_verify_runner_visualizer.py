"""Verifier tests for visualizer scenario kinds."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from scripts import verify_nl_runtime as vr


class FakeVisualizerClient:
    def __init__(self, project_path: Path, *, missing_css: bool = False) -> None:
        self._project_path = project_path
        self._missing_css = missing_css

    async def list_tools(self) -> list[str]:
        return [
            "godot_get_nl_capabilities",
            "godot_compile_nl_test",
            "godot_run_nl_test",
            "godot_visualizer_map_project",
            "godot_visualizer_diff_runs",
            "godot_visualizer_live_start",
            "godot_visualizer_live_stop",
            "godot_launch",
            "godot_stop",
        ]

    async def call_tool_json(self, name: str, arguments: dict | None = None) -> dict:
        _ = arguments
        if name == "godot_get_nl_capabilities":
            return {
                "status": "ok",
                "nodes": [],
                "groups": [],
                "node_count": 0,
                "groups_count": 0,
                "hook_methods": [],
                "hook_targets": [],
                "has_test_hooks": False,
            }
        if name == "godot_compile_nl_test":
            return {"compile_status": "OK", "unsupported_phrases": [], "compiled_plan": {"steps": []}}
        if name == "godot_run_nl_test":
            return {
                "result": "PASS",
                "artifacts": {"screenshots": [], "frames": [], "video": {"path": None}, "logs": []},
            }
        if name == "godot_visualizer_map_project":
            run_id = "visual-run"
            base = self._project_path / ".godot-test-mcp" / "runs" / run_id / "visualizer"
            base.mkdir(parents=True, exist_ok=True)
            assets = base / "assets"
            assets.mkdir(parents=True, exist_ok=True)

            (base / "map.json").write_text(json.dumps({"nodes": [], "edges": [], "summary": {}}), encoding="utf-8")
            (base / "timeline.json").write_text(json.dumps({"events": [], "event_count": 0}), encoding="utf-8")
            (base / "causality.json").write_text(json.dumps({"links": []}), encoding="utf-8")
            (base / "diff.json").write_text(json.dumps({"summary": {"added_node_count": 0}}), encoding="utf-8")
            (base / "graph.bundle.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "nodes": [],
                        "edges": [],
                        "calls_edges": [],
                        "clusters": [],
                        "cluster_edges": [],
                        "search_index": {"items": []},
                        "layouts": {},
                        "board_model": {"clusters": [], "links": [], "hotspots": []},
                    }
                ),
                encoding="utf-8",
            )
            (base / "meta.json").write_text(
                json.dumps(
                    {
                        "runtime_source": "fallback",
                        "ui_version": 2,
                        "render_mode": "canvas_dom_hybrid",
                        "renderer_backend": "canvas2d_fallback",
                        "renderer_error_code": "none",
                        "renderer_error": "",
                        "scale_profile": "large",
                    }
                ),
                encoding="utf-8",
            )
            (base / "view_model.json").write_text(
                json.dumps(
                    {
                        "clusters": [],
                        "nodesById": {},
                        "edgesById": {},
                        "layers": {"cluster": {}, "structural": {}, "detail": {}},
                        "ui_defaults": {"default_layer": "cluster"},
                        "board_model": {"clusters": [], "links": [], "hotspots": []},
                        "cluster_layout_health": {
                            "overlap_count": 0,
                            "duplicate_anchor_count": 0,
                            "max_density_band": "2",
                        },
                    }
                ),
                encoding="utf-8",
            )
            (base / "index.html").write_text("<html></html>", encoding="utf-8")
            (base / "app.js").write_text("console.log('x')", encoding="utf-8")
            (assets / "app.123.js").write_text("console.log('x')", encoding="utf-8")
            if not self._missing_css:
                (base / "styles.css").write_text("body{}", encoding="utf-8")
                (assets / "app.123.css").write_text("body{}", encoding="utf-8")
            (base / "offline.html").write_text("<html>offline</html>", encoding="utf-8")

            return {
                "status": "ok",
                "run_id": run_id,
                "baseline_run_id": "",
                "artifacts": {
                    "map_path": str(base / "map.json"),
                    "timeline_path": str(base / "timeline.json"),
                    "causality_path": str(base / "causality.json"),
                    "diff_path": str(base / "diff.json"),
                    "meta_path": str(base / "meta.json"),
                    "view_model_path": str(base / "view_model.json"),
                    "bundle_path": str(base / "graph.bundle.json"),
                    "html_path": str(base / "index.html"),
                    "js_path": str(base / "app.js"),
                    "css_path": str(base / "styles.css"),
                    "assets_dir": str(assets),
                    "offline_html_path": str(base / "offline.html"),
                },
            }
        if name == "godot_visualizer_diff_runs":
            return {"status": "ok", "summary": {"added_node_count": 1}}
        if name == "godot_visualizer_live_start":
            return {"status": "ok", "url": "http://127.0.0.1:9999/"}
        if name == "godot_visualizer_live_stop":
            return {"status": "ok", "stopped": True}
        if name == "godot_launch":
            return {"status": "launched"}
        if name == "godot_stop":
            return {"status": "stopped"}
        return {"status": "error", "message": f"unknown tool: {name}"}


def _build_config(tmp_path: Path, scenario_pack: Path) -> vr.VerifierConfig:
    project = tmp_path / "game"
    project.mkdir(parents=True)
    (project / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")

    output = tmp_path / "report.json"
    return vr.VerifierConfig(
        project_path=project.resolve(),
        godot_path=None,
        server_command=["python", "-m", "src.server"],
        scenario_pack=scenario_pack.resolve(),
        output_path=output.resolve(),
        timeout_seconds=30,
        strict=True,
        repo_root=Path(__file__).resolve().parent.parent,
    )


def _write_pack(path: Path, *, include_live: bool = False) -> None:
    scenarios = [
        {"id": "visualizer_contract", "kind": "visualizer_contract"},
        {"id": "visualizer_diff_contract", "kind": "visualizer_diff_contract"},
    ]
    if include_live:
        scenarios.append({"id": "visualizer_live_contract", "kind": "visualizer_live_contract"})
    path.write_text(json.dumps({"name": "visual", "version": 1, "scenarios": scenarios}), encoding="utf-8")


@pytest.mark.asyncio
async def test_visualizer_contract_passes(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "visual.json"
    _write_pack(scenario_pack)
    config = _build_config(tmp_path, scenario_pack)

    client = FakeVisualizerClient(config.project_path)

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield client

    report = await vr.run_runtime_verification(config, client_factory=fake_factory)
    assert report["exit_code"] == 0
    vis = next(item for item in report["scenario_results"] if item["id"] == "visualizer_contract")
    assert vis["result"] == "PASS"


@pytest.mark.asyncio
async def test_visualizer_contract_fails_when_artifact_missing(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "visual.json"
    _write_pack(scenario_pack)
    config = _build_config(tmp_path, scenario_pack)

    client = FakeVisualizerClient(config.project_path, missing_css=True)

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield client

    report = await vr.run_runtime_verification(config, client_factory=fake_factory)
    assert report["exit_code"] == 1
    vis = next(item for item in report["scenario_results"] if item["id"] == "visualizer_contract")
    assert vis["result"] == "FAIL"


@pytest.mark.asyncio
async def test_visualizer_live_contract_passes(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "visual_live.json"
    _write_pack(scenario_pack, include_live=True)
    config = _build_config(tmp_path, scenario_pack)

    client = FakeVisualizerClient(config.project_path)

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield client

    report = await vr.run_runtime_verification(config, client_factory=fake_factory)
    live = next(item for item in report["scenario_results"] if item["id"] == "visualizer_live_contract")
    assert live["result"] == "PASS"
