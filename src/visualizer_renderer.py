"""Renderer for visualizer artifacts and static web bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .visualizer_i18n import build_i18n_payload
from .visualizer_schema import VisualizerRunArtifacts
from .visualizer_view_model import VisualizerViewModelBuilder


class VisualizerRenderer:
    """Writes JSON artifacts and copies web assets from src/visualizer_web."""

    def __init__(self) -> None:
        self._view_model_builder = VisualizerViewModelBuilder()

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
        html_path = visualizer_dir / "index.html"
        js_path = visualizer_dir / "app.js"
        css_path = visualizer_dir / "styles.css"
        offline_html_path = visualizer_dir / "offline.html"

        meta = dict(meta_payload)
        meta.setdefault("locale", locale)
        meta.setdefault("ui_version", 2)
        meta.setdefault("render_mode", "canvas_dom_hybrid")
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
        )

        map_path.write_text(json.dumps(map_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        timeline_path.write_text(json.dumps(timeline_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        causality_path.write_text(json.dumps(causality_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        diff_path.write_text(json.dumps(diff_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        view_model_path.write_text(json.dumps(view_model, indent=2, ensure_ascii=False), encoding="utf-8")

        inline_data = {
            "i18n": build_i18n_payload(),
            "meta": meta,
            "map": map_payload,
            "timeline": timeline_payload,
            "causality": causality_payload,
            "diff": diff_payload,
            "view_model": view_model,
        }
        self._copy_web_assets(visualizer_dir=visualizer_dir, inline_data=inline_data)
        offline_html_path.write_text(
            self._build_offline_html(
                map_payload=map_payload,
                timeline_payload=timeline_payload,
                causality_payload=causality_payload,
                diff_payload=diff_payload,
                meta_payload=meta,
                view_model=view_model,
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
            js_path=str(js_path),
            css_path=str(css_path),
            view_model_path=str(view_model_path),
            offline_html_path=str(offline_html_path),
        )

    def _copy_web_assets(self, *, visualizer_dir: Path, inline_data: dict[str, Any]) -> None:
        web_dir = Path(__file__).resolve().parent / "visualizer_web"
        required = ["index.html", "app.js", "styles.css", "i18n.json"]
        missing = [name for name in required if not (web_dir / name).is_file()]
        if missing:
            raise ValueError(f"visualizer_web assets missing: {missing}")

        for name in ["app.js", "styles.css", "i18n.json"]:
            src = web_dir / name
            dst = visualizer_dir / name
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        index_template = (web_dir / "index.html").read_text(encoding="utf-8")
        inline_json = json.dumps(inline_data, ensure_ascii=False).replace("</", "<\\/")
        index_html = index_template.replace("__VISUALIZER_INLINE_DATA__", inline_json)
        (visualizer_dir / "index.html").write_text(index_html, encoding="utf-8")

    def _build_offline_html(
        self,
        *,
        map_payload: dict[str, Any],
        timeline_payload: dict[str, Any],
        causality_payload: dict[str, Any],
        diff_payload: dict[str, Any],
        meta_payload: dict[str, Any],
        view_model: dict[str, Any],
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
      <section class=\"panel\"><h2>view_model.json</h2><pre>{dump(view_model)}</pre></section>
      <section class=\"panel\"><h2>map.json</h2><pre>{dump(map_payload)}</pre></section>
      <section class=\"panel\"><h2>timeline.json</h2><pre>{dump(timeline_payload)}</pre></section>
      <section class=\"panel\"><h2>causality.json</h2><pre>{dump(causality_payload)}</pre></section>
      <section class=\"panel\"><h2>diff.json</h2><pre>{dump(diff_payload)}</pre></section>
    </div>
  </body>
</html>
"""
