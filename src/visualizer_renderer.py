"""Renderer for visualizer artifacts and static web bundle."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .visualizer_bundle import VisualizerBundleBuilder
from .visualizer_i18n import build_i18n_payload
from .visualizer_schema import VisualizerRunArtifacts
from .visualizer_view_model import VisualizerViewModelBuilder


class VisualizerRenderer:
    """Writes JSON artifacts and copies web assets from built dist bundle."""

    def __init__(self) -> None:
        self._view_model_builder = VisualizerViewModelBuilder()
        self._bundle_builder = VisualizerBundleBuilder()

    def write_bundle(
        self,
        *,
        project_path: str,
        run_id: str,
        map_payload: dict[str, Any],
        timeline_payload: dict[str, Any],
        causality_payload: dict[str, Any],
        diff_payload: dict[str, Any],
        meta_payload: dict[str, Any],
        locale: str,
        default_layer: str = "cluster",
        focus_cluster: str = "",
    ) -> VisualizerRunArtifacts:
        project = Path(project_path).resolve()
        run_dir = project / ".godot-test-mcp" / "runs" / run_id
        visualizer_dir = run_dir / "visualizer"
        visualizer_dir.mkdir(parents=True, exist_ok=True)

        map_path = visualizer_dir / "map.json"
        timeline_path = visualizer_dir / "timeline.json"
        causality_path = visualizer_dir / "causality.json"
        diff_path = visualizer_dir / "diff.json"
        meta_path = visualizer_dir / "meta.json"
        view_model_path = visualizer_dir / "view_model.json"
        bundle_path = visualizer_dir / "graph.bundle.json"
        html_path = visualizer_dir / "index.html"
        offline_html_path = visualizer_dir / "offline.html"

        meta = dict(meta_payload)
        meta.setdefault("locale", locale)
        meta.setdefault("ui_version", 2)
        meta.setdefault("render_mode", "webgl_sigma")
        meta.setdefault("renderer_backend", "webgl_sigma")
        meta.setdefault("renderer_error", "")
        meta.setdefault("scale_profile", "large")
        warnings = meta.get("warnings", [])
        if not isinstance(warnings, list):
            warnings = [str(warnings)]
        meta["warnings"] = [str(item) for item in warnings]

        view_model = self._view_model_builder.build(
            map_payload=map_payload,
            timeline_payload=timeline_payload,
            causality_payload=causality_payload,
            diff_payload=diff_payload,
            default_layer=default_layer,
            focus_cluster=focus_cluster,
        )
        bundle_payload = self._bundle_builder.build(
            map_payload=map_payload,
            view_model=view_model,
            timeline_payload=timeline_payload,
            causality_payload=causality_payload,
            diff_payload=diff_payload,
            meta_payload=meta,
        )

        map_path.write_text(json.dumps(map_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        timeline_path.write_text(json.dumps(timeline_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        causality_path.write_text(json.dumps(causality_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        diff_path.write_text(json.dumps(diff_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        view_model_path.write_text(json.dumps(view_model, indent=2, ensure_ascii=False), encoding="utf-8")
        bundle_path.write_text(json.dumps(bundle_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        inline_data = {
            "i18n": build_i18n_payload(),
            "meta": meta,
            "map": map_payload,
            "timeline": timeline_payload,
            "causality": causality_payload,
            "diff": diff_payload,
            "view_model": view_model,
            "graph_bundle": bundle_payload,
        }
        paths = self._copy_web_assets(visualizer_dir=visualizer_dir, inline_data=inline_data)
        offline_html_path.write_text(
            self._build_offline_html(
                map_payload=map_payload,
                timeline_payload=timeline_payload,
                causality_payload=causality_payload,
                diff_payload=diff_payload,
                meta_payload=meta,
                view_model=view_model,
                bundle_payload=bundle_payload,
            ),
            encoding="utf-8",
        )

        return VisualizerRunArtifacts(
            run_id=run_id,
            root_dir=str(run_dir),
            visualizer_dir=str(visualizer_dir),
            map_path=str(map_path),
            timeline_path=str(timeline_path),
            causality_path=str(causality_path),
            diff_path=str(diff_path),
            meta_path=str(meta_path),
            html_path=str(html_path),
            js_path=paths["js_path"],
            css_path=paths["css_path"],
            bundle_path=str(bundle_path),
            assets_dir=paths["assets_dir"],
            view_model_path=str(view_model_path),
            offline_html_path=str(offline_html_path),
        )

    def _copy_web_assets(self, *, visualizer_dir: Path, inline_data: dict[str, Any]) -> dict[str, str]:
        dist_dir = Path(__file__).resolve().parent / "visualizer_web_dist"
        legacy_dir = Path(__file__).resolve().parent / "visualizer_web"
        if dist_dir.is_dir() and (dist_dir / "index.html").is_file():
            return self._copy_dist_assets(visualizer_dir=visualizer_dir, dist_dir=dist_dir, inline_data=inline_data)
        return self._copy_legacy_assets(visualizer_dir=visualizer_dir, web_dir=legacy_dir, inline_data=inline_data)

    def _copy_dist_assets(self, *, visualizer_dir: Path, dist_dir: Path, inline_data: dict[str, Any]) -> dict[str, str]:
        for child in visualizer_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.name not in {
                "map.json",
                "timeline.json",
                "causality.json",
                "diff.json",
                "meta.json",
                "view_model.json",
                "graph.bundle.json",
                "offline.html",
            }:
                child.unlink(missing_ok=True)

        for src in dist_dir.iterdir():
            if src.name == "index.html":
                continue
            dst = visualizer_dir / src.name
            if src.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        inline_json = json.dumps(inline_data, ensure_ascii=False).replace("</", "<\\/")
        index_template = (dist_dir / "index.html").read_text(encoding="utf-8")
        index_html = index_template.replace("__VISUALIZER_INLINE_DATA__", inline_json)
        (visualizer_dir / "index.html").write_text(index_html, encoding="utf-8")

        js_path = ""
        css_path = ""
        manifest_path = visualizer_dir / ".vite" / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(manifest, dict):
                    first = manifest.get("index.html", next(iter(manifest.values()), {}))
                    if isinstance(first, dict):
                        file_value = str(first.get("file", ""))
                        if file_value:
                            js_path = str((visualizer_dir / file_value).resolve())
                        css_files = first.get("css", [])
                        if isinstance(css_files, list) and len(css_files) > 0:
                            css_path = str((visualizer_dir / str(css_files[0])).resolve())
            except Exception:
                js_path = ""
                css_path = ""

        if js_path == "":
            js_candidate = next(iter(sorted((visualizer_dir / "assets").glob("*.js"))), None)
            if js_candidate is not None:
                js_path = str(js_candidate.resolve())
        if css_path == "":
            css_candidate = next(iter(sorted((visualizer_dir / "assets").glob("*.css"))), None)
            if css_candidate is not None:
                css_path = str(css_candidate.resolve())

        if js_path == "":
            js_path = str((visualizer_dir / "app.js").resolve())
        if css_path == "":
            css_path = str((visualizer_dir / "styles.css").resolve())

        return {
            "js_path": js_path,
            "css_path": css_path,
            "assets_dir": str((visualizer_dir / "assets").resolve()),
        }

    def _copy_legacy_assets(self, *, visualizer_dir: Path, web_dir: Path, inline_data: dict[str, Any]) -> dict[str, str]:
        required = ["index.html", "app.js", "styles.css", "i18n.json"]
        missing = [name for name in required if not (web_dir / name).is_file()]
        if missing:
            raise ValueError(f"visualizer web assets missing: {missing}")

        for name in ["app.js", "styles.css", "i18n.json"]:
            src = web_dir / name
            dst = visualizer_dir / name
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        index_template = (web_dir / "index.html").read_text(encoding="utf-8")
        inline_json = json.dumps(inline_data, ensure_ascii=False).replace("</", "<\\/")
        index_html = index_template.replace("__VISUALIZER_INLINE_DATA__", inline_json)
        (visualizer_dir / "index.html").write_text(index_html, encoding="utf-8")

        assets_dir = visualizer_dir / "assets"
        assets_dir.mkdir(exist_ok=True)

        return {
            "js_path": str((visualizer_dir / "app.js").resolve()),
            "css_path": str((visualizer_dir / "styles.css").resolve()),
            "assets_dir": str(assets_dir.resolve()),
        }

    def _build_offline_html(
        self,
        *,
        map_payload: dict[str, Any],
        timeline_payload: dict[str, Any],
        causality_payload: dict[str, Any],
        diff_payload: dict[str, Any],
        meta_payload: dict[str, Any],
        view_model: dict[str, Any],
        bundle_payload: dict[str, Any],
    ) -> str:
        def dump(value: Any) -> str:
            return json.dumps(value, ensure_ascii=False, indent=2)

        return f"""<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Visualizer Offline Snapshot</title>
    <style>
      body {{ margin: 0; background: #0d1018; color: #eef1fb; font-family: 'JetBrains Mono', Menlo, Consolas, monospace; }}
      .top {{ padding: 16px; border-bottom: 1px solid #303b56; }}
      .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 12px; padding: 12px; }}
      .panel {{ background: #171d2d; border: 1px solid #394462; border-radius: 10px; padding: 12px; }}
      h1 {{ margin: 0 0 6px; font-size: 18px; }}
      h2 {{ margin: 0 0 8px; font-size: 14px; color: #a6b4da; }}
      pre {{ margin: 0; font-size: 11px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; max-height: 420px; overflow: auto; }}
      .badge {{ color: #a9ffd4; border: 1px solid #2f6f59; border-radius: 999px; padding: 2px 8px; font-size: 11px; }}
    </style>
  </head>
  <body>
    <div class=\"top\">
      <h1>Godot Visualizer Offline Snapshot <span class=\"badge\">no server</span></h1>
      <div>run_id: {meta_payload.get('run_id', '')}</div>
    </div>
    <div class=\"grid\">
      <section class=\"panel\"><h2>meta.json</h2><pre>{dump(meta_payload)}</pre></section>
      <section class=\"panel\"><h2>graph.bundle.json</h2><pre>{dump(bundle_payload)}</pre></section>
      <section class=\"panel\"><h2>view_model.json</h2><pre>{dump(view_model)}</pre></section>
      <section class=\"panel\"><h2>map.json</h2><pre>{dump(map_payload)}</pre></section>
      <section class=\"panel\"><h2>timeline.json</h2><pre>{dump(timeline_payload)}</pre></section>
      <section class=\"panel\"><h2>causality.json</h2><pre>{dump(causality_payload)}</pre></section>
      <section class=\"panel\"><h2>diff.json</h2><pre>{dump(diff_payload)}</pre></section>
    </div>
  </body>
</html>
"""
