"""Unit tests for runtime verifier helper logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import verify_nl_runtime as vr


class TestVerifierConfig:
    """Configuration parsing and validation tests."""

    def test_resolve_config_defaults(self, tmp_path: Path) -> None:
        project = tmp_path / "game"
        project.mkdir(parents=True)
        (project / "project.godot").write_text("[gd_resource]\n", encoding="utf-8")

        args = vr.parse_args(["--project", str(project.resolve())])
        config = vr.resolve_config(args)

        assert config.project_path == project.resolve()
        assert config.strict is True
        assert config.timeout_seconds == 120
        assert config.scenario_pack.name == "core.json"
        assert len(config.server_command) >= 1

    def test_resolve_config_rejects_relative_project(self) -> None:
        args = vr.parse_args(["--project", "relative/path"])
        with pytest.raises(ValueError, match="absolute path"):
            vr.resolve_config(args)


class TestGateHelpers:
    """Strict gate and summary behavior tests."""

    def test_strict_gate_pass_only(self) -> None:
        assert vr.strict_gate_status("PASS", True)[0] == "PASS"
        assert vr.strict_gate_status("FAIL", True)[0] == "FAIL"
        assert vr.strict_gate_status("UNDETERMINED", True)[0] == "FAIL"
        assert vr.strict_gate_status("ERROR", True)[0] == "ERROR"

    def test_build_summary_counts(self) -> None:
        scenario_results = [
            {"result": "PASS"},
            {"result": "FAIL", "nl_result": "UNDETERMINED"},
            {"result": "ERROR", "nl_result": "ERROR"},
            {"result": "SKIP"},
        ]
        summary = vr.build_summary(scenario_results, strict=True)

        assert summary["total"] == 4
        assert summary["pass"] == 1
        assert summary["fail"] == 1
        assert summary["error"] == 1
        assert summary["skipped"] == 1
        assert summary["undetermined"] == 1
        assert summary["gate_passed"] is False
        assert summary["exit_code"] == 1


class TestReportWriter:
    """Report persistence tests."""

    def test_write_report_json(self, tmp_path: Path) -> None:
        out = tmp_path / "out" / "report.json"
        payload = {
            "summary": {"total": 0, "exit_code": 0},
            "contract_checks": [],
            "scenario_results": [],
            "artifacts_index": {},
            "exit_code": 0,
        }
        path = vr.write_report(payload, out)

        assert path == out
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["exit_code"] == 0
        assert "summary" in data
