"""Integration-style tests for visualizer MCP tool routing."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.server import TOOLS, handle_call_tool


def _decode(result: list) -> dict:
    return json.loads(result[0].text)


class TestVisualizerToolRegistration:
    def test_visualizer_tools_registered(self) -> None:
        names = [tool.name for tool in TOOLS]
        assert "godot_visualizer_map_project" in names
        assert "godot_visualizer_live_start" in names
        assert "godot_visualizer_live_stop" in names
        assert "godot_visualizer_diff_runs" in names
        assert "godot_visualizer_edit_propose" in names
        assert "godot_visualizer_edit_apply" in names
        assert "godot_visualizer_edit_cancel" in names


class TestVisualizerToolRouting:
    @pytest.mark.asyncio
    async def test_map_project_routes_to_service(self) -> None:
        with patch("src.server.visualizer_service.map_project", new_callable=AsyncMock) as mock_map:
            mock_map.return_value = {
                "status": "ok",
                "run_id": "r1",
                "summary": {"runtime_error_count": 1, "runtime_warning_count": 0},
            }
            result = await handle_call_tool("godot_visualizer_map_project", {"project_path": "/tmp/project"})
            payload = _decode(result)
            assert payload["status"] == "ok"
            assert payload["run_id"] == "r1"
            assert payload["summary"]["runtime_error_count"] == 1
            assert payload["summary"]["runtime_warning_count"] == 0
            assert mock_map.await_count == 1

    @pytest.mark.asyncio
    async def test_live_stop_routes_to_service(self) -> None:
        with patch("src.server.visualizer_service.live_stop", new_callable=AsyncMock) as mock_stop:
            mock_stop.return_value = {"status": "ok", "stopped": True}
            result = await handle_call_tool("godot_visualizer_live_stop", {})
            payload = _decode(result)
            assert payload["status"] == "ok"
            assert mock_stop.await_count == 1

    @pytest.mark.asyncio
    async def test_edit_propose_routes_to_service(self) -> None:
        with patch("src.server.visualizer_service.edit_propose") as mock_propose:
            mock_propose.return_value = {"status": "proposed", "edit_session": {"edit_session_id": "e1"}}
            result = await handle_call_tool(
                "godot_visualizer_edit_propose",
                {
                    "project_path": "/tmp/project",
                    "file_path": "a.txt",
                    "operation": "append_text",
                    "payload": {"text": "x"},
                    "reason": "test",
                },
            )
            payload = _decode(result)
            assert payload["status"] == "proposed"
            assert mock_propose.call_count == 1

    @pytest.mark.asyncio
    async def test_diff_runs_without_baseline_returns_ok(self) -> None:
        with (
            patch("src.server.visualizer_service.list_runs") as mock_list,
            patch("src.server.visualizer_service.diff_runs") as mock_diff,
        ):
            mock_list.return_value = {"status": "ok", "runs": [], "total": 0}
            mock_diff.return_value = {
                "run_id": "r1",
                "baseline_run_id": "",
                "summary": {"added_node_count": 0},
                "warnings": ["baseline_unavailable"],
            }
            result = await handle_call_tool("godot_visualizer_diff_runs", {"project_path": "/tmp/project", "run_id": "r1"})
            payload = _decode(result)
            assert payload["status"] == "ok"
            assert payload["warnings"] == ["baseline_unavailable"]
