"""Integration-style tests for NL MCP tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.server import TOOLS, _compile_status, handle_call_tool


def _decode_payload(result: list) -> dict:
    text = result[0].text
    return json.loads(text)


class TestNLToolRegistration:
    """Registration and schema checks for NL tools."""

    def test_nl_tools_registered(self) -> None:
        names = [tool.name for tool in TOOLS]
        assert "godot_compile_nl_test" in names
        assert "godot_run_nl_test" in names
        assert "godot_get_nl_capabilities" in names

    def test_run_nl_schema_has_timeout_and_artifact_level(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_run_nl_test")
        props = tool.inputSchema["properties"]
        assert "timeout_seconds" in props
        assert "artifact_level" in props


class TestCompileTool:
    """Compile tool behavior tests."""

    @pytest.mark.asyncio
    async def test_compile_nl_returns_compiled_plan(self) -> None:
        result = await handle_call_tool(
            "godot_compile_nl_test",
            {"spec_text": "set /root/Main.score to 10. /root/Main.score should be 10"},
        )
        payload = _decode_payload(result)
        assert payload["compile_status"] in {"OK", "PARTIAL"}
        assert "compiled_plan" in payload
        assert "steps" in payload["compiled_plan"]

    @pytest.mark.asyncio
    async def test_compile_nl_requires_spec_text(self) -> None:
        result = await handle_call_tool("godot_compile_nl_test", {})
        payload = _decode_payload(result)
        assert payload["compile_status"] == "FAILED"
        assert payload["error"] == "spec_text is required"


class TestCapabilityRouting:
    """WS routing for capability discovery."""

    @pytest.mark.asyncio
    async def test_get_nl_capabilities_calls_ws_command_and_sets_shape(self) -> None:
        with patch("src.server._ws_command", new_callable=AsyncMock) as mock_ws_command:
            mock_ws_command.return_value = {
                "status": "ok",
                "nodes": [{"path": "/root/Main"}],
                "groups": ["test"],
                "hook_methods": ["test_mcp_ping"],
                "hook_targets": [{"path": "/root/Main", "method": "test_mcp_ping"}],
                "node_count": 1,
                "groups_count": 1,
            }
            result = await handle_call_tool("godot_get_nl_capabilities", {})
            payload = _decode_payload(result)
            mock_ws_command.assert_called_once_with("get_capabilities", {})
            assert payload["status"] == "ok"
            assert "hook_targets" in payload
            assert payload["node_count"] == 1
            assert payload["groups_count"] == 1


class TestRunTool:
    """Run tool basic error handling and route coverage."""

    @pytest.mark.asyncio
    async def test_run_nl_requires_spec_text(self) -> None:
        result = await handle_call_tool("godot_run_nl_test", {})
        payload = _decode_payload(result)
        assert payload["result"] == "ERROR"
        assert "spec_text is required" in payload["summary"]


class TestCompileStatus:
    """Compile status helper behavior."""

    def test_compile_status_failed(self) -> None:
        assert _compile_status(0.2, 0) == "FAILED"

    def test_compile_status_partial(self) -> None:
        assert _compile_status(0.8, 1) == "PARTIAL"

    def test_compile_status_ok(self) -> None:
        assert _compile_status(0.9, 0) == "OK"
