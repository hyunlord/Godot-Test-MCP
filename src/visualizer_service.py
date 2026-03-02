"""Coordinator service for project visualizer features."""

from __future__ import annotations

import json
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Awaitable, Callable

from .visualizer_diff import VisualizerDiffEngine
from .visualizer_edit_session import VisualizerEditSessionStore
from .visualizer_i18n import normalize_locale
from .visualizer_live_server import VisualizerLiveServer
from .visualizer_renderer import VisualizerRenderer
from .visualizer_runtime_mapper import VisualizerRuntimeMapper
from .visualizer_schema import VisualizerMap
from .visualizer_static_mapper import VisualizerStaticMapper


WSCallable = Callable[[str, dict[str, Any] | None], Awaitable[dict[str, Any]]]
ErrorCallable = Callable[[], dict[str, list[dict[str, Any]]]]


class VisualizerService:
    """High-level operations for map, diff, live server, and edit workflow."""

    def __init__(self) -> None:
        self._static_mapper = VisualizerStaticMapper()
        self._runtime_mapper = VisualizerRuntimeMapper()
        self._diff_engine = VisualizerDiffEngine()
        self._renderer = VisualizerRenderer()
        self._live_server = VisualizerLiveServer()
        self._edit_store = VisualizerEditSessionStore()

    async def map_project(
        self,
        *,
        project_path: str,
        root: str,
        include_runtime: bool,
        include_addons: bool,
        scenario: str,
        baseline_run_id: str,
        locale: str,
        default_layer: str,
        focus_cluster: str,
        ws_command: WSCallable,
        read_errors: ErrorCallable,
        open_browser: bool,
    ) -> dict[str, Any]:
        project = Path(project_path).resolve()
        run_id = self._new_run_id()
        locale_value = normalize_locale(locale)

        static = self._static_mapper.map_project(
            project_path=str(project),
            root=root,
            include_addons=include_addons,
        )

        runtime_source = "none"
        normalized_default_layer = default_layer if default_layer in {"cluster", "structural", "detail"} else "cluster"
        normalized_focus_cluster = focus_cluster.strip().lower()
        runtime_nodes: list[dict[str, Any]] = []
        runtime_edges: list[dict[str, Any]] = []
        timeline: dict[str, Any] = {"current_tick": -1, "events": [], "event_count": 0}
        causality: dict[str, Any] = {"links": [], "confirmed_count": 0, "inferred_count": 0}
        raw_probe: dict[str, Any] = {}
        runtime_diagnostics: list[dict[str, Any]] = []

        if include_runtime:
            runtime = await self._runtime_mapper.collect(
                ws_command=ws_command,
                read_errors=read_errors,
                preferred_hook_method="test_mcp_get_visualizer_probe",
            )
            runtime_source = runtime.runtime_source
            runtime_nodes = [item.to_dict() for item in runtime.nodes]
            runtime_edges = [item.to_dict() for item in runtime.edges]
            timeline = runtime.timeline
            causality = runtime.causality
            raw_probe = runtime.raw_probe
            runtime_diagnostics = runtime.runtime_diagnostics

        runtime_error_count = sum(
            1 for item in runtime_diagnostics if isinstance(item, dict) and str(item.get("level", "")) == "error"
        )
        runtime_warning_count = sum(
            1 for item in runtime_diagnostics if isinstance(item, dict) and str(item.get("level", "")) == "warning"
        )

        map_payload = VisualizerMap(
            run_id=run_id,
            project_path=str(project),
            runtime_source=runtime_source,
            locale=locale_value,
            nodes=self._from_dict_nodes(static.get("nodes", []) + runtime_nodes),
            edges=self._from_dict_edges(static.get("edges", []) + runtime_edges),
            summary={
                **static.get("summary", {}),
                "runtime_source": runtime_source,
                "runtime_node_count": len(runtime_nodes),
                "runtime_error_count": runtime_error_count,
                "runtime_warning_count": runtime_warning_count,
            },
        ).to_dict()
        map_payload["summary"] = {
            **map_payload.get("summary", {}),
            **self._extended_summary(map_payload),
        }
        readability_warnings = self._build_readability_warnings(map_payload=map_payload, default_layer=normalized_default_layer)

        selected_baseline = baseline_run_id.strip() or self._select_baseline_run_id(
            project_path=project,
            scenario=scenario,
        )

        if selected_baseline != "":
            diff_payload = self.diff_runs(
                project_path=str(project),
                run_id=run_id,
                baseline_run_id=selected_baseline,
                current_map=map_payload,
                current_timeline=timeline,
            )
        else:
            diff_payload = self._diff_engine.empty_diff(run_id=run_id, warning="baseline_unavailable")

        meta = {
            "version": 1,
            "run_id": run_id,
            "project_path": str(project),
            "generated_at": time.time(),
            "locale": locale_value,
            "scenario": scenario,
            "runtime_source": runtime_source,
            "baseline_run_id": selected_baseline,
            "result": "PASS",
            "raw_probe": raw_probe,
            "ui_version": 2,
            "render_mode": "webgl_sigma",
            "scale_profile": "large",
            "render_profile": "overview_first",
            "warnings": diff_payload.get("warnings", []),
            "runtime_diagnostics": runtime_diagnostics,
            "readability_warnings": readability_warnings,
        }

        artifacts = self._renderer.write_bundle(
            project_path=str(project),
            run_id=run_id,
            map_payload=map_payload,
            timeline_payload=timeline,
            causality_payload=causality,
            diff_payload=diff_payload,
            meta_payload=meta,
            locale=locale_value,
            default_layer=normalized_default_layer,
            focus_cluster=normalized_focus_cluster,
        )

        self._write_i18n_file(artifacts.visualizer_dir)
        self._enforce_retention(project, limit=30)

        if open_browser:
            webbrowser.open(Path(artifacts.html_path).resolve().as_uri())

        return {
            "status": "ok",
            "run_id": run_id,
            "runtime_source": runtime_source,
            "artifacts": artifacts.to_dict(),
            "summary": map_payload.get("summary", {}),
            "baseline_run_id": selected_baseline,
        }

    def _build_readability_warnings(self, *, map_payload: dict[str, Any], default_layer: str) -> list[str]:
        summary = map_payload.get("summary", {})
        function_count = int(summary.get("function_count", 0))
        node_count = int(summary.get("file_count", 0)) + int(summary.get("class_count", 0)) + function_count
        warnings: list[str] = []
        if default_layer != "cluster" and function_count >= 500:
            warnings.append("dense_function_graph")
        if node_count >= 1200:
            warnings.append("very_large_graph")
        return warnings

    async def live_start(
        self,
        *,
        run_id: str,
        project_path: str,
        port: int,
        open_browser: bool,
    ) -> dict[str, Any]:
        visualizer_dir = Path(project_path).resolve() / ".godot-test-mcp" / "runs" / run_id / "visualizer"
        if not visualizer_dir.exists():
            raise ValueError(f"visualizer assets not found for run_id={run_id}")

        result = await self._live_server.start(static_root=visualizer_dir, port=port)
        if open_browser and result.get("url"):
            webbrowser.open(str(result["url"]))
        await self._live_server.publish({"type": "live_started", "run_id": run_id})
        extra = {key: value for key, value in result.items() if key != "status"}
        return {
            "status": "ok",
            "run_id": run_id,
            "live_status": str(result.get("status", "")),
            **extra,
        }

    async def live_stop(self) -> dict[str, Any]:
        result = await self._live_server.stop()
        extra = {key: value for key, value in result.items() if key != "status"}
        return {
            "status": "ok",
            "live_status": str(result.get("status", "")),
            **extra,
        }

    async def publish_event(self, event: dict[str, Any]) -> None:
        """Publish one event to live WebSocket clients if running."""
        await self._live_server.publish(event)

    def get_run(self, *, project_path: str, run_id: str) -> dict[str, Any]:
        base = Path(project_path).resolve() / ".godot-test-mcp" / "runs" / run_id / "visualizer"
        if not base.exists():
            raise ValueError(f"run not found: {run_id}")

        def _load(name: str) -> dict[str, Any]:
            path = base / name
            if not path.is_file():
                return {}
            return json.loads(path.read_text(encoding="utf-8"))

        map_payload = _load("map.json")
        timeline_payload = _load("timeline.json")
        causality_payload = _load("causality.json")
        diff_payload = _load("diff.json")
        meta_payload = _load("meta.json")
        view_model_payload = _load("view_model.json")
        bundle_payload = _load("graph.bundle.json")

        return {
            "status": "ok",
            "run_id": run_id,
            "map": map_payload,
            "timeline": timeline_payload,
            "causality": causality_payload,
            "diff": diff_payload,
            "meta": meta_payload,
            "view_model": view_model_payload,
            "graph_bundle": bundle_payload,
        }

    def list_runs(self, *, project_path: str, scenario: str, limit: int = 30) -> dict[str, Any]:
        runs_dir = Path(project_path).resolve() / ".godot-test-mcp" / "runs"
        items: list[dict[str, Any]] = []
        if runs_dir.exists():
            for run_dir in runs_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                meta_path = run_dir / "visualizer" / "meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if scenario.strip() and str(meta.get("scenario", "")).strip() != scenario.strip():
                    continue
                items.append(
                    {
                        "run_id": str(meta.get("run_id", run_dir.name)),
                        "generated_at": float(meta.get("generated_at", 0)),
                        "scenario": str(meta.get("scenario", "")),
                        "result": str(meta.get("result", "")),
                        "runtime_source": str(meta.get("runtime_source", "")),
                        "visualizer_dir": str((run_dir / "visualizer").resolve()),
                    }
                )
        items.sort(key=lambda item: item.get("generated_at", 0), reverse=True)
        return {
            "status": "ok",
            "runs": items[: max(1, int(limit))],
            "total": len(items),
        }

    def diff_runs(
        self,
        *,
        project_path: str,
        run_id: str,
        baseline_run_id: str,
        current_map: dict[str, Any] | None = None,
        current_timeline: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = Path(project_path).resolve()
        run_dir = project / ".godot-test-mcp" / "runs" / run_id / "visualizer"
        baseline_dir = project / ".godot-test-mcp" / "runs" / baseline_run_id / "visualizer"

        if current_map is None:
            current_map = self._load_json(run_dir / "map.json")
        if current_timeline is None:
            current_timeline = self._load_json(run_dir / "timeline.json")

        if baseline_run_id.strip() == "":
            return self._diff_engine.empty_diff(run_id=run_id, warning="baseline_unavailable")
        if not baseline_dir.exists():
            return self._diff_engine.empty_diff(
                run_id=run_id,
                baseline_run_id=baseline_run_id,
                warning="baseline_not_found",
            )

        baseline_map = self._load_json(baseline_dir / "map.json")
        baseline_timeline = self._load_json(baseline_dir / "timeline.json")

        diff = self._diff_engine.build_diff(
            run_id=run_id,
            baseline_run_id=baseline_run_id,
            current_map=current_map,
            baseline_map=baseline_map,
            current_timeline=current_timeline,
            baseline_timeline=baseline_timeline,
        )

        if run_dir.exists():
            (run_dir / "diff.json").write_text(json.dumps(diff, indent=2, ensure_ascii=False), encoding="utf-8")

        return diff

    def _extended_summary(self, map_payload: dict[str, Any]) -> dict[str, Any]:
        nodes = map_payload.get("nodes", []) if isinstance(map_payload.get("nodes", []), list) else []
        edges = map_payload.get("edges", []) if isinstance(map_payload.get("edges", []), list) else []
        node_count = max(1, len(nodes))
        edge_count = len(edges)

        node_kind_counts: dict[str, int] = {}
        edge_type_counts: dict[str, int] = {}
        clusters: set[str] = set()

        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = str(node.get("kind", "unknown"))
            node_kind_counts[kind] = int(node_kind_counts.get(kind, 0)) + 1
            category = str(node.get("folder_category", "misc")).strip().lower() or "misc"
            clusters.add(category)

        for edge in edges:
            if not isinstance(edge, dict):
                continue
            edge_type = str(edge.get("edge_type", "unknown"))
            edge_type_counts[edge_type] = int(edge_type_counts.get(edge_type, 0)) + 1

        return {
            "cluster_count": len(clusters),
            "graph_density": float(edge_count) / float(node_count * max(1, node_count - 1)),
            "node_kind_counts": node_kind_counts,
            "edge_type_counts": edge_type_counts,
        }

    def edit_propose(
        self,
        *,
        project_path: str,
        file_path: str,
        operation: str,
        payload: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        return self._edit_store.propose(
            project_path=project_path,
            file_path=file_path,
            operation=operation,
            payload=payload,
            reason=reason,
        )

    def edit_apply(self, *, edit_session_id: str, approval_token: str) -> dict[str, Any]:
        return self._edit_store.apply(
            edit_session_id=edit_session_id,
            approval_token=approval_token,
        )

    def edit_cancel(self, *, edit_session_id: str) -> dict[str, Any]:
        return self._edit_store.cancel(edit_session_id=edit_session_id)

    def _new_run_id(self) -> str:
        return f"{time.strftime('%Y%m%d-%H%M%S', time.localtime())}-{uuid.uuid4().hex[:8]}"

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            raise ValueError(f"required file missing: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _from_dict_nodes(self, items: list[dict[str, Any]]) -> list:
        from .visualizer_schema import VisualizerNode

        nodes = []
        for item in items:
            if not isinstance(item, dict):
                continue
            nodes.append(
                VisualizerNode(
                    id=str(item.get("id", "")),
                    kind=str(item.get("kind", "")),
                    label=str(item.get("label", "")),
                    path=str(item.get("path", "")),
                    language=str(item.get("language", "")),
                    folder_category=str(item.get("folder_category", "")),
                    loc=int(item.get("loc", 0)),
                    metadata=item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {},
                )
            )
        return nodes

    def _from_dict_edges(self, items: list[dict[str, Any]]) -> list:
        from .visualizer_schema import VisualizerEdge

        edges = []
        for item in items:
            if not isinstance(item, dict):
                continue
            edges.append(
                VisualizerEdge(
                    source=str(item.get("source", "")),
                    target=str(item.get("target", "")),
                    edge_type=str(item.get("edge_type", "")),
                    confidence=float(item.get("confidence", 0.0)),
                    inferred=bool(item.get("inferred", False)),
                    metadata=item.get("metadata", {}) if isinstance(item.get("metadata", {}), dict) else {},
                )
            )
        return edges

    def _write_i18n_file(self, visualizer_dir: str) -> None:
        path = Path(visualizer_dir) / "i18n.json"
        from .visualizer_i18n import build_i18n_payload

        path.write_text(json.dumps(build_i18n_payload(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _select_baseline_run_id(self, *, project_path: Path, scenario: str) -> str:
        listed = self.list_runs(project_path=str(project_path), scenario=scenario, limit=200)
        for item in listed.get("runs", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("result", "")) == "PASS":
                return str(item.get("run_id", ""))
        return ""

    def _enforce_retention(self, project: Path, limit: int) -> None:
        runs_dir = project / ".godot-test-mcp" / "runs"
        if not runs_dir.exists():
            return
        runs: list[tuple[float, Path]] = []
        for run_dir in runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            meta = run_dir / "visualizer" / "meta.json"
            if not meta.exists():
                continue
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                ts = float(data.get("generated_at", 0))
            except Exception:
                ts = 0.0
            runs.append((ts, run_dir))

        runs.sort(key=lambda item: item[0], reverse=True)
        for _, run_dir in runs[limit:]:
            visualizer_dir = run_dir / "visualizer"
            if not visualizer_dir.exists():
                continue
            try:
                # Retention is scoped to visualizer artifacts only.
                for child in sorted(visualizer_dir.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                visualizer_dir.rmdir()
                # Keep unrelated run artifacts intact when present.
                if not any(run_dir.iterdir()):
                    run_dir.rmdir()
            except Exception:
                continue
