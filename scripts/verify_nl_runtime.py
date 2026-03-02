#!/usr/bin/env python3
"""Runtime verifier for language-agnostic natural-language Godot MCP testing."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import statistics
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Protocol

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, TextContent


REQUIRED_NL_TOOLS: tuple[str, ...] = (
    "godot_get_nl_capabilities",
    "godot_compile_nl_test",
    "godot_run_nl_test",
)


class ToolClient(Protocol):
    """Minimal MCP tool client protocol used by runtime verifier."""

    async def list_tools(self) -> list[str]:
        """Return available tool names."""

    async def call_tool_json(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Invoke MCP tool and return decoded JSON response."""


@dataclass
class VerifierConfig:
    """Typed configuration for runtime verification execution."""

    project_path: Path
    godot_path: Path | None
    server_command: list[str]
    scenario_pack: Path
    output_path: Path
    timeout_seconds: int
    strict: bool
    repo_root: Path
    godot_path_source: str = "none"


@dataclass
class SessionToolClient:
    """Thin wrapper around mcp ClientSession."""

    session: ClientSession

    async def list_tools(self) -> list[str]:
        result = await self.session.list_tools()
        return [tool.name for tool in result.tools]

    async def call_tool_json(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = await self.session.call_tool(name=name, arguments=arguments or {})
        return decode_call_tool_result(result)


@asynccontextmanager
async def open_mcp_client(
    server_command: list[str],
    env: dict[str, str],
    cwd: Path,
    timeout_seconds: int,
) -> AsyncIterator[ToolClient]:
    """Open stdio MCP session and yield JSON-friendly tool client."""
    params = StdioServerParameters(
        command=server_command[0],
        args=server_command[1:],
        env=env,
        cwd=str(cwd),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            read_timeout_seconds=timedelta(seconds=timeout_seconds),
        ) as session:
            await session.initialize()
            yield SessionToolClient(session)


def decode_call_tool_result(result: CallToolResult) -> dict[str, Any]:
    """Decode server JSON payload from MCP CallToolResult."""
    if result.structuredContent is not None and isinstance(result.structuredContent, dict):
        decoded = dict(result.structuredContent)
    else:
        decoded: dict[str, Any] = {}
        for item in result.content:
            if isinstance(item, TextContent):
                try:
                    decoded = json.loads(item.text)
                except json.JSONDecodeError:
                    decoded = {"status": "error", "message": item.text}
                break

    if result.isError and decoded.get("status") != "error":
        decoded = {"status": "error", "message": decoded or "tool returned error"}
    return decoded


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser for CLI runner."""
    parser = argparse.ArgumentParser(description="Verify language-agnostic NL runtime behavior")
    parser.add_argument("--project", required=True, help="Absolute path to target Godot project")
    parser.add_argument("--godot-path", default="", help="Optional absolute path to Godot executable")
    parser.add_argument(
        "--server-command",
        default="",
        help="MCP server command. Example: './.venv/bin/python -m src.server'",
    )
    parser.add_argument(
        "--scenario-pack",
        default="",
        help="Scenario pack JSON path (defaults to verification/scenarios/core.json)",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output report path (defaults to <project>/.godot-test-mcp/verification/<timestamp>.json)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="Timeout seconds for each MCP read operation",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Strict gate: only PASS is treated as success",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI args for testing and main execution."""
    parser = build_parser()
    return parser.parse_args(argv)


def resolve_default_server_command(repo_root: Path) -> list[str]:
    """Resolve default server command for local development environment."""
    venv_python = repo_root / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return [str(venv_python), "-m", "src.server"]
    return ["godot-test-mcp"]


def resolve_godot_path(raw_godot_path: str) -> tuple[Path | None, str]:
    """Resolve Godot executable path for verifier preflight.

    Resolution order:
      1. --godot-path argument
      2. GODOT_PATH environment variable
      3. src.config._resolve_godot_path() auto-detection
    """
    value = str(raw_godot_path).strip()
    if value != "":
        explicit = Path(value).expanduser().resolve()
        if not explicit.is_file():
            raise ValueError(f"--godot-path does not exist: {explicit}")
        return explicit, "arg"

    env_value = os.environ.get("GODOT_PATH", "").strip()
    if env_value != "":
        env_path = Path(env_value).expanduser().resolve()
        if not env_path.is_file():
            raise ValueError(f"GODOT_PATH is set but does not exist: {env_path}")
        return env_path, "env"

    try:
        # Reuse server-side resolution policy so verifier and server stay aligned.
        from src.config import _resolve_godot_path  # pylint: disable=import-outside-toplevel

        detected = Path(_resolve_godot_path()).expanduser().resolve()
        if detected.is_file():
            return detected, "auto"
    except Exception:
        pass
    return None, "none"


def resolve_config(args: argparse.Namespace) -> VerifierConfig:
    """Resolve and validate full verifier configuration from args."""
    repo_root = Path(__file__).resolve().parent.parent
    project_path = Path(args.project).expanduser().resolve()

    if not Path(args.project).expanduser().is_absolute():
        raise ValueError("--project must be an absolute path")
    if not project_path.is_dir():
        raise ValueError(f"project path does not exist: {project_path}")
    if not (project_path / "project.godot").is_file():
        raise ValueError(f"project.godot not found in: {project_path}")

    godot_path, godot_path_source = resolve_godot_path(str(args.godot_path))

    if str(args.server_command).strip() != "":
        server_command = shlex.split(str(args.server_command))
    else:
        server_command = resolve_default_server_command(repo_root)
    if len(server_command) == 0:
        raise ValueError("server command is empty")

    if str(args.scenario_pack).strip() != "":
        scenario_pack = Path(str(args.scenario_pack)).expanduser().resolve()
    else:
        scenario_pack = (repo_root / "verification" / "scenarios" / "core.json").resolve()
    if not scenario_pack.is_file():
        raise ValueError(f"scenario pack not found: {scenario_pack}")

    if str(args.output).strip() != "":
        output_path = Path(str(args.output)).expanduser().resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_path = (project_path / ".godot-test-mcp" / "verification" / f"{timestamp}.json").resolve()

    timeout_seconds = int(args.timeout_seconds)
    if timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be > 0")

    return VerifierConfig(
        project_path=project_path,
        godot_path=godot_path,
        server_command=server_command,
        scenario_pack=scenario_pack,
        output_path=output_path,
        timeout_seconds=timeout_seconds,
        strict=bool(args.strict),
        repo_root=repo_root,
        godot_path_source=godot_path_source,
    )


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON document from disk."""
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return data


def strict_gate_status(nl_result: str, strict: bool) -> tuple[str, str]:
    """Convert tool-level result into scenario gate status."""
    normalized = str(nl_result).upper()
    if strict:
        if normalized == "PASS":
            return "PASS", "strict gate passed"
        if normalized == "ERROR":
            return "ERROR", "strict gate rejected ERROR"
        return "FAIL", f"strict gate rejected {normalized}"

    if normalized in {"PASS", "FAIL", "UNDETERMINED", "ERROR"}:
        if normalized == "ERROR":
            return "ERROR", "run returned ERROR"
        return "PASS", f"non-strict accepted {normalized}"
    return "ERROR", "invalid run result value"


def _normalize_nl_result(value: Any) -> str:
    """Normalize NL run result labels to uppercase string."""
    return str(value).strip().upper()


def _is_valid_nl_result(value: str) -> bool:
    """Return True when value is one of the canonical NL run results."""
    return value in {"PASS", "FAIL", "UNDETERMINED", "ERROR"}


async def resolve_capabilities_payload(
    *,
    client: ToolClient,
    tools: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read capabilities, bootstrapping a temporary launch if runtime is not active."""
    payload = await client.call_tool_json("godot_get_nl_capabilities", {})
    details: dict[str, Any] = {
        "initial_status": payload.get("status"),
        "bootstrap": "not_needed",
    }

    if payload.get("status") == "ok":
        return payload, details

    message = str(payload.get("message", ""))
    needs_runtime = ("not running" in message.lower()) or ("godot_launch" in message.lower())
    has_bootstrap_tools = ("godot_launch" in tools) and ("godot_stop" in tools)

    if not needs_runtime:
        details["bootstrap"] = "skipped"
        details["reason"] = "initial capabilities error is not runtime-state related"
        return payload, details
    if not has_bootstrap_tools:
        details["bootstrap"] = "skipped"
        details["reason"] = "bootstrap tools are unavailable"
        return payload, details

    details["bootstrap"] = "attempted"
    launch_payload = await client.call_tool_json(
        "godot_launch",
        {"mode": "headless", "scene": "", "extra_args": [], "test_harness": True},
    )
    details["launch_status"] = launch_payload.get("status")
    if launch_payload.get("status") != "launched":
        details["reason"] = "temporary launch failed"
        return payload, details

    refreshed_payload = await client.call_tool_json("godot_get_nl_capabilities", {})
    details["refreshed_status"] = refreshed_payload.get("status")

    stop_payload = await client.call_tool_json("godot_stop", {"force": False})
    details["stop_status"] = stop_payload.get("status")

    return refreshed_payload, details


def _to_int(value: Any) -> int | None:
    """Safely convert value to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    """Safely convert value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_tier(value: Any) -> int | None:
    """Normalize tier values like 0/'0'/'tier0'."""
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    if text.startswith("tier"):
        text = text.replace("tier", "", 1)
    return _to_int(text)


def _extract_discovery_events(probe: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract normalized discovery events from hook probe payload."""
    events: list[dict[str, Any]] = []
    raw_events = probe.get("discovery_events", [])
    if isinstance(raw_events, list):
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            events.append(
                {
                    "tech_id": str(item.get("tech_id", "")).strip(),
                    "tier": _normalize_tier(item.get("tier")),
                    "tick": _to_int(item.get("tick")),
                    "discoverer_id": str(item.get("discoverer_id", "")).strip(),
                    "discoverer_name": str(item.get("discoverer_name", "")).strip(),
                    "toast_shown": item.get("toast_shown"),
                }
            )

    raw_tiers = probe.get("tiers", {})
    if isinstance(raw_tiers, dict):
        for tier_key, tier_items in raw_tiers.items():
            tier = _normalize_tier(tier_key)
            if not isinstance(tier_items, list):
                continue
            for item in tier_items:
                if not isinstance(item, dict):
                    continue
                events.append(
                    {
                        "tech_id": str(item.get("tech_id", "")).strip(),
                        "tier": tier if item.get("tier") is None else _normalize_tier(item.get("tier")),
                        "tick": _to_int(item.get("discovered_tick", item.get("tick"))),
                        "discoverer_id": str(item.get("discoverer_id", "")).strip(),
                        "discoverer_name": str(item.get("discoverer_name", item.get("discoverer", ""))).strip(),
                        "toast_shown": item.get("toast_shown"),
                    }
                )

    normalized: list[dict[str, Any]] = []
    for item in events:
        tier = item.get("tier")
        tick = item.get("tick")
        if tier is None or tick is None:
            continue
        normalized.append(item)
    normalized.sort(key=lambda x: int(x.get("tick", 0)))
    return normalized


def _extract_openness_map(probe: dict[str, Any]) -> dict[str, float]:
    """Extract openness scores keyed by agent id and name."""
    mapping: dict[str, float] = {}
    candidate_lists = [
        probe.get("agent_traits", []),
        probe.get("agents", []),
    ]
    for candidate in candidate_lists:
        if not isinstance(candidate, list):
            continue
        for item in candidate:
            if not isinstance(item, dict):
                continue
            openness_value = item.get("openness")
            if openness_value is None and isinstance(item.get("traits"), dict):
                openness_value = item["traits"].get("openness")
            openness = _to_float(openness_value)
            if openness is None:
                continue
            agent_id = str(item.get("agent_id", item.get("id", ""))).strip()
            agent_name = str(item.get("name", "")).strip()
            if agent_id != "":
                mapping[agent_id] = openness
            if agent_name != "":
                mapping[agent_name] = openness
    return mapping


def _aggregate_gate_status(statuses: list[str]) -> str:
    """Aggregate check statuses into a single scenario result."""
    if any(status == "ERROR" for status in statuses):
        return "ERROR"
    if any(status == "FAIL" for status in statuses):
        return "FAIL"
    if any(status == "UNDETERMINED" for status in statuses):
        return "UNDETERMINED"
    return "PASS"


def _all_exist(paths: list[str]) -> tuple[list[str], list[str]]:
    """Split paths into existing/missing lists."""
    existing: list[str] = []
    missing: list[str] = []
    for path in paths:
        expanded = str(Path(path).expanduser())
        if Path(expanded).exists():
            existing.append(expanded)
        else:
            missing.append(expanded)
    return existing, missing


def _select_hook_target(
    hook_targets: list[dict[str, Any]],
    *,
    hook_method: str,
    hook_path: str,
) -> dict[str, str] | None:
    """Select one hook target from discovered capabilities."""
    if hook_path != "" and hook_method != "":
        for target in hook_targets:
            if not isinstance(target, dict):
                continue
            if str(target.get("path", "")) == hook_path and str(target.get("method", "")) == hook_method:
                return {"path": hook_path, "method": hook_method}
        return None

    if hook_method != "":
        for target in hook_targets:
            if not isinstance(target, dict):
                continue
            if str(target.get("method", "")) == hook_method:
                return {"path": str(target.get("path", "")), "method": hook_method}
        return None

    if hook_path != "":
        for target in hook_targets:
            if not isinstance(target, dict):
                continue
            if str(target.get("path", "")) == hook_path:
                return {"path": hook_path, "method": str(target.get("method", ""))}
        return None

    if len(hook_targets) == 0:
        return None
    first = hook_targets[0]
    if not isinstance(first, dict):
        return None
    return {"path": str(first.get("path", "")), "method": str(first.get("method", ""))}


def evaluate_tech_discovery_gate(
    probe: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate 7-point in-game tech discovery checks from hook probe payload."""
    current_tick = _to_int(probe.get("current_tick"))
    events = _extract_discovery_events(probe)
    openness_map = _extract_openness_map(probe)

    tier0_first_by_tick = int(scenario.get("tier0_first_by_tick", 30))
    tier0_all_by_tick = int(scenario.get("tier0_all_by_tick", 100))
    tier1_start_range = scenario.get("tier1_start_range", [50, 150])
    tier2_min_tick = int(scenario.get("tier2_min_tick", 200))
    required_tier0_tech_ids_raw = scenario.get("required_tier0_tech_ids", [])
    openness_sample_size = int(scenario.get("openness_sample_size", 3))
    openness_min_delta = float(scenario.get("openness_min_delta", 0.0))
    openness_tiers_raw = scenario.get("openness_tiers", [0, 1])

    required_tier0_tech_ids: list[str] = []
    if isinstance(required_tier0_tech_ids_raw, list):
        required_tier0_tech_ids = [
            str(item).strip()
            for item in required_tier0_tech_ids_raw
            if str(item).strip() != ""
        ]

    openness_tiers: list[int] = []
    if isinstance(openness_tiers_raw, list):
        openness_tiers = [
            int(tier)
            for tier in openness_tiers_raw
            if _to_int(tier) is not None
        ]
    if len(openness_tiers) == 0:
        openness_tiers = [0, 1]

    if not isinstance(tier1_start_range, list) or len(tier1_start_range) != 2:
        tier1_start_range = [50, 150]
    tier1_start_min = int(tier1_start_range[0])
    tier1_start_max = int(tier1_start_range[1])

    tier0_events = [event for event in events if event.get("tier") == 0]
    tier1_events = [event for event in events if event.get("tier") == 1]
    tier2_events = [event for event in events if event.get("tier") == 2]

    checks: list[dict[str, Any]] = []

    if len(tier0_events) > 0:
        first_tier0_tick = min(int(event["tick"]) for event in tier0_events)
        check_status = "PASS" if first_tier0_tick <= tier0_first_by_tick else "FAIL"
        checks.append(
            {
                "id": "tier0_first_by_tick",
                "status": check_status,
                "details": {
                    "first_tick": first_tier0_tick,
                    "threshold": tier0_first_by_tick,
                },
            }
        )
    else:
        status = "UNDETERMINED" if current_tick is None or current_tick < tier0_first_by_tick else "FAIL"
        checks.append(
            {
                "id": "tier0_first_by_tick",
                "status": status,
                "details": {
                    "reason": "no tier0 discoveries found",
                    "current_tick": current_tick,
                    "threshold": tier0_first_by_tick,
                },
            }
        )

    tier0_by_tech: dict[str, int] = {}
    for event in tier0_events:
        tech_id = str(event.get("tech_id", "")).strip()
        tick = int(event.get("tick", 0))
        if tech_id == "":
            continue
        if tech_id not in tier0_by_tech or tick < tier0_by_tech[tech_id]:
            tier0_by_tech[tech_id] = tick

    if len(required_tier0_tech_ids) > 0:
        missing = [tech_id for tech_id in required_tier0_tech_ids if tech_id not in tier0_by_tech]
        if len(missing) == 0:
            latest_required_tick = max(tier0_by_tech[tech_id] for tech_id in required_tier0_tech_ids)
            status = "PASS" if latest_required_tick <= tier0_all_by_tick else "FAIL"
            checks.append(
                {
                    "id": "tier0_all_by_tick",
                    "status": status,
                    "details": {
                        "latest_required_tick": latest_required_tick,
                        "threshold": tier0_all_by_tick,
                        "required_tech_ids": required_tier0_tech_ids,
                    },
                }
            )
        else:
            status = "UNDETERMINED" if current_tick is None or current_tick < tier0_all_by_tick else "FAIL"
            checks.append(
                {
                    "id": "tier0_all_by_tick",
                    "status": status,
                    "details": {
                        "missing": missing,
                        "threshold": tier0_all_by_tick,
                        "current_tick": current_tick,
                    },
                }
            )
    else:
        checks.append(
            {
                "id": "tier0_all_by_tick",
                "status": "UNDETERMINED",
                "details": {
                    "reason": "required_tier0_tech_ids is empty",
                },
            }
        )

    if len(tier0_events) == 0:
        checks.append(
            {
                "id": "tier0_toast_visible",
                "status": "UNDETERMINED",
                "details": {"reason": "no tier0 discoveries found"},
            }
        )
    else:
        toast_values = [event.get("toast_shown") for event in tier0_events]
        if any(value is False for value in toast_values):
            toast_status = "FAIL"
        elif all(value is True for value in toast_values):
            toast_status = "PASS"
        else:
            toast_status = "UNDETERMINED"
        checks.append(
            {
                "id": "tier0_toast_visible",
                "status": toast_status,
                "details": {
                    "sample": toast_values[:10],
                    "total_events": len(tier0_events),
                },
            }
        )

    if len(tier0_events) == 0:
        checks.append(
            {
                "id": "discoverer_name_recorded",
                "status": "UNDETERMINED",
                "details": {"reason": "no tier0 discoveries found"},
            }
        )
    else:
        names = [str(event.get("discoverer_name", "")).strip() for event in tier0_events]
        missing_count = sum(1 for name in names if name == "")
        status = "PASS" if missing_count == 0 else "FAIL"
        checks.append(
            {
                "id": "discoverer_name_recorded",
                "status": status,
                "details": {
                    "missing_name_count": missing_count,
                    "total_events": len(tier0_events),
                },
            }
        )

    if len(tier1_events) > 0:
        first_tier1_tick = min(int(event["tick"]) for event in tier1_events)
        in_range = tier1_start_min <= first_tier1_tick <= tier1_start_max
        checks.append(
            {
                "id": "tier1_start_range",
                "status": "PASS" if in_range else "FAIL",
                "details": {
                    "first_tick": first_tier1_tick,
                    "range": [tier1_start_min, tier1_start_max],
                },
            }
        )
    else:
        status = "UNDETERMINED" if current_tick is None or current_tick < tier1_start_max else "FAIL"
        checks.append(
            {
                "id": "tier1_start_range",
                "status": status,
                "details": {
                    "reason": "no tier1 discoveries found",
                    "current_tick": current_tick,
                    "range": [tier1_start_min, tier1_start_max],
                },
            }
        )

    if len(tier2_events) > 0:
        first_tier2_tick = min(int(event["tick"]) for event in tier2_events)
        checks.append(
            {
                "id": "tier2_after_min_tick",
                "status": "PASS" if first_tier2_tick >= tier2_min_tick else "FAIL",
                "details": {
                    "first_tick": first_tier2_tick,
                    "min_tick": tier2_min_tick,
                },
            }
        )
    else:
        checks.append(
            {
                "id": "tier2_after_min_tick",
                "status": "UNDETERMINED",
                "details": {
                    "reason": "no tier2 discoveries found",
                    "current_tick": current_tick,
                    "min_tick": tier2_min_tick,
                },
            }
        )

    trend_events = [event for event in events if event.get("tier") in openness_tiers]
    trend_events.sort(key=lambda item: int(item.get("tick", 0)))
    population_openness = list(openness_map.values())
    if len(population_openness) == 0 or len(trend_events) < max(1, openness_sample_size):
        checks.append(
            {
                "id": "openness_discovery_trend",
                "status": "UNDETERMINED",
                "details": {
                    "reason": "insufficient openness or discovery data",
                    "population_count": len(population_openness),
                    "discovery_count": len(trend_events),
                },
            }
        )
    else:
        sampled = trend_events[:max(1, openness_sample_size)]
        sampled_scores: list[float] = []
        for event in sampled:
            discoverer_id = str(event.get("discoverer_id", "")).strip()
            discoverer_name = str(event.get("discoverer_name", "")).strip()
            score = None
            if discoverer_id in openness_map:
                score = openness_map[discoverer_id]
            elif discoverer_name in openness_map:
                score = openness_map[discoverer_name]
            if score is None:
                continue
            sampled_scores.append(float(score))

        if len(sampled_scores) < max(1, openness_sample_size):
            checks.append(
                {
                    "id": "openness_discovery_trend",
                    "status": "UNDETERMINED",
                    "details": {
                        "reason": "missing openness for early discoverers",
                        "sampled_with_scores": len(sampled_scores),
                        "sample_size": openness_sample_size,
                    },
                }
            )
        else:
            early_avg = float(sum(sampled_scores) / len(sampled_scores))
            population_median = float(statistics.median(population_openness))
            passes = early_avg >= (population_median + openness_min_delta)
            checks.append(
                {
                    "id": "openness_discovery_trend",
                    "status": "PASS" if passes else "FAIL",
                    "details": {
                        "early_avg": round(early_avg, 4),
                        "population_median": round(population_median, 4),
                        "required_delta": openness_min_delta,
                        "tiers": openness_tiers,
                        "sample_size": openness_sample_size,
                    },
                }
            )

    aggregate = _aggregate_gate_status([str(check.get("status", "ERROR")) for check in checks])
    return {
        "result": aggregate,
        "summary": {
            "current_tick": current_tick,
            "event_count": len(events),
            "tier0_count": len(tier0_events),
            "tier1_count": len(tier1_events),
            "tier2_count": len(tier2_events),
        },
        "checks": checks,
    }


def build_summary(scenario_results: list[dict[str, Any]], strict: bool) -> dict[str, Any]:
    """Build summary counters and gate outcome."""
    pass_count = sum(1 for r in scenario_results if r.get("result") == "PASS")
    fail_count = sum(1 for r in scenario_results if r.get("result") == "FAIL")
    error_count = sum(1 for r in scenario_results if r.get("result") == "ERROR")
    skip_count = sum(1 for r in scenario_results if r.get("result") == "SKIP")
    undetermined_count = sum(
        1
        for r in scenario_results
        if (
            r.get("result") == "UNDETERMINED"
            or r.get("nl_result") == "UNDETERMINED"
            or r.get("raw_result") == "UNDETERMINED"
        )
    )

    gate_passed = fail_count == 0 and error_count == 0
    exit_code = 0 if gate_passed else 1

    return {
        "total": len(scenario_results),
        "pass": pass_count,
        "fail": fail_count,
        "error": error_count,
        "skipped": skip_count,
        "undetermined": undetermined_count,
        "strict": strict,
        "gate_passed": gate_passed,
        "exit_code": exit_code,
    }


async def execute_scenario_pack(
    *,
    client: ToolClient,
    scenario_pack: dict[str, Any],
    config: VerifierConfig,
    tools: list[str],
    capabilities_payload: dict[str, Any],
    runtime_context: dict[str, Any],
) -> list[dict[str, Any]]:
    """Execute scenarios in a pack and return per-scenario outcomes."""
    results: list[dict[str, Any]] = []
    scenarios = scenario_pack.get("scenarios", [])
    if not isinstance(scenarios, list):
        return [{"id": "invalid_pack", "kind": "meta", "result": "ERROR", "reason": "scenarios must be a list"}]

    for scenario in scenarios:
        if not isinstance(scenario, dict):
            results.append({"id": "invalid_scenario", "kind": "meta", "result": "ERROR", "reason": "scenario must be object"})
            continue

        scenario_id = str(scenario.get("id", "unknown"))
        kind = str(scenario.get("kind", "unknown"))
        base = {
            "id": scenario_id,
            "kind": kind,
            "result": "ERROR",
            "reason": "not executed",
            "details": {},
        }

        if kind == "contract_tools_present":
            required_tools = scenario.get("required_tools", [])
            missing = [name for name in required_tools if name not in tools]
            if len(missing) == 0:
                base["result"] = "PASS"
                base["reason"] = "all required tools found"
                base["details"] = {"required_tools": required_tools}
            else:
                base["result"] = "FAIL"
                base["reason"] = "missing required tools"
                base["details"] = {"missing_tools": missing}

        elif kind == "compile":
            spec_text = str(scenario.get("spec_text", "")).strip()
            payload = await client.call_tool_json(
                "godot_compile_nl_test",
                {"spec_text": spec_text, "scene": str(scenario.get("scene", ""))},
            )
            status = str(payload.get("compile_status", "FAILED"))
            allowed = scenario.get("allowed_compile_status", ["OK", "PARTIAL"])
            unsupported_min = int(scenario.get("expect_unsupported_min", 0))
            unsupported = payload.get("unsupported_phrases", [])
            has_enough_unsupported = isinstance(unsupported, list) and len(unsupported) >= unsupported_min
            compile_ok = status in allowed and has_enough_unsupported
            base["result"] = "PASS" if compile_ok else "FAIL"
            base["reason"] = "compile scenario passed" if compile_ok else "compile scenario failed"
            base["details"] = payload

        elif kind == "run":
            spec_text = str(scenario.get("spec_text", "")).strip()
            payload = await client.call_tool_json(
                "godot_run_nl_test",
                {
                    "spec_text": spec_text,
                    "scene": str(scenario.get("scene", "")),
                    "mode": str(scenario.get("mode", "auto")),
                    "timeout_seconds": min(config.timeout_seconds, int(scenario.get("timeout_seconds", config.timeout_seconds))),
                    "artifact_level": str(scenario.get("artifact_level", "full")),
                },
            )
            nl_result = _normalize_nl_result(payload.get("result", "ERROR"))
            accepted_nl_results_raw = scenario.get("accepted_nl_results")

            if isinstance(accepted_nl_results_raw, list) and len(accepted_nl_results_raw) > 0:
                accepted_nl_results = {
                    _normalize_nl_result(item)
                    for item in accepted_nl_results_raw
                }
                if not _is_valid_nl_result(nl_result):
                    scenario_status = "ERROR"
                    reason = "run returned invalid result enum"
                elif nl_result in accepted_nl_results:
                    scenario_status = "PASS"
                    reason = "run result accepted by scenario policy"
                else:
                    scenario_status = "FAIL"
                    reason = f"run result {nl_result} is outside accepted_nl_results"
            else:
                scenario_status, reason = strict_gate_status(nl_result, config.strict)

            base["result"] = scenario_status
            base["reason"] = reason
            base["nl_result"] = nl_result
            base["details"] = payload
            runtime_context["run_payloads"][scenario_id] = payload

            artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts", {}), dict) else {}
            runtime_context["artifacts_index"]["screenshots"].extend(artifacts.get("screenshots", []))
            runtime_context["artifacts_index"]["frames"].extend(artifacts.get("frames", []))
            runtime_context["artifacts_index"]["logs"].extend(artifacts.get("logs", []))
            video_info = artifacts.get("video", {})
            if isinstance(video_info, dict) and video_info.get("path"):
                runtime_context["artifacts_index"]["videos"].append(video_info.get("path"))

        elif kind == "artifact_presence":
            depends_on = str(scenario.get("depends_on", "run_no_error_smoke"))
            run_payload = runtime_context["run_payloads"].get(depends_on)
            if run_payload is None:
                base["result"] = "ERROR"
                base["reason"] = f"missing dependency payload: {depends_on}"
            else:
                artifacts = run_payload.get("artifacts", {}) if isinstance(run_payload.get("artifacts", {}), dict) else {}
                logs = artifacts.get("logs", []) if isinstance(artifacts.get("logs", []), list) else []
                existing_logs = [str(path) for path in logs if Path(str(path)).expanduser().exists()]
                has_report = any(Path(path).name == "report.json" for path in existing_logs)
                has_events = any(Path(path).name == "events.jsonl" for path in existing_logs)
                ok = has_report and has_events
                base["result"] = "PASS" if ok else "FAIL"
                base["reason"] = "artifact files present" if ok else "required artifact files missing"
                base["details"] = {
                    "logs": logs,
                    "existing_logs": existing_logs,
                    "has_report": has_report,
                    "has_events": has_events,
                }

        elif kind == "capabilities_hook_discovery":
            hook_targets = capabilities_payload.get("hook_targets", [])
            has_hooks = isinstance(hook_targets, list) and len(hook_targets) > 0
            base["result"] = "PASS" if has_hooks else "FAIL"
            base["reason"] = "hook targets discovered" if has_hooks else "no hook targets discovered"
            base["details"] = {"hook_targets": hook_targets}

        elif kind == "execute_test_mcp_smoke_hook":
            hook_targets = capabilities_payload.get("hook_targets", [])
            if not isinstance(hook_targets, list) or len(hook_targets) == 0:
                base["result"] = "SKIP"
                base["reason"] = "no hook targets available"
            else:
                first_success: dict[str, Any] | None = None
                errors: list[dict[str, Any]] = []
                for target in hook_targets:
                    if not isinstance(target, dict):
                        continue
                    path = str(target.get("path", ""))
                    method = str(target.get("method", ""))
                    payload = await client.call_tool_json(
                        "godot_call_method",
                        {"path": path, "method": method, "args": []},
                    )
                    if payload.get("status") == "ok":
                        first_success = {"path": path, "method": method, "payload": payload}
                        break
                    errors.append({"path": path, "method": method, "payload": payload})

                if first_success is None:
                    base["result"] = "FAIL"
                    base["reason"] = "all discovered hook calls failed"
                    base["details"] = {"errors": errors}
                else:
                    runtime_context["last_hook_call"] = first_success
                    base["result"] = "PASS"
                    base["reason"] = "hook call succeeded"
                    base["details"] = first_success

        elif kind == "assert_hook_return_schema":
            hook_call = runtime_context.get("last_hook_call")
            if hook_call is None:
                base["result"] = "SKIP"
                base["reason"] = "no successful hook call to validate"
            else:
                payload = hook_call.get("payload", {})
                ok = payload.get("status") == "ok" and "return_value" in payload
                base["result"] = "PASS" if ok else "FAIL"
                base["reason"] = "hook return schema valid" if ok else "hook return schema invalid"
                base["details"] = payload

        elif kind == "tech_discovery_gate":
            hook_targets_raw = capabilities_payload.get("hook_targets", [])
            hook_targets = hook_targets_raw if isinstance(hook_targets_raw, list) else []
            hook_method = str(scenario.get("hook_method", "test_mcp_get_tech_probe")).strip()
            hook_path = str(scenario.get("hook_path", "")).strip()

            target = _select_hook_target(
                hook_targets=[target for target in hook_targets if isinstance(target, dict)],
                hook_method=hook_method,
                hook_path=hook_path,
            )
            if target is None:
                base["result"] = "FAIL"
                base["reason"] = "requested hook target is not discoverable"
                base["details"] = {
                    "hook_method": hook_method,
                    "hook_path": hook_path,
                    "discovered_hook_targets": hook_targets,
                }
            else:
                payload = await client.call_tool_json(
                    "godot_call_method",
                    {
                        "path": target["path"],
                        "method": target["method"],
                        "args": scenario.get("hook_args", []),
                    },
                )
                if payload.get("status") != "ok":
                    base["result"] = "ERROR"
                    base["reason"] = "hook method invocation failed"
                    base["details"] = {
                        "target": target,
                        "payload": payload,
                    }
                else:
                    return_value = payload.get("return_value")
                    if not isinstance(return_value, dict):
                        base["result"] = "FAIL"
                        base["reason"] = "hook return_value must be an object"
                        base["details"] = {
                            "target": target,
                            "payload": payload,
                        }
                    else:
                        evaluated = evaluate_tech_discovery_gate(return_value, scenario)
                        raw_result = str(evaluated.get("result", "ERROR"))
                        scenario_result = raw_result
                        scenario_reason = "tech discovery gate completed"
                        if config.strict and raw_result == "UNDETERMINED":
                            scenario_result = "FAIL"
                            scenario_reason = "strict gate rejected UNDETERMINED"

                        base["result"] = scenario_result
                        base["reason"] = scenario_reason
                        base["raw_result"] = raw_result
                        base["details"] = {
                            "target": target,
                            "evaluation": evaluated,
                        }

        elif kind == "visualizer_contract":
            payload = await client.call_tool_json(
                "godot_visualizer_map_project",
                {
                    "project_path": str(config.project_path),
                    "root": str(scenario.get("root", "res://")),
                    "include_runtime": bool(scenario.get("include_runtime", True)),
                    "include_addons": bool(scenario.get("include_addons", False)),
                    "scenario": str(scenario.get("scenario", "")),
                    "baseline_run_id": str(scenario.get("baseline_run_id", "")),
                    "open": False,
                    "locale": str(scenario.get("locale", "ko")),
                    "default_layer": str(scenario.get("default_layer", "cluster")),
                    "focus_cluster": str(scenario.get("focus_cluster", "")),
                },
            )
            runtime_context["visualizer_map_payload"] = payload
            if payload.get("status") != "ok":
                base["result"] = "FAIL"
                base["reason"] = "visualizer map call failed"
                base["details"] = payload
            else:
                artifacts = payload.get("artifacts", {}) if isinstance(payload.get("artifacts"), dict) else {}
                required_paths = [
                    str(artifacts.get("map_path", "")),
                    str(artifacts.get("timeline_path", "")),
                    str(artifacts.get("causality_path", "")),
                    str(artifacts.get("diff_path", "")),
                    str(artifacts.get("meta_path", "")),
                    str(artifacts.get("view_model_path", "")),
                    str(artifacts.get("bundle_path", "")),
                    str(artifacts.get("html_path", "")),
                    str(artifacts.get("js_path", "")),
                    str(artifacts.get("css_path", "")),
                    str(artifacts.get("offline_html_path", "")),
                ]
                required_paths = [path for path in required_paths if path.strip() != ""]
                existing_paths, missing_paths = _all_exist(required_paths)
                map_json = {}
                timeline_json = {}
                causality_json = {}
                diff_json = {}
                meta_json = {}
                view_model_json = {}
                bundle_json = {}
                try:
                    if str(artifacts.get("map_path", "")).strip() != "":
                        map_json = load_json(Path(str(artifacts.get("map_path"))))
                    if str(artifacts.get("timeline_path", "")).strip() != "":
                        timeline_json = load_json(Path(str(artifacts.get("timeline_path"))))
                    if str(artifacts.get("causality_path", "")).strip() != "":
                        causality_json = load_json(Path(str(artifacts.get("causality_path"))))
                    if str(artifacts.get("diff_path", "")).strip() != "":
                        diff_json = load_json(Path(str(artifacts.get("diff_path"))))
                    if str(artifacts.get("meta_path", "")).strip() != "":
                        meta_json = load_json(Path(str(artifacts.get("meta_path"))))
                    if str(artifacts.get("view_model_path", "")).strip() != "":
                        view_model_json = load_json(Path(str(artifacts.get("view_model_path"))))
                    if str(artifacts.get("bundle_path", "")).strip() != "":
                        bundle_json = load_json(Path(str(artifacts.get("bundle_path"))))
                except Exception as exc:
                    base["result"] = "FAIL"
                    base["reason"] = f"visualizer artifact parse failed: {exc}"
                    base["details"] = payload
                    results.append(base)
                    continue

                assets_dir = str(artifacts.get("assets_dir", "")).strip()
                assets_ok = False
                if assets_dir != "":
                    assets_path = Path(assets_dir)
                    if assets_path.is_dir():
                        has_js = any(assets_path.glob("*.js"))
                        has_css = any(assets_path.glob("*.css"))
                        assets_ok = has_js and has_css

                schema_ok = (
                    "nodes" in map_json
                    and "edges" in map_json
                    and "events" in timeline_json
                    and "links" in causality_json
                    and "summary" in diff_json
                    and "runtime_source" in meta_json
                    and "renderer_backend" in meta_json
                    and "renderer_error" in meta_json
                    and "clusters" in view_model_json
                    and "nodesById" in view_model_json
                    and "layers" in view_model_json
                    and "ui_defaults" in view_model_json
                    and "cluster_layout_health" in view_model_json
                    and str(bundle_json.get("schema_version", "")).strip() != ""
                    and "nodes" in bundle_json
                    and "edges" in bundle_json
                    and "calls_edges" in bundle_json
                    and "clusters" in bundle_json
                    and "cluster_edges" in bundle_json
                    and "search_index" in bundle_json
                    and "layouts" in bundle_json
                    and (assets_ok or assets_dir == "")
                )
                base["result"] = "PASS" if (len(missing_paths) == 0 and schema_ok) else "FAIL"
                base["reason"] = "visualizer artifacts validated" if base["result"] == "PASS" else "visualizer contract failed"
                base["details"] = {
                    "run_id": payload.get("run_id"),
                    "existing_paths": existing_paths,
                    "missing_paths": missing_paths,
                    "schema_ok": schema_ok,
                    "assets_ok": assets_ok,
                    "assets_dir": assets_dir,
                }

        elif kind == "visualizer_diff_contract":
            dependency = runtime_context.get("visualizer_map_payload", {})
            run_id = str(scenario.get("run_id", "")).strip() or str(dependency.get("run_id", "")).strip()
            baseline_run_id = str(scenario.get("baseline_run_id", "")).strip() or str(dependency.get("baseline_run_id", "")).strip()
            if run_id == "":
                base["result"] = "FAIL"
                base["reason"] = "run_id missing for visualizer diff contract"
            else:
                payload = await client.call_tool_json(
                    "godot_visualizer_diff_runs",
                    {
                        "project_path": str(config.project_path),
                        "run_id": run_id,
                        "baseline_run_id": baseline_run_id,
                    },
                )
                if payload.get("status") != "ok":
                    base["result"] = "FAIL"
                    base["reason"] = "visualizer diff call failed"
                    base["details"] = payload
                else:
                    summary = payload.get("summary", {})
                    summary_ok = isinstance(summary, dict) and "added_node_count" in summary
                    base["result"] = "PASS" if summary_ok else "FAIL"
                    base["reason"] = "visualizer diff contract passed" if summary_ok else "visualizer diff summary missing keys"
                    base["details"] = payload

        elif kind == "visualizer_live_contract":
            dependency = runtime_context.get("visualizer_map_payload", {})
            run_id = str(scenario.get("run_id", "")).strip() or str(dependency.get("run_id", "")).strip()
            if run_id == "":
                base["result"] = "FAIL"
                base["reason"] = "run_id missing for visualizer live contract"
            else:
                start_payload = await client.call_tool_json(
                    "godot_visualizer_live_start",
                    {
                        "project_path": str(config.project_path),
                        "run_id": run_id,
                        "port": int(scenario.get("port", 0)),
                        "open": False,
                        "locale": str(scenario.get("locale", "ko")),
                    },
                )
                stop_payload = await client.call_tool_json("godot_visualizer_live_stop", {})
                started = start_payload.get("status") == "ok" and "url" in start_payload
                stopped = stop_payload.get("status") == "ok"
                base["result"] = "PASS" if (started and stopped) else "FAIL"
                base["reason"] = "visualizer live contract passed" if base["result"] == "PASS" else "visualizer live start/stop failed"
                base["details"] = {
                    "start": start_payload,
                    "stop": stop_payload,
                }

        else:
            base["result"] = "ERROR"
            base["reason"] = f"unsupported scenario kind: {kind}"

        results.append(base)

    return results


async def run_runtime_verification(
    config: VerifierConfig,
    client_factory: Callable[[list[str], dict[str, str], Path, int], Any] = open_mcp_client,
) -> dict[str, Any]:
    """Run full runtime verification and return report payload."""
    core_pack = load_json(config.scenario_pack)
    hooked_pack_path = config.scenario_pack.parent / "hooked.json"
    hooked_pack = load_json(hooked_pack_path) if hooked_pack_path.is_file() else None

    env = os.environ.copy()
    env["GODOT_PROJECT_PATH"] = str(config.project_path)
    if config.godot_path is not None:
        env["GODOT_PATH"] = str(config.godot_path)

    runtime_context: dict[str, Any] = {
        "run_payloads": {},
        "last_hook_call": None,
        "artifacts_index": {
            "screenshots": [],
            "frames": [],
            "videos": [],
            "logs": [],
        },
    }

    contract_checks: list[dict[str, Any]] = []
    scenario_results: list[dict[str, Any]] = []

    async with client_factory(config.server_command, env, config.repo_root, config.timeout_seconds) as client:
        tools = await client.list_tools()
        missing_required = [name for name in REQUIRED_NL_TOOLS if name not in tools]
        contract_checks.append(
            {
                "id": "required_nl_tools",
                "result": "PASS" if len(missing_required) == 0 else "FAIL",
                "details": {
                    "required": list(REQUIRED_NL_TOOLS),
                    "missing": missing_required,
                },
            }
        )

        capabilities_payload, capabilities_probe = await resolve_capabilities_payload(
            client=client,
            tools=tools,
        )
        fields_ok = all(
            key in capabilities_payload for key in ["hook_targets", "node_count", "groups_count"]
        ) and capabilities_payload.get("status") == "ok"
        contract_checks.append(
            {
                "id": "capabilities_shape",
                "result": "PASS" if fields_ok else "FAIL",
                "details": {
                    "status": capabilities_payload.get("status"),
                    "present_keys": sorted(capabilities_payload.keys()),
                    "required_keys": ["hook_targets", "node_count", "groups_count"],
                    "probe": capabilities_probe,
                },
            }
        )

        scenario_results.extend(
            await execute_scenario_pack(
                client=client,
                scenario_pack=core_pack,
                config=config,
                tools=tools,
                capabilities_payload=capabilities_payload,
                runtime_context=runtime_context,
            )
        )

        has_hooks = bool(capabilities_payload.get("has_test_hooks")) and len(
            capabilities_payload.get("hook_targets", [])
        ) > 0
        if hooked_pack is not None and has_hooks:
            scenario_results.extend(
                await execute_scenario_pack(
                    client=client,
                    scenario_pack=hooked_pack,
                    config=config,
                    tools=tools,
                    capabilities_payload=capabilities_payload,
                    runtime_context=runtime_context,
                )
            )
        elif hooked_pack is not None:
            scenario_results.append(
                {
                    "id": "hooked_pack",
                    "kind": "meta",
                    "result": "SKIP",
                    "reason": "optional hook scenarios skipped (no test_mcp hooks)",
                    "details": {},
                }
            )

    summary = build_summary(scenario_results, config.strict)

    contract_failed = any(check.get("result") != "PASS" for check in contract_checks)
    if contract_failed:
        summary["gate_passed"] = False
        summary["exit_code"] = 1

    report = {
        "summary": summary,
        "contract_checks": contract_checks,
        "scenario_results": scenario_results,
        "artifacts_index": runtime_context["artifacts_index"],
        "exit_code": summary["exit_code"],
    }
    return report


def write_report(report: dict[str, Any], output_path: Path) -> Path:
    """Write report JSON to disk and return final path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return output_path


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    try:
        args = parse_args(argv)
        config = resolve_config(args)
        report = asyncio.run(run_runtime_verification(config))
        output_path = write_report(report, config.output_path)

        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "summary": report.get("summary", {}),
                    "godot_path": str(config.godot_path) if config.godot_path is not None else "",
                    "godot_path_source": config.godot_path_source,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return int(report.get("exit_code", 1))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
