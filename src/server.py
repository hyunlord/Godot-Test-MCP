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
from .injector import HarnessInjector
from .ws_client import GodotWebSocketClient

server = Server("godot-test-mcp")
manager: GodotProcessManager
injector: HarnessInjector | None = None
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
            "test_harness: inject WebSocket test bridge for Phase 2 tools (default true)."
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
                    "default": True,
                    "description": "Inject WebSocket test harness for Phase 2 tools",
                },
            },
        },
    ),
    Tool(
        name="godot_stop",
        description="Stop the running Godot process. Cleans up test harness if injected.",
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
            "This is the primary tool for automated verification after code changes. "
            "Does NOT inject test harness (Phase 1 error-check only)."
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
        name="godot_get_tree",
        description=(
            "Get scene tree overview: root children, node count, current scene, paused state. "
            "Requires Godot running with test_harness=true."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_get_node",
        description=(
            "Get node info + all script variables at a given path (e.g. '/root/Main'). "
            "Requires test harness."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Node path (e.g. '/root/Main')",
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="godot_get_property",
        description="Get a single property value from a node. Requires test harness.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Node path",
                },
                "property": {
                    "type": "string",
                    "description": "Property name",
                },
            },
            "required": ["path", "property"],
        },
    ),
    Tool(
        name="godot_set_property",
        description="Set a property on a node. Requires test harness.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Node path",
                },
                "property": {
                    "type": "string",
                    "description": "Property name",
                },
                "value": {
                    "description": "Value to set",
                },
            },
            "required": ["path", "property", "value"],
        },
    ),
    Tool(
        name="godot_call_method",
        description="Call a method on a node and return the result. Requires test harness.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Node path",
                },
                "method": {
                    "type": "string",
                    "description": "Method name",
                },
                "args": {
                    "type": "array",
                    "default": [],
                    "description": "Method arguments",
                },
            },
            "required": ["path", "method"],
        },
    ),
    Tool(
        name="godot_get_group",
        description="Get all nodes in a group. Requires test harness.",
        inputSchema={
            "type": "object",
            "properties": {
                "group": {
                    "type": "string",
                    "description": "Group name",
                },
            },
            "required": ["group"],
        },
    ),
    Tool(
        name="godot_ping",
        description="Health check — verify WebSocket connection to Godot test harness is alive.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_pause",
        description="Pause the game simulation (get_tree().paused = true). Requires test harness.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_resume",
        description="Resume the game simulation (get_tree().paused = false). Requires test harness.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_eval",
        description=(
            "Evaluate a GDScript expression in the running game via Expression class. "
            "Executed in the context of the scene root. Requires test harness. "
            "Example: get_node('Main').score"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "GDScript expression to evaluate",
                },
            },
            "required": ["expression"],
        },
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
    elif name == "godot_get_tree":
        return await _godot_get_tree(arguments)
    elif name == "godot_get_node":
        return await _godot_get_node(arguments)
    elif name == "godot_get_property":
        return await _godot_get_property(arguments)
    elif name == "godot_set_property":
        return await _godot_set_property(arguments)
    elif name == "godot_call_method":
        return await _godot_call_method(arguments)
    elif name == "godot_get_group":
        return await _godot_get_group(arguments)
    elif name == "godot_ping":
        return await _godot_ping(arguments)
    elif name == "godot_pause":
        return await _godot_pause(arguments)
    elif name == "godot_resume":
        return await _godot_resume(arguments)
    elif name == "godot_eval":
        return await _godot_eval(arguments)
    else:
        return _text({"error": f"Unknown tool: {name}"})


# ── Phase 1 tool implementations ─────────────────────────────────────────


async def _godot_launch(args: dict) -> list[TextContent]:
    global injector
    mode = args.get("mode", "headless")
    scene = args.get("scene", "")
    extra_args = list(args.get("extra_args", []))
    test_harness = args.get("test_harness", True)

    # Cleanup any leftover injection from previous crash
    if injector is not None:
        injector.cleanup()
        injector = None

    if test_harness:
        # 1. Inject harness into target project
        injector = HarnessInjector(manager._config.project_path)
        injector.inject()
        # 2. Add user args separator and harness port
        extra_args.extend(["--", "--test-harness-port=9877"])

    pid = await manager.launch(mode, scene, extra_args)

    ws_connected = False
    if test_harness:
        # 3. Try stdout-based harness detection first
        try:
            port = await manager.wait_for_harness(timeout=15.0)
            ws_client.port = port
            await ws_client.connect()
            ws_connected = True
        except (TimeoutError, RuntimeError, ConnectionError):
            # 4. Fallback: direct WS connection (headless stdout buffering workaround)
            ws_client.port = 9877
            for attempt in range(3):
                try:
                    await ws_client.connect()
                    ws_connected = True
                    break
                except (ConnectionError, OSError):
                    if attempt < 2:
                        await asyncio.sleep(5.0)

        if not ws_connected:
            return _text({
                "status": "launched",
                "pid": pid,
                "mode": mode,
                "test_harness": True,
                "ws_connected": False,
                "warning": "Harness connection failed after stdout detection and WS fallback",
            })

    return _text({
        "status": "launched",
        "pid": pid,
        "mode": mode,
        "test_harness": test_harness,
        "ws_connected": ws_connected,
    })


async def _godot_stop(args: dict) -> list[TextContent]:
    global injector
    force = args.get("force", False)
    if not manager.is_running:
        # Still cleanup injector if it exists
        if injector is not None:
            injector.cleanup()
            injector = None
        return _text({"status": "not_running"})

    # 1. Disconnect WebSocket
    if ws_client.is_connected:
        await ws_client.disconnect()

    # 2. Stop process
    runtime = manager.uptime
    exit_code = await manager.stop(force)

    # 3. Cleanup injector
    if injector is not None:
        injector.cleanup()
        injector = None

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

    # 1. Stop if already running (cleanup injection too)
    if manager.is_running:
        if ws_client.is_connected:
            await ws_client.disconnect()
        await manager.stop()

    # 2. Launch (no harness — this is Phase 1 error-check only)
    await manager.launch(mode, scene, [])

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
            "ws_connected": ws_client.is_connected,
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


async def _ensure_ws() -> None:
    """Ensure WebSocket is connected. Raises clear error if not."""
    if not ws_client.is_connected:
        if not manager.is_running:
            raise RuntimeError("Godot is not running. Call godot_launch first.")
        await ws_client.connect()


async def _ws_tool(method: str, params: dict | None = None) -> list[TextContent]:
    """Common pattern for Phase 2 WS tools."""
    try:
        await _ensure_ws()
        result = await ws_client.send_command(method, params)
        return _text({"status": "ok", **result})
    except (ConnectionError, RuntimeError) as e:
        return _text({"status": "error", "message": str(e)})


async def _godot_get_tree(args: dict) -> list[TextContent]:
    return await _ws_tool("get_tree_info")


async def _godot_get_node(args: dict) -> list[TextContent]:
    return await _ws_tool("get_node", {"path": args.get("path", "")})


async def _godot_get_property(args: dict) -> list[TextContent]:
    return await _ws_tool("get_property", {
        "path": args.get("path", ""),
        "property": args.get("property", ""),
    })


async def _godot_set_property(args: dict) -> list[TextContent]:
    return await _ws_tool("set_property", {
        "path": args.get("path", ""),
        "property": args.get("property", ""),
        "value": args.get("value"),
    })


async def _godot_call_method(args: dict) -> list[TextContent]:
    return await _ws_tool("call_method", {
        "path": args.get("path", ""),
        "method": args.get("method", ""),
        "args": args.get("args", []),
    })


async def _godot_get_group(args: dict) -> list[TextContent]:
    return await _ws_tool("get_nodes_in_group", {"group": args.get("group", "")})


async def _godot_ping(args: dict) -> list[TextContent]:
    return await _ws_tool("ping")


async def _godot_pause(args: dict) -> list[TextContent]:
    return await _ws_tool("pause")


async def _godot_resume(args: dict) -> list[TextContent]:
    return await _ws_tool("resume")


async def _godot_eval(args: dict) -> list[TextContent]:
    return await _ws_tool("eval", {"expression": args.get("expression", "")})


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
