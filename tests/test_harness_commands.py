"""Tests for harness commands and NL tool integration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.server import TOOLS, handle_call_tool


class TestToolRegistration:
    """Verify required tools are registered in the TOOLS list."""

    def _tool_names(self) -> list[str]:
        return [t.name for t in TOOLS]

    def test_godot_inspect_registered(self) -> None:
        assert "godot_inspect" in self._tool_names()

    def test_godot_run_script_registered(self) -> None:
        assert "godot_run_script" in self._tool_names()

    def test_godot_batch_registered(self) -> None:
        assert "godot_batch" in self._tool_names()

    def test_godot_compile_nl_test_registered(self) -> None:
        assert "godot_compile_nl_test" in self._tool_names()

    def test_godot_run_nl_test_registered(self) -> None:
        assert "godot_run_nl_test" in self._tool_names()

    def test_godot_get_nl_capabilities_registered(self) -> None:
        assert "godot_get_nl_capabilities" in self._tool_names()

    def test_compile_nl_requires_spec_text(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_compile_nl_test")
        assert "spec_text" in tool.inputSchema["properties"]
        assert "spec_text" in tool.inputSchema.get("required", [])

    def test_run_nl_has_mode_auto(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_run_nl_test")
        mode_schema = tool.inputSchema["properties"]["mode"]
        assert mode_schema["default"] == "auto"
        assert "auto" in mode_schema["enum"]


class TestToolDescriptions:
    """Verify descriptions are present and include guidance."""

    def test_all_tools_have_descriptions(self) -> None:
        for tool in TOOLS:
            assert tool.description, f"{tool.name} has empty description"
            assert len(tool.description) > 20, f"{tool.name} description too short"

    def test_eval_mentions_legacy_or_limitations(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_eval")
        desc = tool.description.lower()
        assert "single" in desc or "legacy" in desc or "run_script" in desc

    def test_run_script_mentions_legacy_optional(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_run_script")
        assert "legacy/optional" in tool.description.lower()


class TestToolHandlerRouting:
    """Verify routing behavior for WS-backed and NL tools."""

    @pytest.fixture(autouse=True)
    def mock_ws(self) -> AsyncMock:
        with patch("src.server._ws_tool", new_callable=AsyncMock) as mock:
            mock.return_value = [{"type": "text", "text": "{}"}]
            self.mock_ws_tool = mock
            yield mock

    @pytest.mark.asyncio
    async def test_inspect_sends_inspect_command(self) -> None:
        await handle_call_tool("godot_inspect", {"expression": "get_tree().root"})
        args = self.mock_ws_tool.call_args
        assert args[0][0] == "inspect"
        assert args[0][1]["expression"] == "get_tree().root"

    @pytest.mark.asyncio
    async def test_batch_sends_batch_command(self) -> None:
        exprs = ["1+1", "2+2"]
        await handle_call_tool("godot_batch", {"expressions": exprs})
        args = self.mock_ws_tool.call_args
        assert args[0][0] == "batch"
        assert args[0][1]["expressions"] == exprs

    @pytest.mark.asyncio
    async def test_get_nl_capabilities_routes_to_ws(self) -> None:
        with patch("src.server._ws_command", new_callable=AsyncMock) as mock_ws_command:
            mock_ws_command.return_value = {
                "status": "ok",
                "nodes": [],
                "groups": [],
                "hook_methods": [],
                "hook_targets": [],
                "node_count": 0,
                "groups_count": 0,
            }
            await handle_call_tool("godot_get_nl_capabilities", {})
            mock_ws_command.assert_called_once_with("get_capabilities", {})

    @pytest.mark.asyncio
    async def test_compile_nl_routes_to_compiler_handler(self) -> None:
        with patch("src.server._godot_compile_nl_test", new_callable=AsyncMock) as mock_compile:
            mock_compile.return_value = []
            await handle_call_tool("godot_compile_nl_test", {"spec_text": "no errors"})
            mock_compile.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_nl_routes_to_executor_handler(self) -> None:
        with patch("src.server._godot_run_nl_test", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = []
            await handle_call_tool("godot_run_nl_test", {"spec_text": "no errors"})
            mock_run.assert_called_once()


class TestSecurityBlocklist:
    """Verify harness source contains security patterns for run_script."""

    @pytest.fixture(autouse=True)
    def load_harness(self) -> None:
        harness_path = Path(__file__).parent.parent / "src" / "harness" / "test_harness.gd"
        assert harness_path.exists(), f"Harness not found at {harness_path}"
        self.harness_source = harness_path.read_text(encoding="utf-8")

    def test_blocked_patterns_constant_exists(self) -> None:
        assert "_BLOCKED_PATTERNS" in self.harness_source

    def test_blocks_os_access(self) -> None:
        assert '"OS."' in self.harness_source

    def test_blocks_file_access(self) -> None:
        assert '"FileAccess."' in self.harness_source

    def test_run_script_checks_blocklist_before_compile(self) -> None:
        compile_pos = self.harness_source.find("script.reload()")
        security_check_pos = self.harness_source.find("code.find(pattern)")
        assert security_check_pos > 0
        assert security_check_pos < compile_pos


class TestHarnessCommandStructure:
    """Verify harness GDScript command surface and generic introspection."""

    @pytest.fixture(autouse=True)
    def load_harness(self) -> None:
        harness_path = Path(__file__).parent.parent / "src" / "harness" / "test_harness.gd"
        self.harness_source = harness_path.read_text(encoding="utf-8")

    def test_dispatch_has_nl_support_commands(self) -> None:
        assert '"get_capabilities"' in self.harness_source
        assert '"capture_screenshot"' in self.harness_source
        assert '"capture_frame"' in self.harness_source
        assert '"get_visual_snapshot"' in self.harness_source
        assert '"send_input"' in self.harness_source
        assert '"wait_frames"' in self.harness_source

    def test_nl_command_functions_exist(self) -> None:
        assert "func _cmd_get_capabilities(" in self.harness_source
        assert "func _cmd_capture_screenshot(" in self.harness_source
        assert "func _cmd_send_input(" in self.harness_source
        assert "func _cmd_wait_frames(" in self.harness_source
        assert "hook_targets" in self.harness_source
        assert "node_count" in self.harness_source
        assert "groups_count" in self.harness_source

    def test_inspect_uses_generic_object_introspection(self) -> None:
        assert "get_method_list" in self.harness_source
        assert "get_signal_list" in self.harness_source
        assert "get_property_list" in self.harness_source

    def test_inspect_helper_exists(self) -> None:
        assert "func _inspect_object(" in self.harness_source

    def test_batch_returns_per_expression_status(self) -> None:
        assert '"status": "ok"' in self.harness_source
        assert '"status": "error"' in self.harness_source
