"""Integration-style tests for runtime verifier with mocked MCP client."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from scripts import verify_nl_runtime as vr


class FakeClient:
    """Simple fake MCP client returning deterministic responses."""

    def __init__(self, *, run_result: str, report_path: Path, events_path: Path) -> None:
        self._run_result = run_result
        self._report_path = report_path
        self._events_path = events_path

    async def list_tools(self) -> list[str]:
        return [
            "godot_get_nl_capabilities",
            "godot_compile_nl_test",
            "godot_run_nl_test",
            "godot_call_method",
            "godot_launch",
            "godot_stop",
        ]

    async def call_tool_json(self, name: str, arguments: dict | None = None) -> dict:
        _ = arguments
        if name == "godot_get_nl_capabilities":
            return {
                "status": "ok",
                "nodes": [],
                "groups": [],
                "node_count": 0,
                "groups_count": 0,
                "hook_methods": [],
                "hook_targets": [],
                "has_test_hooks": False,
            }
        if name == "godot_compile_nl_test":
            return {
                "compile_status": "OK",
                "confidence": 0.9,
                "unsupported_phrases": [],
                "compiled_plan": {"steps": []},
            }
        if name == "godot_run_nl_test":
            return {
                "result": self._run_result,
                "confidence": 0.8,
                "summary": "mock run",
                "artifacts": {
                    "screenshots": [],
                    "frames": [],
                    "video": {"available": False, "path": None, "reason": "mock"},
                    "logs": [str(self._events_path), str(self._report_path)],
                },
            }
        if name == "godot_launch":
            return {"status": "launched"}
        if name == "godot_stop":
            return {"status": "stopped"}
        if name == "godot_call_method":
            return {"status": "ok", "return_value": {"ok": True}}
        return {"status": "error", "message": f"unknown tool: {name}"}


class BootstrapCapabilitiesClient(FakeClient):
    """Fake MCP client that requires runtime launch before capabilities succeed."""

    def __init__(self, *, run_result: str, report_path: Path, events_path: Path) -> None:
        super().__init__(run_result=run_result, report_path=report_path, events_path=events_path)
        self._running = False

    async def call_tool_json(self, name: str, arguments: dict | None = None) -> dict:
        _ = arguments
        if name == "godot_get_nl_capabilities":
            if not self._running:
                return {"status": "error", "message": "Godot is not running. Call godot_launch first."}
            return {
                "status": "ok",
                "nodes": [],
                "groups": [],
                "node_count": 0,
                "groups_count": 0,
                "hook_methods": [],
                "hook_targets": [],
                "has_test_hooks": False,
            }
        if name == "godot_launch":
            self._running = True
            return {"status": "launched"}
        if name == "godot_stop":
            self._running = False
            return {"status": "stopped"}
        return await super().call_tool_json(name, arguments)


def _build_core_pack(path: Path) -> None:
    payload = {
        "name": "core",
        "version": 1,
        "scenarios": [
            {
                "id": "contract_tools_present",
                "kind": "contract_tools_present",
                "required_tools": [
                    "godot_get_nl_capabilities",
                    "godot_compile_nl_test",
                    "godot_run_nl_test",
                ],
            },
            {
                "id": "compile_basic",
                "kind": "compile",
                "spec_text": "set /root/Main.score to 10",
                "allowed_compile_status": ["OK", "PARTIAL"],
            },
            {
                "id": "run_no_error_smoke",
                "kind": "run",
                "spec_text": "no errors",
                "mode": "auto",
                "artifact_level": "minimal",
            },
            {
                "id": "artifact_presence",
                "kind": "artifact_presence",
                "depends_on": "run_no_error_smoke",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _build_schema_run_pack(path: Path) -> None:
    payload = {
        "name": "core",
        "version": 1,
        "scenarios": [
            {
                "id": "run_schema_smoke",
                "kind": "run",
                "spec_text": "no errors",
                "accepted_nl_results": ["PASS", "FAIL", "UNDETERMINED", "ERROR"],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _build_config(tmp_path: Path, scenario_pack: Path) -> vr.VerifierConfig:
    project = tmp_path / "game"
    project.mkdir(parents=True)
    (project / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")

    output = tmp_path / "reports" / "runtime.json"
    return vr.VerifierConfig(
        project_path=project.resolve(),
        godot_path=None,
        server_command=["python", "-m", "src.server"],
        scenario_pack=scenario_pack.resolve(),
        output_path=output.resolve(),
        timeout_seconds=30,
        strict=True,
        repo_root=Path(__file__).resolve().parent.parent,
    )


@pytest.mark.asyncio
async def test_runtime_verification_passes_when_run_returns_pass(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "core.json"
    _build_core_pack(scenario_pack)

    report_path = tmp_path / "run" / "report.json"
    events_path = tmp_path / "run" / "events.jsonl"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}", encoding="utf-8")
    events_path.write_text("{}\n", encoding="utf-8")

    fake_client = FakeClient(run_result="PASS", report_path=report_path, events_path=events_path)

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield fake_client

    config = _build_config(tmp_path, scenario_pack)
    report = await vr.run_runtime_verification(config, client_factory=fake_factory)

    assert report["exit_code"] == 0
    assert report["summary"]["gate_passed"] is True
    run_result = next(r for r in report["scenario_results"] if r["id"] == "run_no_error_smoke")
    assert run_result["result"] == "PASS"


@pytest.mark.asyncio
async def test_runtime_verification_fails_on_undetermined_in_strict_mode(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "core.json"
    _build_core_pack(scenario_pack)

    report_path = tmp_path / "run" / "report.json"
    events_path = tmp_path / "run" / "events.jsonl"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}", encoding="utf-8")
    events_path.write_text("{}\n", encoding="utf-8")

    fake_client = FakeClient(run_result="UNDETERMINED", report_path=report_path, events_path=events_path)

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield fake_client

    config = _build_config(tmp_path, scenario_pack)
    report = await vr.run_runtime_verification(config, client_factory=fake_factory)

    assert report["exit_code"] == 1
    assert report["summary"]["undetermined"] == 1
    run_result = next(r for r in report["scenario_results"] if r["id"] == "run_no_error_smoke")
    assert run_result["result"] == "FAIL"
    assert run_result["nl_result"] == "UNDETERMINED"


@pytest.mark.asyncio
async def test_capabilities_shape_bootstraps_runtime_when_needed(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "core.json"
    _build_core_pack(scenario_pack)

    report_path = tmp_path / "run" / "report.json"
    events_path = tmp_path / "run" / "events.jsonl"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}", encoding="utf-8")
    events_path.write_text("{}\n", encoding="utf-8")

    fake_client = BootstrapCapabilitiesClient(
        run_result="PASS",
        report_path=report_path,
        events_path=events_path,
    )

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield fake_client

    config = _build_config(tmp_path, scenario_pack)
    report = await vr.run_runtime_verification(config, client_factory=fake_factory)

    capabilities_check = next(c for c in report["contract_checks"] if c["id"] == "capabilities_shape")
    assert capabilities_check["result"] == "PASS"
    assert capabilities_check["details"]["probe"]["bootstrap"] == "attempted"
    assert capabilities_check["details"]["probe"]["refreshed_status"] == "ok"


@pytest.mark.asyncio
async def test_run_scenario_can_accept_non_pass_results_via_policy(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "schema_pack.json"
    _build_schema_run_pack(scenario_pack)

    report_path = tmp_path / "run" / "report.json"
    events_path = tmp_path / "run" / "events.jsonl"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}", encoding="utf-8")
    events_path.write_text("{}\n", encoding="utf-8")

    fake_client = FakeClient(run_result="FAIL", report_path=report_path, events_path=events_path)

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield fake_client

    config = _build_config(tmp_path, scenario_pack)
    report = await vr.run_runtime_verification(config, client_factory=fake_factory)

    run_result = next(r for r in report["scenario_results"] if r["id"] == "run_schema_smoke")
    assert run_result["result"] == "PASS"
    assert run_result["nl_result"] == "FAIL"
