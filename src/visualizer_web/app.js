(() => {
  const state = {
    i18n: {},
    locale: 'ko',
    meta: {},
    viewModel: null,
    map: null,
    timeline: null,
    causality: null,
    diff: null,
    selectedNodeId: '',
    activeTab: 'timeline',
    search: '',
    languageFilter: '',
    kindFilter: '',
    edgeFilter: '',
    diffOverlay: true,
    transform: { x: 32, y: 24, scale: 0.72 },
    drag: { active: false, sx: 0, sy: 0, ox: 0, oy: 0 },
    editSession: null,
  };

  const $ = (id) => document.getElementById(id);

  const loadJson = async (path) => {
    const res = await fetch(path);
    if (!res.ok) {
      throw new Error(`Failed to load ${path}: ${res.status}`);
    }
    return await res.json();
  };

  const t = (key) => {
    const lang = state.i18n[state.locale] || state.i18n.ko || {};
    return lang[key] || key;
  };

  const fmt = (value) => JSON.stringify(value, null, 2);

  const maxDomNodes = (zoom) => {
    if (zoom < 0.35) return 700;
    if (zoom < 0.6) return 1800;
    if (zoom < 1.0) return 4200;
    return 8500;
  };

  const edgeStride = (zoom) => {
    if (zoom < 0.35) return 14;
    if (zoom < 0.6) return 6;
    if (zoom < 1.0) return 3;
    return 1;
  };

  const fallbackViewModel = (map, timeline, causality, diff) => {
    const nodes = Array.isArray(map?.nodes) ? map.nodes : [];
    const edges = Array.isArray(map?.edges) ? map.edges : [];
    const clusters = [];
    const byCategory = new Map();
    for (const node of nodes) {
      const key = String(node.folder_category || 'misc');
      if (!byCategory.has(key)) byCategory.set(key, []);
      byCategory.get(key).push(node);
    }
    let cx = 40;
    let cy = 40;
    const nodePositions = {};
    const nodesById = {};
    const adjacencyOut = {};
    const adjacencyIn = {};
    const edgesById = {};

    for (const [key, group] of byCategory.entries()) {
      const cols = Math.max(2, Math.min(4, Math.ceil(Math.sqrt(group.length))));
      const cardW = 250;
      const cardH = 78;
      const gapX = 22;
      const gapY = 16;
      const pad = 20;
      const rows = Math.max(1, Math.ceil(group.length / cols));
      const cw = pad * 2 + cols * cardW + (cols - 1) * gapX;
      const ch = pad * 2 + rows * cardH + (rows - 1) * gapY + 28;

      const clusterId = `cluster::${key}`;
      clusters.push({
        id: clusterId,
        key,
        title: key.charAt(0).toUpperCase() + key.slice(1),
        x: cx,
        y: cy,
        w: cw,
        h: ch,
        node_count: group.length,
        node_ids: group.map((n) => n.id),
      });

      group.forEach((node, idx) => {
        const col = idx % cols;
        const row = Math.floor(idx / cols);
        const x = cx + pad + col * (cardW + gapX);
        const y = cy + pad + 22 + row * (cardH + gapY);
        nodePositions[node.id] = { x, y, w: cardW, h: cardH, cluster_id: clusterId };
        nodesById[node.id] = {
          ...node,
          layout: nodePositions[node.id],
          metrics: { in_degree: 0, out_degree: 0, loc: Number(node.loc || 0) },
          diff_state: 'unchanged',
        };
      });

      cx += cw + 36;
      if (cx > 3200) {
        cx = 40;
        cy += ch + 36;
      }
    }

    const addedNodes = new Set(diff?.added_nodes || []);
    const removedNodes = new Set(diff?.removed_nodes || []);
    const addedEdges = new Set(diff?.added_edges || []);
    const removedEdges = new Set(diff?.removed_edges || []);

    edges.forEach((edge, idx) => {
      const source = edge.source;
      const target = edge.target;
      if (!nodePositions[source] || !nodePositions[target]) return;

      const src = nodePositions[source];
      const dst = nodePositions[target];
      const sx = src.x + src.w / 2;
      const sy = src.y + src.h / 2;
      const tx = dst.x + dst.w / 2;
      const ty = dst.y + dst.h / 2;
      const span = Math.abs(tx - sx);
      const bend = Math.max(24, Math.min(220, span * 0.35));

      const key = `${source}->${target}:${edge.edge_type || ''}`;
      edgesById[`edge::${idx}`] = {
        id: `edge::${idx}`,
        source,
        target,
        edge_type: edge.edge_type || 'unknown',
        confidence: Number(edge.confidence || 0),
        inferred: Boolean(edge.inferred),
        diff_state: addedEdges.has(key) ? 'added' : removedEdges.has(key) ? 'removed' : 'unchanged',
        points: { sx, sy, c1x: sx + bend, c1y: sy, c2x: tx - bend, c2y: ty, tx, ty },
      };

      adjacencyOut[source] = adjacencyOut[source] || [];
      adjacencyOut[source].push(target);
      adjacencyIn[target] = adjacencyIn[target] || [];
      adjacencyIn[target].push(source);
      nodesById[source].metrics.out_degree += 1;
      nodesById[target].metrics.in_degree += 1;
    });

    Object.keys(nodesById).forEach((id) => {
      if (addedNodes.has(id)) nodesById[id].diff_state = 'added';
      if (removedNodes.has(id)) nodesById[id].diff_state = 'removed';
    });

    return {
      version: 1,
      viewport: { width: 3400, height: Math.max(1200, cy + 600) },
      clusters,
      nodesById,
      edgesById,
      adjacency: { out: adjacencyOut, in: adjacencyIn },
      timeline,
      causality,
      diff,
      filters: {
        languages: [...new Set(nodes.map((n) => String(n.language || '')))].filter(Boolean).sort(),
        kinds: [...new Set(nodes.map((n) => String(n.kind || 'unknown')))].sort(),
        edge_types: [...new Set(edges.map((e) => String(e.edge_type || 'unknown')))].sort(),
      },
      stats: {
        cluster_count: clusters.length,
        node_count: Object.keys(nodesById).length,
        edge_count: Object.keys(edgesById).length,
        graph_density: Object.keys(edgesById).length / Math.max(1, Object.keys(nodesById).length ** 2),
      },
    };
  };

  const applyI18n = () => {
    $('title').textContent = t('title');
    $('label-structure').textContent = t('structure_graph');
    $('label-inspector').textContent = t('detail_inspector');
    $('label-edit').textContent = t('edit_preview');
  };

  const allNodes = () => Object.values(state.viewModel?.nodesById || {});
  const allEdges = () => Object.values(state.viewModel?.edgesById || {});

  const filterNodes = () => {
    const q = state.search.trim().toLowerCase();
    return allNodes().filter((node) => {
      if (state.languageFilter && String(node.language || '') !== state.languageFilter) return false;
      if (state.kindFilter && String(node.kind || '') !== state.kindFilter) return false;
      if (!q) return true;

      const hay = [node.label, node.path, node.kind, node.language, node.folder_category]
        .map((v) => String(v || '').toLowerCase())
        .join(' ');
      return hay.includes(q);
    });
  };

  const nodeIdSet = (nodes) => new Set(nodes.map((n) => String(n.id)));

  const filterEdges = (visibleNodes) => {
    const visible = nodeIdSet(visibleNodes);
    return allEdges().filter((edge) => {
      if (!visible.has(String(edge.source)) || !visible.has(String(edge.target))) return false;
      if (state.edgeFilter && String(edge.edge_type || '') !== state.edgeFilter) return false;
      return true;
    });
  };

  const transformed = (x, y) => {
    return {
      x: x * state.transform.scale + state.transform.x,
      y: y * state.transform.scale + state.transform.y,
    };
  };

  const drawEdges = (edges) => {
    const canvas = $('edge-canvas');
    const stage = $('graph-stage');
    const rect = stage.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;

    canvas.width = Math.floor(rect.width * dpr);
    canvas.height = Math.floor(rect.height * dpr);
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;

    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.lineWidth = 1.2;

    const stride = edgeStride(state.transform.scale);
    edges.forEach((edge, idx) => {
      if (idx % stride !== 0) return;

      const p = edge.points;
      const s = transformed(p.sx, p.sy);
      const c1 = transformed(p.c1x, p.c1y);
      const c2 = transformed(p.c2x, p.c2y);
      const t = transformed(p.tx, p.ty);

      if (edge.inferred) {
        ctx.setLineDash([5, 5]);
      } else {
        ctx.setLineDash([]);
      }

      const diffState = state.diffOverlay ? String(edge.diff_state || 'unchanged') : 'unchanged';
      if (diffState === 'added') ctx.strokeStyle = 'rgba(133, 241, 187, 0.72)';
      else if (diffState === 'removed') ctx.strokeStyle = 'rgba(255, 123, 151, 0.78)';
      else if (edge.inferred) ctx.strokeStyle = 'rgba(255, 208, 112, 0.58)';
      else ctx.strokeStyle = 'rgba(140, 175, 239, 0.42)';

      if (state.selectedNodeId && edge.source !== state.selectedNodeId && edge.target !== state.selectedNodeId) {
        ctx.globalAlpha = 0.18;
      } else {
        ctx.globalAlpha = 1;
      }

      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.bezierCurveTo(c1.x, c1.y, c2.x, c2.y, t.x, t.y);
      ctx.stroke();
    });

    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
  };

  const applyLayerTransform = () => {
    const value = `translate(${state.transform.x}px, ${state.transform.y}px) scale(${state.transform.scale})`;
    $('cluster-layer').style.transform = value;
    $('node-layer').style.transform = value;
    $('selection-layer').style.transform = value;
  };

  const renderClusters = (visibleNodes) => {
    const layer = $('cluster-layer');
    const clusters = state.viewModel.clusters || [];
    const visibleSet = nodeIdSet(visibleNodes);

    const html = clusters
      .filter((cluster) => (cluster.node_ids || []).some((id) => visibleSet.has(String(id))))
      .map((cluster) => {
        return `
          <div class="cluster-box" style="left:${cluster.x}px;top:${cluster.y}px;width:${cluster.w}px;height:${cluster.h}px;">
            <div class="cluster-title">${cluster.title} (${cluster.node_count})</div>
          </div>
        `;
      })
      .join('');
    layer.innerHTML = html;
  };

  const nodeBadge = (node) => {
    const m = node.metrics || {};
    return `${node.kind || 'node'} · ${m.out_degree || 0}f ${m.in_degree || 0}r · ${m.loc || 0}L`;
  };

  const renderNodes = (visibleNodes) => {
    const layer = $('node-layer');

    const limited = visibleNodes.slice(0, maxDomNodes(state.transform.scale));
    const html = limited
      .map((node) => {
        const layout = node.layout || { x: 0, y: 0, w: 220, h: 72 };
        const selected = state.selectedNodeId === node.id ? 'selected' : '';
        const diffState = state.diffOverlay ? String(node.diff_state || 'unchanged') : 'unchanged';
        const diffClass = diffState === 'added' || diffState === 'removed' ? diffState : '';
        return `
          <div class="node-card ${selected} ${diffClass}" data-node-id="${node.id}" style="left:${layout.x}px;top:${layout.y}px;width:${layout.w}px;height:${layout.h}px;">
            <div class="node-title" title="${node.label}">${node.label}</div>
            <div class="node-meta">
              <span>${nodeBadge(node)}</span>
            </div>
          </div>
        `;
      })
      .join('');

    layer.innerHTML = html;
    layer.querySelectorAll('.node-card').forEach((el) => {
      el.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const id = el.getAttribute('data-node-id') || '';
        state.selectedNodeId = id;
        render();
      });
    });
  };

  const selectedNeighborhood = () => {
    const id = state.selectedNodeId;
    if (!id) return { hop1: [], hop2: [] };

    const out = state.viewModel.adjacency?.out || {};
    const inMap = state.viewModel.adjacency?.in || {};

    const hop1Set = new Set([...(out[id] || []), ...(inMap[id] || [])]);
    const hop2Set = new Set();
    hop1Set.forEach((n) => {
      (out[n] || []).forEach((m) => hop2Set.add(m));
      (inMap[n] || []).forEach((m) => hop2Set.add(m));
    });
    hop2Set.delete(id);

    return {
      hop1: [...hop1Set],
      hop2: [...hop2Set],
    };
  };

  const renderSelectionOverlay = () => {
    const layer = $('selection-layer');
    const selected = state.selectedNodeId;
    if (!selected) {
      layer.innerHTML = '';
      return;
    }
    const node = state.viewModel.nodesById[selected];
    if (!node) {
      layer.innerHTML = '';
      return;
    }

    const n = selectedNeighborhood();
    const all = [selected, ...n.hop1, ...n.hop2];

    const html = all
      .map((id) => {
        const entry = state.viewModel.nodesById[id];
        if (!entry) return '';
        const l = entry.layout;
        const color = id === selected ? 'rgba(133, 241, 187, 0.75)' : n.hop1.includes(id) ? 'rgba(125, 178, 255, 0.62)' : 'rgba(255, 208, 112, 0.5)';
        return `<div style="position:absolute;left:${l.x - 3}px;top:${l.y - 3}px;width:${l.w + 6}px;height:${l.h + 6}px;border:1px solid ${color};border-radius:12px;pointer-events:none;"></div>`;
      })
      .join('');

    layer.innerHTML = html;
  };

  const renderInspector = () => {
    const selected = state.selectedNodeId;
    if (!selected || !state.viewModel.nodesById[selected]) {
      $('inspector-content').textContent = 'Select a node to inspect details.';
      return;
    }

    const node = state.viewModel.nodesById[selected];
    const neighborhood = selectedNeighborhood();
    const payload = {
      selected_node: node,
      path_highlight: {
        hop1_count: neighborhood.hop1.length,
        hop2_count: neighborhood.hop2.length,
        hop1: neighborhood.hop1,
        hop2: neighborhood.hop2,
      },
      runtime_source: state.meta.runtime_source,
    };
    $('inspector-content').textContent = fmt(payload);
  };

  const renderBottom = () => {
    const data = {
      timeline: state.timeline,
      causality: state.causality,
      diff: state.diff,
      debug: {
        view_model_stats: state.viewModel.stats,
        transform: state.transform,
        filters: {
          search: state.search,
          language: state.languageFilter,
          kind: state.kindFilter,
          edge: state.edgeFilter,
          diff_overlay: state.diffOverlay,
        },
      },
    };

    $('bottom-content').textContent = fmt(data[state.activeTab] || data.timeline);

    ['timeline', 'causality', 'diff', 'debug'].forEach((name) => {
      const btn = $(`tab-${name}`);
      if (!btn) return;
      btn.classList.toggle('active', state.activeTab === name);
    });
  };

  const render = () => {
    if (!state.viewModel) return;

    const nodes = filterNodes();
    const edges = filterEdges(nodes);

    applyLayerTransform();
    renderClusters(nodes);
    renderNodes(nodes);
    renderSelectionOverlay();
    drawEdges(edges);
    renderInspector();
    renderBottom();

    const stats = state.viewModel.stats || {};
    $('stats-strip').textContent = `${stats.node_count || 0} nodes · ${stats.edge_count || 0} edges · ${stats.cluster_count || 0} clusters`;
  };

  const fitSelected = () => {
    const id = state.selectedNodeId;
    if (!id) return;
    const node = state.viewModel?.nodesById?.[id];
    if (!node) return;

    const stage = $('graph-stage').getBoundingClientRect();
    const l = node.layout;
    state.transform.scale = Math.max(0.45, Math.min(1.5, state.transform.scale));
    state.transform.x = stage.width / 2 - (l.x + l.w / 2) * state.transform.scale;
    state.transform.y = stage.height / 2 - (l.y + l.h / 2) * state.transform.scale;
    render();
  };

  const setupFilters = () => {
    const setOptions = (el, values, label) => {
      el.innerHTML = `<option value="">All ${label}</option>` + values.map((v) => `<option value="${v}">${v}</option>`).join('');
    };

    const filters = state.viewModel.filters || {};
    setOptions($('language-filter'), filters.languages || [], 'languages');
    setOptions($('kind-filter'), filters.kinds || [], 'kinds');
    setOptions($('edge-filter'), filters.edge_types || [], 'edges');
  };

  const apiToolCall = async (tool, args) => {
    const res = await fetch('/api/tool', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool, args }),
    });
    if (!res.ok) {
      throw new Error(`API ${res.status}`);
    }
    return await res.json();
  };

  const setupEditDrawer = () => {
    $('edit-propose-btn').addEventListener('click', async () => {
      const selected = state.selectedNodeId;
      if (!selected) {
        $('edit-status').textContent = 'Select a node first.';
        return;
      }
      const node = state.viewModel.nodesById[selected];
      const filePath = String(node.path || '').startsWith('res://') ? String(node.path).replace('res://', '') : String(node.path || '');

      let payload = {};
      try {
        payload = JSON.parse($('edit-payload').value || '{}');
      } catch (err) {
        $('edit-status').textContent = `Invalid payload JSON: ${err}`;
        return;
      }

      try {
        const result = await apiToolCall('godot_visualizer_edit_propose', {
          project_path: state.meta.project_path || '',
          file_path: filePath,
          operation: $('edit-operation').value,
          payload,
          reason: $('edit-reason').value || 'visualizer edit',
        });
        state.editSession = result.edit_session || null;
        $('edit-status').textContent = `Proposed: ${state.editSession?.edit_session_id || 'unknown'}`;
        $('edit-preview').textContent = fmt(result);
      } catch (err) {
        $('edit-status').textContent = `Propose failed (live API required): ${err}`;
      }
    });

    $('edit-apply-btn').addEventListener('click', async () => {
      if (!state.editSession) {
        $('edit-status').textContent = 'No edit session.';
        return;
      }
      try {
        const result = await apiToolCall('godot_visualizer_edit_apply', {
          edit_session_id: state.editSession.edit_session_id,
          approval_token: state.editSession.approval_token,
        });
        $('edit-status').textContent = `Applied: ${result.status || 'ok'}`;
        $('edit-preview').textContent = fmt(result);
      } catch (err) {
        $('edit-status').textContent = `Apply failed (live API required): ${err}`;
      }
    });

    $('edit-cancel-btn').addEventListener('click', async () => {
      if (!state.editSession) {
        $('edit-status').textContent = 'No edit session.';
        return;
      }
      try {
        const result = await apiToolCall('godot_visualizer_edit_cancel', {
          edit_session_id: state.editSession.edit_session_id,
        });
        $('edit-status').textContent = `Cancelled: ${result.status || 'ok'}`;
        $('edit-preview').textContent = fmt(result);
        state.editSession = null;
      } catch (err) {
        $('edit-status').textContent = `Cancel failed (live API required): ${err}`;
      }
    });
  };

  const setupEvents = () => {
    $('search-input').addEventListener('input', (ev) => {
      state.search = String(ev.target.value || '');
      render();
    });

    $('language-filter').addEventListener('change', (ev) => {
      state.languageFilter = String(ev.target.value || '');
      render();
    });

    $('kind-filter').addEventListener('change', (ev) => {
      state.kindFilter = String(ev.target.value || '');
      render();
    });

    $('edge-filter').addEventListener('change', (ev) => {
      state.edgeFilter = String(ev.target.value || '');
      render();
    });

    $('diff-toggle').addEventListener('change', (ev) => {
      state.diffOverlay = Boolean(ev.target.checked);
      render();
    });

    $('lang-select').addEventListener('change', (ev) => {
      state.locale = String(ev.target.value || 'ko');
      applyI18n();
      render();
    });

    ['timeline', 'causality', 'diff', 'debug'].forEach((name) => {
      const btn = $(`tab-${name}`);
      btn.addEventListener('click', () => {
        state.activeTab = name;
        renderBottom();
      });
    });

    $('graph-stage').addEventListener('click', () => {
      state.selectedNodeId = '';
      render();
    });

    const stage = $('graph-stage');
    stage.addEventListener('mousedown', (ev) => {
      state.drag.active = true;
      state.drag.sx = ev.clientX;
      state.drag.sy = ev.clientY;
      state.drag.ox = state.transform.x;
      state.drag.oy = state.transform.y;
    });

    window.addEventListener('mousemove', (ev) => {
      if (!state.drag.active) return;
      state.transform.x = state.drag.ox + (ev.clientX - state.drag.sx);
      state.transform.y = state.drag.oy + (ev.clientY - state.drag.sy);
      applyLayerTransform();
      drawEdges(filterEdges(filterNodes()));
    });

    window.addEventListener('mouseup', () => {
      state.drag.active = false;
    });

    stage.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const delta = ev.deltaY < 0 ? 1.08 : 0.92;
      const old = state.transform.scale;
      const next = Math.max(0.2, Math.min(2.0, old * delta));

      const rect = stage.getBoundingClientRect();
      const cx = ev.clientX - rect.left;
      const cy = ev.clientY - rect.top;
      const wx = (cx - state.transform.x) / old;
      const wy = (cy - state.transform.y) / old;

      state.transform.scale = next;
      state.transform.x = cx - wx * next;
      state.transform.y = cy - wy * next;
      render();
    }, { passive: false });

    stage.addEventListener('keydown', (ev) => {
      if (ev.key === '/') {
        ev.preventDefault();
        $('search-input').focus();
      }
      if (ev.key === 'Escape') {
        state.selectedNodeId = '';
        render();
      }
      if (ev.key.toLowerCase() === 'f') {
        fitSelected();
      }
    });

    window.addEventListener('resize', () => render());
  };

  const bootstrap = async () => {
    state.i18n = await loadJson('i18n.json');
    state.meta = await loadJson('meta.json');

    const [map, timeline, causality, diff] = await Promise.all([
      loadJson('map.json'),
      loadJson('timeline.json'),
      loadJson('causality.json'),
      loadJson('diff.json'),
    ]);

    state.map = map;
    state.timeline = timeline;
    state.causality = causality;
    state.diff = diff;

    try {
      state.viewModel = await loadJson('view_model.json');
    } catch (_) {
      state.viewModel = fallbackViewModel(map, timeline, causality, diff);
    }

    state.locale = state.meta.locale || 'ko';
    $('lang-select').value = state.locale;

    $('runtime-source').textContent = `${t('runtime_source')}: ${state.meta.runtime_source || 'unknown'}`;

    applyI18n();
    setupFilters();
    setupEvents();
    setupEditDrawer();
    render();
  };

  bootstrap().catch((err) => {
    console.error('Visualizer bootstrap failed', err);
    const el = $('inspector-content');
    if (el) {
      el.textContent = `Visualizer bootstrap failed:\n${String(err)}`;
    }
  });
})();
