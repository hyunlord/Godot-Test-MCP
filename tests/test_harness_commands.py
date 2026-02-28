"""Tests for Phase 3 harness commands (inspect, run_script, batch).

Since harness commands are GDScript running inside Godot, these tests verify:
1. MCP tool registration (new tools exist in TOOLS list)
2. Tool handler routing (correct WS command is sent)
3. Security blocklist patterns exist in harness source
4. Tool schema validation
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.server import TOOLS, handle_call_tool


# ── Tool Registration Tests ──────────────────────────────────────────────


class TestToolRegistration:
    """Verify Phase 3 tools are registered in the TOOLS list."""

    def _tool_names(self) -> list[str]:
        return [t.name for t in TOOLS]

    def test_godot_inspect_registered(self) -> None:
        assert "godot_inspect" in self._tool_names()

    def test_godot_run_script_registered(self) -> None:
        assert "godot_run_script" in self._tool_names()

    def test_godot_batch_registered(self) -> None:
        assert "godot_batch" in self._tool_names()

    def test_inspect_has_expression_required(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_inspect")
        assert "expression" in tool.inputSchema["properties"]
        assert "expression" in tool.inputSchema.get("required", [])

    def test_inspect_has_depth_optional(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_inspect")
        assert "depth" in tool.inputSchema["properties"]
        assert "depth" not in tool.inputSchema.get("required", [])

    def test_run_script_has_code_required(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_run_script")
        assert "code" in tool.inputSchema["properties"]
        assert "code" in tool.inputSchema.get("required", [])

    def test_batch_has_expressions_required(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_batch")
        schema = tool.inputSchema
        assert "expressions" in schema["properties"]
        assert "expressions" in schema.get("required", [])
        assert schema["properties"]["expressions"]["type"] == "array"


# ── Tool Description Quality Tests ───────────────────────────────────────


class TestToolDescriptions:
    """Verify all tool descriptions follow the Phase 3 pattern."""

    def test_all_tools_have_descriptions(self) -> None:
        for tool in TOOLS:
            assert tool.description, f"{tool.name} has empty description"
            assert len(tool.description) > 20, f"{tool.name} description too short"

    def test_phase3_tools_have_examples(self) -> None:
        phase3_tools = ["godot_inspect", "godot_run_script", "godot_batch"]
        for name in phase3_tools:
            tool = next(t for t in TOOLS if t.name == name)
            assert "Example" in tool.description, f"{name} missing example"

    def test_phase3_tools_have_usage_guidance(self) -> None:
        phase3_tools = ["godot_inspect", "godot_run_script", "godot_batch"]
        for name in phase3_tools:
            tool = next(t for t in TOOLS if t.name == name)
            assert "USE THIS" in tool.description or "USE" in tool.description, (
                f"{name} missing usage guidance"
            )

    def test_eval_mentions_limitations(self) -> None:
        tool = next(t for t in TOOLS if t.name == "godot_eval")
        desc = tool.description.lower()
        assert "single" in desc or "no var" in desc or "run_script" in desc, (
            "godot_eval should mention its limitations or point to run_script"
        )


# ── Tool Handler Routing Tests ───────────────────────────────────────────


class TestToolHandlerRouting:
    """Verify tool handlers send correct WS commands."""

    @pytest.fixture(autouse=True)
    def mock_ws(self):
        """Mock the _ws_tool helper to capture command routing."""
        with patch("src.server._ws_tool", new_callable=AsyncMock) as mock:
            mock.return_value = [{"type": "text", "text": "{}"}]
            self.mock_ws_tool = mock
            yield mock

    @pytest.mark.asyncio
    async def test_inspect_sends_inspect_command(self) -> None:
        await handle_call_tool("godot_inspect", {"expression": "get_tree().root"})
        self.mock_ws_tool.assert_called_once()
        args = self.mock_ws_tool.call_args
        assert args[0][0] == "inspect"
        assert args[0][1]["expression"] == "get_tree().root"

    @pytest.mark.asyncio
    async def test_inspect_forwards_depth(self) -> None:
        await handle_call_tool("godot_inspect", {"expression": "get_tree().root", "depth": 2})
        args = self.mock_ws_tool.call_args
        assert args[0][1].get("depth") == 2

    @pytest.mark.asyncio
    async def test_run_script_sends_run_script_command(self) -> None:
        await handle_call_tool("godot_run_script", {"code": "return 1 + 2"})
        self.mock_ws_tool.assert_called_once()
        args = self.mock_ws_tool.call_args
        assert args[0][0] == "run_script"
        assert args[0][1]["code"] == "return 1 + 2"

    @pytest.mark.asyncio
    async def test_batch_sends_batch_command(self) -> None:
        exprs = ["1+1", "2+2", "3+3"]
        await handle_call_tool("godot_batch", {"expressions": exprs})
        self.mock_ws_tool.assert_called_once()
        args = self.mock_ws_tool.call_args
        assert args[0][0] == "batch"
        assert args[0][1]["expressions"] == exprs


# ── Security Blocklist Tests ─────────────────────────────────────────────


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

    def test_blocks_dir_access(self) -> None:
        assert '"DirAccess."' in self.harness_source

    def test_blocks_classdb(self) -> None:
        assert '"ClassDB."' in self.harness_source

    def test_blocks_resource_saver(self) -> None:
        assert '"ResourceSaver."' in self.harness_source

    def test_blocks_project_settings_save(self) -> None:
        assert '"ProjectSettings.save"' in self.harness_source

    def test_run_script_checks_blocklist_before_compile(self) -> None:
        """Verify blocklist check comes before GDScript.new() compilation."""
        blocklist_pos = self.harness_source.find("_BLOCKED_PATTERNS")
        compile_pos = self.harness_source.find("script.reload()")
        # The blocklist check (find pattern in code) should appear before compilation
        security_check_pos = self.harness_source.find("code.find(pattern)")
        assert security_check_pos > 0, "Security check not found"
        assert security_check_pos < compile_pos, "Security check must come before compilation"


# ── Harness Command Structure Tests ──────────────────────────────────────


class TestHarnessCommandStructure:
    """Verify harness GDScript has correct command dispatch structure."""

    @pytest.fixture(autouse=True)
    def load_harness(self) -> None:
        harness_path = Path(__file__).parent.parent / "src" / "harness" / "test_harness.gd"
        self.harness_source = harness_path.read_text(encoding="utf-8")

    def test_dispatch_has_inspect(self) -> None:
        assert '"inspect"' in self.harness_source

    def test_dispatch_has_run_script(self) -> None:
        assert '"run_script"' in self.harness_source

    def test_dispatch_has_batch(self) -> None:
        assert '"batch"' in self.harness_source

    def test_cmd_inspect_function_exists(self) -> None:
        assert "func _cmd_inspect(" in self.harness_source

    def test_cmd_run_script_function_exists(self) -> None:
        assert "func _cmd_run_script(" in self.harness_source

    def test_cmd_batch_function_exists(self) -> None:
        assert "func _cmd_batch(" in self.harness_source

    def test_inspect_object_helper_exists(self) -> None:
        assert "func _inspect_object(" in self.harness_source

    def test_inspect_returns_properties(self) -> None:
        """Verify inspect collects script properties."""
        assert "PROPERTY_USAGE_SCRIPT_VARIABLE" in self.harness_source

    def test_inspect_returns_methods(self) -> None:
        """Verify inspect collects script methods."""
        assert "get_script_method_list" in self.harness_source

    def test_inspect_returns_signals(self) -> None:
        """Verify inspect collects script signals."""
        assert "get_script_signal_list" in self.harness_source

    def test_run_script_wraps_in_refcounted(self) -> None:
        """Verify run_script uses RefCounted wrapper pattern."""
        assert "extends RefCounted" in self.harness_source

    def test_run_script_provides_get_tree(self) -> None:
        """Verify run_script injects get_tree() access."""
        assert "_tree_ref" in self.harness_source

    def test_batch_returns_per_expression_status(self) -> None:
        """Verify batch includes status field in results."""
        # Check that batch appends status: "ok" and status: "error"
        assert '"status": "ok"' in self.harness_source
        assert '"status": "error"' in self.harness_source
