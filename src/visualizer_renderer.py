"""Renderer for static visualizer artifact files (JSON + HTML bundle)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .visualizer_i18n import build_i18n_payload, get_translations, normalize_locale
from .visualizer_schema import VisualizerRunArtifacts


class VisualizerRenderer:
    """Writes map/timeline/causality/diff/meta and static web assets."""

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
        html_path = visualizer_dir / "index.html"
        js_path = visualizer_dir / "app.js"
        css_path = visualizer_dir / "styles.css"

        map_path.write_text(json.dumps(map_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        timeline_path.write_text(json.dumps(timeline_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        causality_path.write_text(json.dumps(causality_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        diff_path.write_text(json.dumps(diff_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        meta_path.write_text(json.dumps(meta_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        html_path.write_text(self._html_template(), encoding="utf-8")
        js_path.write_text(self._js_bundle(locale=locale), encoding="utf-8")
        css_path.write_text(self._css_bundle(), encoding="utf-8")

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
        )

    def _html_template(self) -> str:
        return """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Godot Visualizer</title>
    <link rel=\"stylesheet\" href=\"styles.css\" />
  </head>
  <body>
    <header>
      <h1 id=\"title\"></h1>
      <div class=\"toolbar\">
        <label for=\"lang-select\">Language</label>
        <select id=\"lang-select\">
          <option value=\"ko\">한국어</option>
          <option value=\"en\">English</option>
        </select>
        <span id=\"runtime-source\"></span>
      </div>
    </header>

    <main>
      <section class=\"panel\" id=\"structure-panel\">
        <h2 id=\"label-structure\"></h2>
        <pre id=\"structure-content\"></pre>
      </section>

      <section class=\"panel\" id=\"timeline-panel\">
        <h2 id=\"label-timeline\"></h2>
        <pre id=\"timeline-content\"></pre>
      </section>

      <section class=\"panel\" id=\"causality-panel\">
        <h2 id=\"label-causality\"></h2>
        <pre id=\"causality-content\"></pre>
      </section>

      <section class=\"panel\" id=\"diff-panel\">
        <h2 id=\"label-diff\"></h2>
        <pre id=\"diff-content\"></pre>
      </section>

      <section class=\"panel\" id=\"inspector-panel\">
        <h2 id=\"label-inspector\"></h2>
        <pre id=\"inspector-content\"></pre>
      </section>

      <section class=\"panel\" id=\"edit-panel\">
        <h2 id=\"label-edit\"></h2>
        <pre id=\"edit-content\"></pre>
      </section>
    </main>

    <script src=\"app.js\"></script>
  </body>
</html>
"""

    def _js_bundle(self, *, locale: str) -> str:
        default_locale = normalize_locale(locale)
        translations = json.dumps(build_i18n_payload(), ensure_ascii=False)
        return f"""const I18N = {translations};
let currentLocale = {json.dumps(default_locale)};

function t(key) {{
  const pack = I18N[currentLocale] || I18N.ko;
  return pack[key] || key;
}}

async function loadJson(path) {{
  const res = await fetch(path);
  return await res.json();
}}

function applyLabels(meta) {{
  document.getElementById('title').textContent = t('title');
  document.getElementById('label-structure').textContent = t('structure_graph');
  document.getElementById('label-timeline').textContent = t('tick_timeline');
  document.getElementById('label-causality').textContent = t('causality_chain');
  document.getElementById('label-diff').textContent = t('diff_panel');
  document.getElementById('label-inspector').textContent = t('detail_inspector');
  document.getElementById('label-edit').textContent = t('edit_preview');
  document.getElementById('runtime-source').textContent = `${{t('runtime_source')}}: ${{meta.runtime_source || 'unknown'}}`;
}}

function pretty(obj) {{
  return JSON.stringify(obj, null, 2);
}}

function render(mapData, timelineData, causalityData, diffData, metaData) {{
  document.getElementById('structure-content').textContent = pretty({{
    summary: mapData.summary,
    nodes: mapData.nodes.slice(0, 200),
    edges: mapData.edges.slice(0, 200)
  }});
  document.getElementById('timeline-content').textContent = pretty(timelineData);
  document.getElementById('causality-content').textContent = pretty(causalityData);
  document.getElementById('diff-content').textContent = pretty(diffData);
  document.getElementById('inspector-content').textContent = pretty(metaData);
  document.getElementById('edit-content').textContent = 'Edit proposals are shown via MCP tool responses.';
  applyLabels(metaData);
}}

async function bootstrap() {{
  const langSelect = document.getElementById('lang-select');
  langSelect.value = currentLocale;
  langSelect.addEventListener('change', async (ev) => {{
    currentLocale = ev.target.value;
    const mapData = await loadJson('map.json');
    const timelineData = await loadJson('timeline.json');
    const causalityData = await loadJson('causality.json');
    const diffData = await loadJson('diff.json');
    const metaData = await loadJson('meta.json');
    render(mapData, timelineData, causalityData, diffData, metaData);
  }});

  const mapData = await loadJson('map.json');
  const timelineData = await loadJson('timeline.json');
  const causalityData = await loadJson('causality.json');
  const diffData = await loadJson('diff.json');
  const metaData = await loadJson('meta.json');
  render(mapData, timelineData, causalityData, diffData, metaData);
}}

bootstrap().catch((err) => {{
  console.error('visualizer bootstrap failed', err);
}});
"""

    def _css_bundle(self) -> str:
        return """
:root {
  --bg: #f3f2eb;
  --text: #1f2a2e;
  --panel: #fffdf6;
  --accent: #006c67;
  --line: #d4d0c4;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Pretendard", "Noto Sans KR", "IBM Plex Sans", sans-serif;
  color: var(--text);
  background: radial-gradient(circle at top left, #f7f5ea, #ecebe2 60%, #e2dfd2);
}

header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--line);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

h1 { margin: 0; font-size: 22px; }
h2 { margin-top: 0; font-size: 16px; }

.toolbar { display: flex; gap: 10px; align-items: center; font-size: 14px; }

main {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  padding: 12px;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px;
  min-height: 240px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}

pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: "JetBrains Mono", "IBM Plex Mono", monospace;
  font-size: 12px;
  line-height: 1.5;
  max-height: 320px;
  overflow: auto;
}

@media (max-width: 960px) {
  main {
    grid-template-columns: 1fr;
  }
}
"""
