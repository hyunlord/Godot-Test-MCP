"""MCP server for automated Godot game testing."""

from __future__ import annotations

import asyncio
import json
import time

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .config import Config
from .godot_process import GodotProcessManager
from .ws_client import GodotWebSocketClient

server = Server("godot-test-mcp")
manager: GodotProcessManager
ws_client: GodotWebSocketClient = GodotWebSocketClient()


def _text(data: dict) -> list[TextContent]:
    """Convert a dict to MCP TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ── Tool definitions ─────────────────────────────────────────────────────

TOOLS = [
    # ── Phase 1 tools ────────────────────────────────────────────────
    Tool(
        name="godot_launch",
        description=(
            "Launch Godot game process. "
            "mode: 'headless' (no GUI), 'windowed' (GUI), or 'editor'. "
            "scene: scene path to run (empty = main scene). "
            "extra_args: additional Godot CLI arguments. "
            "test_harness: enable WebSocket test bridge (Phase 2)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["headless", "windowed", "editor"],
                    "default": "headless",
                    "description": "Run mode: headless (no GUI), windowed (GUI), or editor",
                },
                "scene": {
                    "type": "string",
                    "default": "",
                    "description": "Scene path to run (empty = main scene from project.godot)",
                },
                "extra_args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                    "description": "Additional Godot CLI arguments",
                },
                "test_harness": {
                    "type": "boolean",
                    "default": False,
                    "description": "Enable TestHarness WebSocket bridge for Phase 2 tools",
                },
            },
        },
    ),
    Tool(
        name="godot_stop",
        description="Stop the running Godot process. force=true sends SIGKILL immediately.",
        inputSchema={
            "type": "object",
            "properties": {
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "True = SIGKILL (immediate), False = SIGTERM (graceful)",
                },
            },
        },
    ),
    Tool(
        name="godot_get_errors",
        description="Get captured errors and/or warnings from the running or last-run Godot process.",
        inputSchema={
            "type": "object",
            "properties": {
                "level": {
                    "type": "string",
                    "enum": ["error", "warning", "all"],
                    "default": "error",
                    "description": "Which messages to return: error, warning, or all",
                },
            },
        },
    ),
    Tool(
        name="godot_get_output",
        description="Get raw stdout/stderr output from the Godot process.",
        inputSchema={
            "type": "object",
            "properties": {
                "tail_lines": {
                    "type": "integer",
                    "default": 100,
                    "description": "Return last N lines",
                },
                "filter_pattern": {
                    "type": "string",
                    "default": "",
                    "description": "Regex pattern to filter lines (empty = no filter)",
                },
            },
        },
    ),
    Tool(
        name="godot_run_and_check",
        description=(
            "Launch game, run for N seconds, collect errors, stop, return PASS/FAIL verdict. "
            "This is the primary tool for automated verification after code changes."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "integer",
                    "default": 15,
                    "description": "How long to run the game (seconds). 15 is a good default.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["headless", "windowed"],
                    "default": "headless",
                    "description": "Run mode: headless (no GUI) or windowed (with GUI)",
                },
                "fail_on_warnings": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, warnings also cause FAIL result",
                },
                "scene": {
                    "type": "string",
                    "default": "",
                    "description": "Scene to run (empty = main scene)",
                },
                "test_harness": {
                    "type": "boolean",
                    "default": False,
                    "description": "Enable TestHarness for actual simulation (not idle map editor)",
                },
            },
        },
    ),
    Tool(
        name="godot_headless_import",
        description=(
            "Run Godot --headless --quit to verify project imports/parses correctly. "
            "Equivalent to a quick parse-check gate."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_get_status",
        description="Get current Godot process status (running/stopped/crashed).",
        inputSchema={"type": "object", "properties": {}},
    ),
    # ── Phase 2 tools ────────────────────────────────────────────────
    Tool(
        name="godot_advance_ticks",
        description=(
            "Advance the simulation by N ticks instantly. "
            "Requires Godot running with test_harness=true."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "default": 100,
                    "description": "Number of ticks to advance (1-100000)",
                },
            },
        },
    ),
    Tool(
        name="godot_get_tick",
        description="Get current simulation tick, game time, pause state, and speed.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_get_entity",
        description="Get full entity state by ID (all fields from entity_data.to_dict()).",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "Entity ID",
                },
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="godot_get_entity_field",
        description="Get a single field from an entity's state. Lightweight alternative to get_entity.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "Entity ID",
                },
                "field": {
                    "type": "string",
                    "description": "Field name (e.g. 'hunger', 'energy', 'position_x')",
                },
            },
            "required": ["id", "field"],
        },
    ),
    Tool(
        name="godot_get_entities",
        description="Get a list of entities with their full state.",
        inputSchema={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "enum": ["alive", "all"],
                    "default": "alive",
                    "description": "Filter: 'alive' (default) or 'all'",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max entities to return (1-200)",
                },
            },
        },
    ),
    Tool(
        name="godot_get_alive_count",
        description="Get the number of alive entities. Lightweight population check.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_get_settlement",
        description="Get settlement data by ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "Settlement ID",
                },
            },
            "required": ["id"],
        },
    ),
    Tool(
        name="godot_get_world_stats",
        description=(
            "Get aggregated world statistics: population, avg hunger/energy/stress, "
            "settlement count, min/max values."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_pause",
        description="Pause the simulation.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_resume",
        description="Resume the simulation.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    # Phase 1 tools
    if name == "godot_launch":
        return await _godot_launch(arguments)
    elif name == "godot_stop":
        return await _godot_stop(arguments)
    elif name == "godot_get_errors":
        return await _godot_get_errors(arguments)
    elif name == "godot_get_output":
        return await _godot_get_output(arguments)
    elif name == "godot_run_and_check":
        return await _godot_run_and_check(arguments)
    elif name == "godot_headless_import":
        return await _godot_headless_import(arguments)
    elif name == "godot_get_status":
        return await _godot_get_status(arguments)
    # Phase 2 tools
    elif name == "godot_advance_ticks":
        return await _godot_advance_ticks(arguments)
    elif name == "godot_get_tick":
        return await _godot_get_tick(arguments)
    elif name == "godot_get_entity":
        return await _godot_get_entity(arguments)
    elif name == "godot_get_entity_field":
        return await _godot_get_entity_field(arguments)
    elif name == "godot_get_entities":
        return await _godot_get_entities(arguments)
    elif name == "godot_get_alive_count":
        return await _godot_get_alive_count(arguments)
    elif name == "godot_get_settlement":
        return await _godot_get_settlement(arguments)
    elif name == "godot_get_world_stats":
        return await _godot_get_world_stats(arguments)
    elif name == "godot_pause":
        return await _godot_pause(arguments)
    elif name == "godot_resume":
        return await _godot_resume(arguments)
    else:
        return _text({"error": f"Unknown tool: {name}"})


# ── Phase 1 tool implementations ─────────────────────────────────────────


async def _godot_launch(args: dict) -> list[TextContent]:
    mode = args.get("mode", "headless")
    scene = args.get("scene", "")
    extra_args = args.get("extra_args", [])
    test_harness = args.get("test_harness", False)
    pid = await manager.launch(mode, scene, extra_args, test_harness=test_harness)
    return _text({"status": "launched", "pid": pid, "mode": mode, "test_harness": test_harness})


async def _godot_stop(args: dict) -> list[TextContent]:
    # Disconnect WebSocket first
    if ws_client.is_connected:
        await ws_client.disconnect()

    force = args.get("force", False)
    if not manager.is_running:
        return _text({"status": "not_running"})
    runtime = manager.uptime
    exit_code = await manager.stop(force)
    return _text({
        "status": "stopped",
        "exit_code": exit_code,
        "runtime_seconds": round(runtime, 1),
    })


async def _godot_get_errors(args: dict) -> list[TextContent]:
    level = args.get("level", "error")
    errors = manager.get_errors() if level in ("error", "all") else []
    warnings = manager.get_warnings() if level in ("warning", "all") else []
    return _text({
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    })


async def _godot_get_output(args: dict) -> list[TextContent]:
    tail_lines = args.get("tail_lines", 100)
    filter_pattern = args.get("filter_pattern", "")
    lines = manager.get_output(tail=tail_lines, pattern=filter_pattern)
    return _text({
        "line_count": len(lines),
        "output": "\n".join(lines),
        "total_lines": len(manager._stdout_lines) + len(manager._stderr_lines),
    })


async def _godot_run_and_check(args: dict) -> list[TextContent]:
    seconds = args.get("seconds", 15)
    mode = args.get("mode", "headless")
    fail_on_warnings = args.get("fail_on_warnings", False)
    scene = args.get("scene", "")
    test_harness = args.get("test_harness", False)

    # 1. Stop if already running
    if manager.is_running:
        if ws_client.is_connected:
            await ws_client.disconnect()
        await manager.stop()

    # 2. Launch
    await manager.launch(mode, scene, [], test_harness=test_harness)

    # 3. Wait N seconds, detect early crash
    start = time.time()
    while time.time() - start < seconds:
        if not manager.is_running:
            break
        await asyncio.sleep(0.5)

    # 4. Stop if still running
    runtime = manager.uptime
    crashed = False
    exit_code = 0
    if manager.is_running:
        if ws_client.is_connected:
            await ws_client.disconnect()
        exit_code = await manager.stop()
    else:
        exit_code = manager.exit_code or 0
        crashed = runtime < (seconds - 1)  # Died early = crash

    # 5. Collect errors
    errors = manager.get_errors()
    warnings = manager.get_warnings()

    # 6. Verdict
    failed = len(errors) > 0 or crashed
    if fail_on_warnings and len(warnings) > 0:
        failed = True

    # 7. Summary
    if not failed:
        summary = f"Game ran for {runtime:.1f}s with no errors."
    else:
        parts: list[str] = []
        if crashed:
            parts.append(f"crashed after {runtime:.1f}s")
        if errors:
            e = errors[0]
            src = e.get("source", "unknown")
            ln = e.get("line", "?")
            parts.append(f"{len(errors)} error(s), first: {src}:{ln}")
        summary = "Game " + ", ".join(parts) + "."

    return _text({
        "result": "FAIL" if failed else "PASS",
        "runtime_seconds": round(runtime, 1),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings if fail_on_warnings else [],
        "crashed": crashed,
        "exit_code": exit_code,
        "summary": summary,
    })


async def _godot_headless_import(args: dict) -> list[TextContent]:
    await manager.launch("headless", "", ["--quit"])
    exit_code = await manager.wait_for_exit(timeout=60.0)
    errors = manager.get_errors()
    output = "\n".join(manager.get_output(tail=50))
    return _text({
        "result": "FAIL" if (exit_code != 0 or len(errors) > 0) else "PASS",
        "exit_code": exit_code,
        "error_count": len(errors),
        "errors": errors,
        "output": output,
    })


async def _godot_get_status(args: dict) -> list[TextContent]:
    if manager.is_running:
        return _text({
            "status": "running",
            "pid": manager._process.pid,  # type: ignore[union-attr]
            "uptime_seconds": round(manager.uptime, 1),
            "error_count": len(manager.get_errors()),
        })
    elif manager._process is None:
        return _text({"status": "stopped"})
    else:
        return _text({
            "status": "crashed" if (manager.exit_code or 0) != 0 else "stopped",
            "exit_code": manager.exit_code,
            "error_count": len(manager.get_errors()),
        })


# ── Phase 2 tool implementations ─────────────────────────────────────────


async def _ensure_ws_connected() -> None:
    """Connect to Godot WS if not already connected."""
    if not ws_client.is_connected:
        await ws_client.connect()


async def _godot_advance_ticks(args: dict) -> list[TextContent]:
    count = args.get("count", 100)
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("advance_ticks", {"count": count})
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_get_tick(args: dict) -> list[TextContent]:
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("get_tick")
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_get_entity(args: dict) -> list[TextContent]:
    entity_id = args.get("id", -1)
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("get_entity", {"id": entity_id})
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_get_entity_field(args: dict) -> list[TextContent]:
    entity_id = args.get("id", -1)
    field = args.get("field", "")
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("get_entity_field", {"id": entity_id, "field": field})
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_get_entities(args: dict) -> list[TextContent]:
    filter_str = args.get("filter", "alive")
    limit = args.get("limit", 50)
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("get_entities", {"filter": filter_str, "limit": limit})
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_get_alive_count(args: dict) -> list[TextContent]:
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("get_alive_count")
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_get_settlement(args: dict) -> list[TextContent]:
    settlement_id = args.get("id", -1)
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("get_settlement", {"id": settlement_id})
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_get_world_stats(args: dict) -> list[TextContent]:
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("get_world_stats")
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_pause(args: dict) -> list[TextContent]:
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("pause")
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_resume(args: dict) -> list[TextContent]:
    try:
        await _ensure_ws_connected()
        result = await ws_client.send_command("resume")
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


# ── Entrypoint ──────────────────────────────────────────────────────────


async def main() -> None:
    global manager
    config = Config.resolve()
    manager = GodotProcessManager(config)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run() -> None:
    """Synchronous entrypoint for CLI and uvx."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
