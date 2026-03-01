"""Unit tests for runtime visualizer mapper."""

from __future__ import annotations

import pytest

from src.visualizer_runtime_mapper import VisualizerRuntimeMapper


@pytest.mark.asyncio
async def test_runtime_mapper_uses_hook_probe() -> None:
    async def ws_command(method: str, params: dict | None = None):
        _ = params
        if method == "get_capabilities":
            return {
                "status": "ok",
                "hook_targets": [{"path": "/root/Main", "method": "test_mcp_get_visualizer_probe"}],
            }
        if method == "call_method":
            return {
                "status": "ok",
                "return_value": {
                    "current_tick": 120,
                    "entities": [{"id": "e1", "name": "A"}],
                    "systems": [{"id": "s1", "name": "Sim"}],
                    "events": [
                        {"id": "ev1", "tick": 10, "type": "spawn", "source_id": "e1"},
                        {"id": "ev2", "tick": 12, "type": "move", "source_id": "e1", "causes": ["ev1"]},
                    ],
                },
            }
        return {"status": "error"}

    mapper = VisualizerRuntimeMapper()
    result = await mapper.collect(ws_command=ws_command, read_errors=lambda: {"errors": [], "warnings": []})

    assert result.runtime_source == "hook"
    assert result.timeline["event_count"] == 2
    assert any(edge.edge_type == "causes" for edge in result.edges)


@pytest.mark.asyncio
async def test_runtime_mapper_falls_back_when_hook_missing() -> None:
    async def ws_command(method: str, params: dict | None = None):
        _ = params
        if method == "get_capabilities":
            return {"status": "ok", "hook_targets": []}
        if method == "get_tree_info":
            return {"status": "ok", "root_children": [{"name": "Main", "class": "Node2D"}]}
        if method == "get_visual_snapshot":
            return {"status": "ok", "nodes": [{"name": "HUD", "path": "/root/Main/HUD"}]}
        return {"status": "ok"}

    mapper = VisualizerRuntimeMapper()
    result = await mapper.collect(
        ws_command=ws_command,
        read_errors=lambda: {"errors": [{"category": "SCRIPT_ERROR", "message": "x"}], "warnings": []},
    )

    assert result.runtime_source == "fallback"
    assert result.timeline["event_count"] == 1


@pytest.mark.asyncio
async def test_runtime_mapper_classifies_autoload_singleton_collision() -> None:
    async def ws_command(method: str, params: dict | None = None):
        _ = params
        if method == "get_capabilities":
            return {"status": "ok", "hook_targets": []}
        if method == "get_tree_info":
            return {"status": "ok", "root_children": []}
        if method == "get_visual_snapshot":
            return {"status": "ok", "nodes": []}
        return {"status": "ok"}

    mapper = VisualizerRuntimeMapper()
    result = await mapper.collect(
        ws_command=ws_command,
        read_errors=lambda: {
            "errors": [
                {
                    "message": 'Parse Error: Class "TestHarness" hides an autoload singleton.',
                    "source": "res://scripts/test_harness/test_harness.gd",
                    "line": -1,
                }
            ],
            "warnings": [],
        },
    )

    assert result.runtime_source == "fallback"
    assert len(result.runtime_diagnostics) == 1
    diagnostic = result.runtime_diagnostics[0]
    assert diagnostic["code"] == "autoload_singleton_collision"
    assert "Rename one side" in diagnostic["hint"]
