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
            "Launch Godot game process with optional test harness injection.\n\n"
            "Example 1 — Launch headless with test harness:\n"
            "  mode: 'headless', test_harness: true\n"
            "  → {status: 'launched', pid: 1234, ws_connected: true}\n\n"
            "Example 2 — Launch with GUI for visual testing:\n"
            "  mode: 'windowed', scene: 'res://test_scene.tscn'\n"
            "  → {status: 'launched', pid: 1235, ws_connected: true}\n\n"
            "After launch, use godot_inspect to discover the game's API. "
            "If the game needs setup (e.g., spawning entities), use godot_call_method.\n"
            "USE THIS as the first step in any test session."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["headless", "windowed", "editor"],
                    "default": "headless",
                    "description": "Run mode: headless (no GUI, fastest), windowed (GUI), or editor",
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
                    "description": "Inject WebSocket test harness for interactive tools (godot_eval, godot_inspect, etc.)",
                },
            },
        },
    ),
    Tool(
        name="godot_stop",
        description=(
            "Stop the running Godot process and clean up test harness.\n\n"
            "Example — Graceful stop:\n"
            "  force: false → {status: 'stopped', exit_code: 0, runtime_seconds: 12.5}\n\n"
            "USE THIS when done testing. Always call this to ensure harness cleanup."
        ),
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
        description=(
            "Get captured errors and/or warnings from the running or last-run Godot process.\n\n"
            "Example — Get all errors:\n"
            "  level: 'error'\n"
            "  → {error_count: 2, errors: [{level: 'error', category: 'SCRIPT_ERROR', "
            "source: 'res://main.gd', line: 42, message: '...'}]}\n\n"
            "USE THIS after godot_run_and_check or during a running session to check for issues."
        ),
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
        description=(
            "Get raw stdout/stderr output from the Godot process.\n\n"
            "Example — Get last 50 lines:\n"
            "  tail_lines: 50\n"
            "  → {line_count: 50, output: '...'}\n\n"
            "USE THIS for debugging when errors don't capture what you need. "
            "Supports regex filtering with filter_pattern."
        ),
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
            "This is the primary tool for automated verification after code changes.\n\n"
            "Example — Quick 10-second check:\n"
            "  seconds: 10, mode: 'headless'\n"
            "  → {result: 'PASS', runtime_seconds: 10.0, error_count: 0, "
            "summary: 'Game ran for 10.0s with no errors.'}\n\n"
            "USE THIS for quick pass/fail verification. Does NOT inject test harness. "
            "USE godot_launch with test_harness=true when you need interactive tools."
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
            "Equivalent to a quick parse-check gate.\n\n"
            "Example:\n"
            "  → {result: 'PASS', exit_code: 0, error_count: 0}\n\n"
            "USE THIS as a fast pre-check before running the game. "
            "Catches syntax errors and resource issues without running the game."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_get_status",
        description=(
            "Get current Godot process status.\n\n"
            "Example:\n"
            "  → {status: 'running', pid: 1234, uptime_seconds: 30.5, ws_connected: true}\n\n"
            "USE THIS to check if Godot is running before calling other tools."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    # ── Phase 2 tools ────────────────────────────────────────────────
    Tool(
        name="godot_get_tree",
        description=(
            "Get scene tree overview: root children, node count, current scene, paused state. "
            "Requires Godot running with test_harness=true.\n\n"
            "Example:\n"
            "  → {root_children: [{name: 'Main', class: 'Node2D'}, ...], "
            "node_count: 150, current_scene: 'Main', paused: false}\n\n"
            "START HERE to see what's in the scene. Then use godot_inspect on specific nodes. "
            "USE THIS as the first exploration step after godot_launch."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_get_node",
        description=(
            "Get node info + all script variables at a given path. Requires test harness.\n\n"
            "Example:\n"
            "  path: '/root/Main'\n"
            "  → {path: '/root/Main', class: 'Node2D', name: 'Main', "
            "properties: {score: 100, lives: 3}}\n\n"
            "USE THIS to read all script variables on a specific node. "
            "USE godot_inspect for deeper introspection (methods, signals, children)."
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
        description=(
            "Get a single property value from a node. Requires test harness.\n\n"
            "Example:\n"
            "  path: '/root/Main', property: 'score'\n"
            "  → {path: '/root/Main', property: 'score', value: 100}\n\n"
            "USE THIS for reading one specific property. "
            "USE godot_batch to read multiple values at once (faster)."
        ),
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
        description=(
            "Set a property on a node. Requires test harness.\n\n"
            "Example:\n"
            "  path: '/root/Main', property: 'score', value: 999\n"
            "  → {ok: true}\n\n"
            "USE THIS to modify game state for testing. "
            "USE godot_call_method to trigger behavior changes instead."
        ),
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
        description=(
            "Call a method on a node and return the result. Requires test harness.\n\n"
            "Example:\n"
            "  path: '/root/Main', method: 'reset_game', args: []\n"
            "  → {return_value: null}\n\n"
            "USE THIS to trigger game actions (reset, spawn, etc.). "
            "USE godot_run_script when you need to chain multiple calls with logic."
        ),
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
        description=(
            "Get all nodes in a group. Requires test harness.\n\n"
            "Example:\n"
            "  group: 'enemies'\n"
            "  → {group: 'enemies', count: 5, nodes: [{name: 'Goblin', path: '/root/Main/Goblin', class: 'CharacterBody2D'}, ...]}\n\n"
            "USE THIS to find nodes by group membership. "
            "USE godot_get_tree for overall scene structure."
        ),
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
        description=(
            "Health check — verify WebSocket connection to Godot test harness is alive.\n\n"
            "Example:\n"
            "  → {pong: true}\n\n"
            "USE THIS to verify connection before running commands."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_pause",
        description=(
            "Pause the game simulation (get_tree().paused = true). Requires test harness.\n\n"
            "Example:\n"
            "  → {paused: true}\n\n"
            "USE THIS before inspecting or modifying game state to prevent changes during inspection."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_resume",
        description=(
            "Resume the game simulation (get_tree().paused = false). Requires test harness.\n\n"
            "Example:\n"
            "  → {paused: false}\n\n"
            "USE THIS after pausing to let the game continue running."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="godot_eval",
        description=(
            "Evaluate a single GDScript expression in the running game. Requires test harness. "
            "Single expression only — no var, no loops, no multi-line.\n\n"
            "Example 1 — Read a property:\n"
            "  expression: \"get_node('Main').score\"\n"
            "  → {value: 100}\n\n"
            "Example 2 — Call a method:\n"
            "  expression: \"get_node('Main').entity_manager.get_alive_count()\"\n"
            "  → {value: 20}\n\n"
            "USE THIS for simple single-expression queries.\n"
            "USE godot_run_script for multi-line code (var, loops, conditionals).\n"
            "USE godot_batch to evaluate multiple expressions at once (10-20x faster)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "GDScript expression to evaluate. Executed in scene root context. "
                        "Example: get_node('Main').score"
                    ),
                },
            },
            "required": ["expression"],
        },
    ),
    # ── Phase 3 tools ────────────────────────────────────────────────
    Tool(
        name="godot_inspect",
        description=(
            "Discover methods, properties, signals of any object in the running game. "
            "Returns the object's full schema so you can plan further queries.\n\n"
            "Example 1 — Inspect the entity manager:\n"
            "  expression: \"get_tree().root.get_node('Main').entity_manager\"\n"
            "  → {class: 'RefCounted', script: 'res://entity_manager.gd', "
            "methods: [{name: 'get_alive_count', args: [], return_type: 'int'}, ...], "
            "properties: {_entities: {type: 'Dictionary', value: '<size:20>'}}, ...}\n\n"
            "Example 2 — Inspect a specific entity:\n"
            "  expression: \"get_tree().root.get_node('Main').entity_manager.get_alive_entities()[0]\"\n"
            "  → {class: 'RefCounted', properties: {personality: ..., hunger: ...}, methods: [...]}\n\n"
            "USE THIS when you don't know what methods/properties an object has.\n"
            "USE godot_eval or godot_batch when you already know the exact expression.\n"
            "USE godot_run_script when you need loops, variables, or complex logic."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "GDScript expression that evaluates to the object to inspect. "
                        "Executed in context of scene root. "
                        "Example: \"get_tree().root.get_node('Main').entity_manager\""
                    ),
                },
                "depth": {
                    "type": "integer",
                    "default": 0,
                    "description": (
                        "For Node objects: 0 = list child names only, "
                        "1 = inspect children too, 2 = grandchildren. Max 3."
                    ),
                },
            },
            "required": ["expression"],
        },
    ),
    Tool(
        name="godot_run_script",
        description=(
            "Execute multi-line GDScript code in the running game. Supports var declarations, "
            "loops, conditionals — anything GDScript can do. Returns the value from 'return' statement.\n\n"
            "Example 1 — Collect all agent health values:\n"
            "  code: \"var em = get_tree().root.get_node('Main').entity_manager\\n"
            "var results = []\\n"
            "for e in em.get_alive_entities():\\n"
            "\\tresults.append({'id': e.id, 'health': e.health})\\n"
            "return results\"\n"
            "  → {value: [{id: 0, health: 0.85}, {id: 1, health: 0.92}, ...]}\n\n"
            "Example 2 — Check simulation state:\n"
            "  code: \"var sim = get_tree().root.get_node('Main').sim_engine\\n"
            "return {'tick': sim.current_tick, 'paused': sim.is_paused}\"\n"
            "  → {value: {tick: 1500, paused: false}}\n\n"
            "USE THIS when you need loops, variables, or multi-step logic.\n"
            "USE godot_eval for simple single-expression queries.\n"
            "USE godot_batch to evaluate multiple simple expressions at once.\n"
            "NOTE: OS, FileAccess, DirAccess are blocked for security."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Multi-line GDScript code. Use \\n for newlines, \\t for indentation. "
                        "get_tree() is available. Must use 'return <value>' to return data. "
                        "OS/File access is blocked."
                    ),
                },
            },
            "required": ["code"],
        },
    ),
    Tool(
        name="godot_batch",
        description=(
            "Evaluate multiple GDScript expressions in a single round-trip. "
            "Each expression is independent (like calling godot_eval N times but 10-20x faster).\n\n"
            "Example — Check 3 values at once:\n"
            "  expressions: [\n"
            "    \"get_node('Main').entity_manager.get_alive_count()\",\n"
            "    \"get_node('Main').sim_engine.current_tick\",\n"
            "    \"get_node('Main').sim_engine.is_paused\"\n"
            "  ]\n"
            "  → [{expr: '...alive_count()', status: 'ok', value: 20},\n"
            "      {expr: '...current_tick', status: 'ok', value: 1500},\n"
            "      {expr: '...is_paused', status: 'ok', value: false}]\n\n"
            "USE THIS when checking multiple simple values (e.g., verifying 5 properties).\n"
            "USE godot_eval for a single expression.\n"
            "USE godot_run_script when expressions depend on each other (need variables)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "expressions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Array of GDScript expressions to evaluate. "
                        "Each runs independently in scene root context. "
                        "Results returned in same order."
                    ),
                },
            },
            "required": ["expressions"],
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
    # Phase 3 tools
    elif name == "godot_inspect":
        return await _godot_inspect(arguments)
    elif name == "godot_run_script":
        return await _godot_run_script(arguments)
    elif name == "godot_batch":
        return await _godot_batch(arguments)
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
            port = await manager.wait_for_harness(timeout=60.0)
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


# ── Phase 3 tool implementations ─────────────────────────────────────────


async def _godot_inspect(args: dict) -> list[TextContent]:
    params = {"expression": args.get("expression", "")}
    depth = args.get("depth", 0)
    if depth:
        params["depth"] = depth
    return await _ws_tool("inspect", params)


async def _godot_run_script(args: dict) -> list[TextContent]:
    return await _ws_tool("run_script", {"code": args.get("code", "")})


async def _godot_batch(args: dict) -> list[TextContent]:
    return await _ws_tool("batch", {"expressions": args.get("expressions", [])})


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
