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


class TechProbeClient(FakeClient):
    """Fake client that exposes one deterministic tech probe hook."""

    def __init__(self, *, run_result: str, report_path: Path, events_path: Path, probe: dict) -> None:
        super().__init__(run_result=run_result, report_path=report_path, events_path=events_path)
        self._probe = probe

    async def call_tool_json(self, name: str, arguments: dict | None = None) -> dict:
        if name == "godot_get_nl_capabilities":
            return {
                "status": "ok",
                "nodes": [],
                "groups": [],
                "node_count": 0,
                "groups_count": 0,
                "hook_methods": ["test_mcp_get_tech_probe"],
                "hook_targets": [{"path": "/root/Main", "method": "test_mcp_get_tech_probe"}],
                "has_test_hooks": True,
            }
        if name == "godot_call_method":
            args = arguments or {}
            if args.get("method") == "test_mcp_get_tech_probe":
                return {"status": "ok", "return_value": self._probe}
            return {"status": "error", "message": "unexpected hook"}
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


def _build_tech_discovery_pack(path: Path) -> None:
    payload = {
        "name": "tech_discovery",
        "version": 1,
        "scenarios": [
            {"id": "capabilities_hook_discovery", "kind": "capabilities_hook_discovery"},
            {
                "id": "tech_discovery_gate",
                "kind": "tech_discovery_gate",
                "hook_method": "test_mcp_get_tech_probe",
                "tier0_first_by_tick": 30,
                "tier0_all_by_tick": 100,
                "required_tier0_tech_ids": ["fire", "stone_tools", "basic_shelter", "foraging_knowledge"],
                "tier1_start_range": [50, 150],
                "tier2_min_tick": 200,
                "openness_tiers": [0, 1],
                "openness_sample_size": 3,
                "openness_min_delta": 0.0,
            },
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


@pytest.mark.asyncio
async def test_tech_discovery_gate_passes_with_valid_probe(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "tech_discovery.json"
    _build_tech_discovery_pack(scenario_pack)

    report_path = tmp_path / "run" / "report.json"
    events_path = tmp_path / "run" / "events.jsonl"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}", encoding="utf-8")
    events_path.write_text("{}\n", encoding="utf-8")

    probe = {
        "current_tick": 320,
        "discovery_events": [
            {"tech_id": "fire", "tier": 0, "tick": 10, "discoverer_id": "a1", "discoverer_name": "Ari", "toast_shown": True},
            {"tech_id": "stone_tools", "tier": 0, "tick": 20, "discoverer_id": "a2", "discoverer_name": "Bora", "toast_shown": True},
            {"tech_id": "basic_shelter", "tier": 0, "tick": 50, "discoverer_id": "a3", "discoverer_name": "Cora", "toast_shown": True},
            {"tech_id": "foraging_knowledge", "tier": 0, "tick": 80, "discoverer_id": "a1", "discoverer_name": "Ari", "toast_shown": True},
            {"tech_id": "bronze_working", "tier": 1, "tick": 120, "discoverer_id": "a1", "discoverer_name": "Ari", "toast_shown": True},
            {"tech_id": "agriculture", "tier": 2, "tick": 260, "discoverer_id": "a2", "discoverer_name": "Bora", "toast_shown": True},
        ],
        "agent_traits": [
            {"agent_id": "a1", "name": "Ari", "openness": 0.92},
            {"agent_id": "a2", "name": "Bora", "openness": 0.85},
            {"agent_id": "a3", "name": "Cora", "openness": 0.8},
            {"agent_id": "a4", "name": "Daro", "openness": 0.3},
            {"agent_id": "a5", "name": "Ena", "openness": 0.2},
        ],
    }
    fake_client = TechProbeClient(
        run_result="PASS",
        report_path=report_path,
        events_path=events_path,
        probe=probe,
    )

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield fake_client

    config = _build_config(tmp_path, scenario_pack)
    report = await vr.run_runtime_verification(config, client_factory=fake_factory)

    tech_result = next(r for r in report["scenario_results"] if r["id"] == "tech_discovery_gate")
    assert tech_result["result"] == "PASS"
    assert tech_result["raw_result"] == "PASS"
    assert report["exit_code"] == 0


@pytest.mark.asyncio
async def test_tech_discovery_gate_strict_rejects_undetermined(tmp_path: Path) -> None:
    scenario_pack = tmp_path / "tech_discovery.json"
    _build_tech_discovery_pack(scenario_pack)

    report_path = tmp_path / "run" / "report.json"
    events_path = tmp_path / "run" / "events.jsonl"
    report_path.parent.mkdir(parents=True)
    report_path.write_text("{}", encoding="utf-8")
    events_path.write_text("{}\n", encoding="utf-8")

    probe = {
        "current_tick": 110,
        "discovery_events": [
            {"tech_id": "fire", "tier": 0, "tick": 10, "discoverer_id": "a1", "discoverer_name": "Ari", "toast_shown": True},
            {"tech_id": "stone_tools", "tier": 0, "tick": 20, "discoverer_id": "a2", "discoverer_name": "Bora", "toast_shown": True},
            {"tech_id": "basic_shelter", "tier": 0, "tick": 50, "discoverer_id": "a3", "discoverer_name": "Cora", "toast_shown": True},
            {"tech_id": "foraging_knowledge", "tier": 0, "tick": 80, "discoverer_id": "a1", "discoverer_name": "Ari", "toast_shown": True},
            {"tech_id": "bronze_working", "tier": 1, "tick": 100, "discoverer_id": "a2", "discoverer_name": "Bora", "toast_shown": True},
        ],
        "agent_traits": [
            {"agent_id": "a1", "name": "Ari", "openness": 0.92},
            {"agent_id": "a2", "name": "Bora", "openness": 0.85},
            {"agent_id": "a3", "name": "Cora", "openness": 0.8},
        ],
    }
    fake_client = TechProbeClient(
        run_result="PASS",
        report_path=report_path,
        events_path=events_path,
        probe=probe,
    )

    @asynccontextmanager
    async def fake_factory(server_command, env, cwd, timeout):
        _ = (server_command, env, cwd, timeout)
        yield fake_client

    config = _build_config(tmp_path, scenario_pack)
    report = await vr.run_runtime_verification(config, client_factory=fake_factory)

    tech_result = next(r for r in report["scenario_results"] if r["id"] == "tech_discovery_gate")
    assert tech_result["raw_result"] == "UNDETERMINED"
    assert tech_result["result"] == "FAIL"
    assert report["summary"]["undetermined"] >= 1
