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

server = Server("godot-test-mcp")
manager: GodotProcessManager


def _text(data: dict) -> list[TextContent]:
    """Convert a dict to MCP TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2))]


# ── Tool definitions ─────────────────────────────────────────────────────

TOOLS = [
    Tool(
        name="godot_launch",
        description=(
            "Launch Godot game process. "
            "mode: 'headless' (no GUI), 'windowed' (GUI), or 'editor'. "
            "scene: scene path to run (empty = main scene). "
            "extra_args: additional Godot CLI arguments."
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
]


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
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
    else:
        return _text({"error": f"Unknown tool: {name}"})


# ── Tool implementations ─────────────────────────────────────────────────


async def _godot_launch(args: dict) -> list[TextContent]:
    mode = args.get("mode", "headless")
    scene = args.get("scene", "")
    extra_args = args.get("extra_args", [])
    pid = await manager.launch(mode, scene, extra_args)
    return _text({"status": "launched", "pid": pid, "mode": mode})


async def _godot_stop(args: dict) -> list[TextContent]:
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

    # 1. Stop if already running
    if manager.is_running:
        await manager.stop()

    # 2. Launch
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
        })
    elif manager._process is None:
        return _text({"status": "stopped"})
    else:
        return _text({
            "status": "crashed" if (manager.exit_code or 0) != 0 else "stopped",
            "exit_code": manager.exit_code,
            "error_count": len(manager.get_errors()),
        })


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


if __name__ == "__main__":
    asyncio.run(main())
