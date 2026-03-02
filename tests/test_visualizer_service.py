"""Unit tests for visualizer service diagnostics projection."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.visualizer_runtime_mapper import RuntimeMapResult
from src.visualizer_schema import VisualizerRunArtifacts
from src.visualizer_service import VisualizerService


@pytest.mark.asyncio
async def test_map_project_exports_runtime_diagnostics_to_summary_and_meta(tmp_path) -> None:
    service = VisualizerService()
    diagnostics = [
        {"level": "error", "code": "script_parse_error", "message": "bad parse"},
        {"level": "warning", "code": "runtime_warning_generic", "message": "slow call"},
    ]

    with (
        patch.object(service._static_mapper, "map_project", return_value={"nodes": [], "edges": [], "summary": {}}),
        patch.object(service._runtime_mapper, "collect", new_callable=AsyncMock) as mock_collect,
        patch.object(service._renderer, "write_bundle") as mock_write_bundle,
        patch.object(service, "_write_i18n_file"),
        patch.object(service, "_enforce_retention"),
    ):
        mock_collect.return_value = RuntimeMapResult(
            runtime_source="fallback",
            nodes=[],
            edges=[],
            timeline={"current_tick": -1, "events": [], "event_count": 0},
            causality={"links": [], "confirmed_count": 0, "inferred_count": 0},
            raw_probe={},
            runtime_diagnostics=diagnostics,
        )
        mock_write_bundle.return_value = VisualizerRunArtifacts(
            run_id="run-1",
            root_dir=str(tmp_path),
            visualizer_dir=str(tmp_path / "visualizer"),
            map_path=str(tmp_path / "visualizer" / "map.json"),
            timeline_path=str(tmp_path / "visualizer" / "timeline.json"),
            causality_path=str(tmp_path / "visualizer" / "causality.json"),
            diff_path=str(tmp_path / "visualizer" / "diff.json"),
            meta_path=str(tmp_path / "visualizer" / "meta.json"),
            html_path=str(tmp_path / "visualizer" / "index.html"),
            js_path=str(tmp_path / "visualizer" / "app.js"),
            css_path=str(tmp_path / "visualizer" / "styles.css"),
            view_model_path=str(tmp_path / "visualizer" / "view_model.json"),
            offline_html_path=str(tmp_path / "visualizer" / "offline.html"),
        )

        result = await service.map_project(
            project_path=str(tmp_path),
            root="res://",
            include_runtime=True,
            include_addons=False,
            scenario="",
            baseline_run_id="",
            locale="ko",
            default_layer="cluster",
            focus_cluster="",
            ws_command=AsyncMock(return_value={"status": "ok"}),
            read_errors=lambda: {"errors": [], "warnings": []},
            open_browser=False,
        )

        assert result["status"] == "ok"
        assert result["summary"]["runtime_error_count"] == 1
        assert result["summary"]["runtime_warning_count"] == 1

        meta_payload = mock_write_bundle.call_args.kwargs["meta_payload"]
        assert meta_payload["runtime_diagnostics"] == diagnostics
        assert meta_payload["render_profile"] == "overview_first"
        assert meta_payload["renderer_backend"] == "webgl_sigma"
        assert meta_payload["renderer_error"] == ""
