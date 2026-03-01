#!/usr/bin/env python3
"""Runtime verifier for language-agnostic natural-language Godot MCP testing."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
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

    godot_path: Path | None = None
    if str(args.godot_path).strip() != "":
        godot_path = Path(str(args.godot_path)).expanduser().resolve()
        if not godot_path.is_file():
            raise ValueError(f"--godot-path does not exist: {godot_path}")

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


def build_summary(scenario_results: list[dict[str, Any]], strict: bool) -> dict[str, Any]:
    """Build summary counters and gate outcome."""
    pass_count = sum(1 for r in scenario_results if r.get("result") == "PASS")
    fail_count = sum(1 for r in scenario_results if r.get("result") == "FAIL")
    error_count = sum(1 for r in scenario_results if r.get("result") == "ERROR")
    skip_count = sum(1 for r in scenario_results if r.get("result") == "SKIP")
    undetermined_count = sum(1 for r in scenario_results if r.get("nl_result") == "UNDETERMINED")

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

        print(json.dumps({"output": str(output_path), "summary": report.get("summary", {})}, indent=2, ensure_ascii=False))
        return int(report.get("exit_code", 1))
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
