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
    showCallsEdges: false,
    currentLayer: 'cluster',
    focusCluster: '',
    focusFile: '',
    transform: { x: 32, y: 24, scale: 0.72 },
    drag: { active: false, sx: 0, sy: 0, ox: 0, oy: 0 },
    userAdjustedView: false,
    editSession: null,
    diagnosticsCollapsed: false,
    inspectorRawVisible: false,
  };

  const $ = (id) => document.getElementById(id);

  const readInlineData = () => {
    const el = $('visualizer-inline-data');
    if (!el || !el.textContent) return {};
    try {
      return JSON.parse(el.textContent);
    } catch (_) {
      return {};
    }
  };

  const inlineData = readInlineData();

  const loadJson = async (path, fallbackKey = '') => {
    try {
      const res = await fetch(path);
      if (!res.ok) {
        throw new Error(`Failed to load ${path}: ${res.status}`);
      }
      return await res.json();
    } catch (err) {
      if (fallbackKey && inlineData && typeof inlineData === 'object' && fallbackKey in inlineData) {
        return inlineData[fallbackKey];
      }
      throw err;
    }
  };

  const clamp = (value, minValue, maxValue) => Math.max(minValue, Math.min(maxValue, value));
  const fmt = (value) => JSON.stringify(value, null, 2);
  const t = (key) => {
    const lang = state.i18n[state.locale] || state.i18n.ko || {};
    return lang[key] || key;
  };

  const escapeHtml = (value) => {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };

  const maxDomNodes = (zoom, layerName) => {
    if (layerName === 'cluster') return 300;
    if (layerName === 'structural') return zoom < 0.7 ? 420 : 680;
    if (zoom < 0.35) return 300;
    if (zoom < 0.6) return 700;
    if (zoom < 1.0) return 1800;
    return 3600;
  };

  const edgeStride = (zoom, layerName) => {
    if (layerName === 'cluster') return 1;
    if (layerName === 'structural') return zoom < 0.55 ? 2 : 1;
    if (zoom < 0.35) return 18;
    if (zoom < 0.6) return 8;
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
    const edgesById = {};
    const adjacencyOut = {};
    const adjacencyIn = {};

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
        node_ids: group.map((item) => item.id),
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

    edges.forEach((edge, idx) => {
      const source = String(edge.source || '');
      const target = String(edge.target || '');
      if (!nodePositions[source] || !nodePositions[target]) return;
      const src = nodePositions[source];
      const dst = nodePositions[target];
      const sx = src.x + src.w / 2;
      const sy = src.y + src.h / 2;
      const tx = dst.x + dst.w / 2;
      const ty = dst.y + dst.h / 2;
      const span = Math.abs(tx - sx);
      const bend = Math.max(24, Math.min(220, span * 0.35));

      edgesById[`edge::${idx}`] = {
        id: `edge::${idx}`,
        source,
        target,
        edge_type: String(edge.edge_type || 'unknown'),
        confidence: Number(edge.confidence || 0),
        inferred: Boolean(edge.inferred),
        diff_state: 'unchanged',
        points: { sx, sy, c1x: sx + bend, c1y: sy, c2x: tx - bend, c2y: ty, tx, ty },
      };

      adjacencyOut[source] = adjacencyOut[source] || [];
      adjacencyOut[source].push(target);
      adjacencyIn[target] = adjacencyIn[target] || [];
      adjacencyIn[target].push(source);
      nodesById[source].metrics.out_degree += 1;
      nodesById[target].metrics.in_degree += 1;
    });

    const structuralIds = Object.keys(nodesById).filter((id) => String(nodesById[id].kind) !== 'function');
    const structuralSet = new Set(structuralIds);
    const structuralEdgeIds = Object.keys(edgesById).filter((id) => {
      const edge = edgesById[id];
      return structuralSet.has(String(edge.source)) && structuralSet.has(String(edge.target)) && String(edge.edge_type) !== 'calls';
    });

    const clusterNodes = {};
    clusters.forEach((cluster) => {
      const width = Math.max(280, Math.min(520, Number(cluster.w || 320) * 0.44));
      const height = 116;
      clusterNodes[cluster.id] = {
        id: cluster.id,
        kind: 'cluster',
        label: cluster.title,
        path: `cluster://${cluster.key}`,
        language: 'meta',
        folder_category: cluster.key,
        loc: Number(cluster.node_count || 0),
        metadata: {
          cluster_key: cluster.key,
          node_count: Number(cluster.node_count || 0),
        },
        layout: {
          x: Number(cluster.x || 0) + Math.max(0, (Number(cluster.w || 0) - width) / 2),
          y: Number(cluster.y || 0) + 20,
          w: width,
          h: height,
          cluster_id: cluster.id,
        },
        metrics: { in_degree: 0, out_degree: 0, loc: Number(cluster.node_count || 0) },
        diff_state: 'unchanged',
      };
    });

    return {
      version: 2,
      viewport: { width: 3400, height: Math.max(1200, cy + 600) },
      clusters,
      nodesById,
      edgesById,
      adjacency: { out: adjacencyOut, in: adjacencyIn },
      layers: {
        cluster: {
          node_ids: Object.keys(clusterNodes),
          edge_ids: [],
          nodesById: clusterNodes,
          edgesById: {},
          adjacency: { out: {}, in: {} },
        },
        structural: {
          node_ids: structuralIds,
          edge_ids: structuralEdgeIds,
          adjacency: { out: {}, in: {} },
        },
        detail: {
          node_ids: Object.keys(nodesById),
          edge_ids: Object.keys(edgesById),
          adjacency: { out: adjacencyOut, in: adjacencyIn },
        },
      },
      ui_defaults: {
        default_layer: 'cluster',
        hidden_edge_types: ['calls'],
        collapsed_kinds: ['function'],
        focus_cluster: '',
      },
      cluster_metrics: clusters.map((cluster) => ({
        key: cluster.key,
        node_count: Number(cluster.node_count || 0),
        function_count: 0,
        edge_count: 0,
        hotspot_score: Number(cluster.node_count || 0),
      })),
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

  const allNodesById = () => state.viewModel?.nodesById || {};
  const allEdgesById = () => state.viewModel?.edgesById || {};

  const clusterKeyForNode = (node) => {
    const clusterId = String(node?.layout?.cluster_id || '');
    const clusters = Array.isArray(state.viewModel?.clusters) ? state.viewModel.clusters : [];
    const cluster = clusters.find((item) => String(item.id || '') === clusterId);
    return String(cluster?.key || node?.folder_category || '').toLowerCase();
  };

  const effectiveLayer = () => {
    const zoom = state.transform.scale;
    if (zoom < 0.45) return 'cluster';
    if (zoom < 0.9) return 'structural';
    if (state.currentLayer === 'cluster') return 'structural';
    return state.currentLayer;
  };

  const layerPayload = (layerName) => {
    const layers = state.viewModel?.layers || {};
    const payload = layers[layerName] || {};
    const globalNodes = allNodesById();
    const globalEdges = allEdgesById();

    if (layerName === 'cluster') {
      return {
        nodeIds: Array.isArray(payload.node_ids) ? payload.node_ids.map(String) : [],
        edgeIds: Array.isArray(payload.edge_ids) ? payload.edge_ids.map(String) : [],
        nodesById: payload.nodesById || {},
        edgesById: payload.edgesById || {},
        adjacency: payload.adjacency || { out: {}, in: {} },
      };
    }

    return {
      nodeIds: Array.isArray(payload.node_ids) ? payload.node_ids.map(String) : Object.keys(globalNodes),
      edgeIds: Array.isArray(payload.edge_ids) ? payload.edge_ids.map(String) : Object.keys(globalEdges),
      nodesById: globalNodes,
      edgesById: globalEdges,
      adjacency: payload.adjacency || state.viewModel?.adjacency || { out: {}, in: {} },
    };
  };

  const worldBoundsFromStage = () => {
    const stageRect = $('graph-stage').getBoundingClientRect();
    const s = Math.max(0.1, state.transform.scale);
    const minX = (0 - state.transform.x) / s;
    const minY = (0 - state.transform.y) / s;
    const maxX = (stageRect.width - state.transform.x) / s;
    const maxY = (stageRect.height - state.transform.y) / s;
    return { minX, minY, maxX, maxY };
  };

  const visibleNodeIdsByViewport = (nodes) => {
    const bounds = worldBoundsFromStage();
    const margin = 80;
    return nodes
      .filter((node) => {
        const l = node.layout || { x: 0, y: 0, w: 0, h: 0 };
        if (l.x > bounds.maxX + margin) return false;
        if (l.y > bounds.maxY + margin) return false;
        if (l.x + l.w < bounds.minX - margin) return false;
        if (l.y + l.h < bounds.minY - margin) return false;
        return true;
      })
      .map((node) => String(node.id));
  };

  const diagnosticsList = () => {
    if (!Array.isArray(state.meta?.runtime_diagnostics)) return [];
    return state.meta.runtime_diagnostics.filter((item) => item && typeof item === 'object');
  };

  const diagnosticHint = (diagnostic) => {
    const code = String(diagnostic?.code || '').trim();
    if (code) {
      const key = `diagnostic_hint_${code}`;
      const translated = t(key);
      if (translated !== key) return translated;
    }
    if (String(diagnostic?.level || '') === 'warning') {
      return t('diagnostic_hint_runtime_warning_generic');
    }
    if (diagnostic?.hint) return String(diagnostic.hint);
    return t('diagnostic_hint_runtime_error_generic');
  };

  const findDiagnosticNodeId = () => {
    const diagnostics = diagnosticsList();
    const nodes = allNodesById();
    for (const diagnostic of diagnostics) {
      const msg = String(diagnostic.message || '');
      const found = Object.values(nodes).find((node) => {
        const kind = String(node.kind || '');
        if (kind !== 'error' && kind !== 'warning') return false;
        const metadataMessage = String(node.metadata?.message || '');
        return metadataMessage === msg || metadataMessage.includes(msg) || msg.includes(metadataMessage);
      });
      if (found) return String(found.id);
    }
    return '';
  };

  const renderRuntimeWarningBanner = () => {
    const banner = $('runtime-warning-banner');
    const diagnostics = diagnosticsList();
    if (!banner) return;

    if (diagnostics.length === 0) {
      banner.classList.add('hidden');
      return;
    }

    const primary = diagnostics.find((item) => String(item.level || '') === 'error') || diagnostics[0];
    const source = String(primary.source || '').trim();
    const line = Number(primary.line);
    const locationParts = [];
    if (source) locationParts.push(`${t('runtime_diagnostics_source')}: ${source}`);
    if (Number.isFinite(line) && line >= 0) locationParts.push(`${t('runtime_diagnostics_line')}: ${line}`);

    $('runtime-warning-title').textContent = `${t('runtime_diagnostics_title')} (${diagnostics.length} ${t('runtime_diagnostics_count')})`;
    $('runtime-warning-message').textContent = state.diagnosticsCollapsed ? String(primary.message || '') : [String(primary.message || ''), locationParts.join(' · ')].filter(Boolean).join('\n');
    $('runtime-warning-hint').textContent = state.diagnosticsCollapsed ? '' : `${t('runtime_diagnostics_hint')}: ${diagnosticHint(primary)}`;
    $('runtime-warning-toggle').textContent = state.diagnosticsCollapsed ? t('expand') : t('collapse');
    banner.classList.remove('hidden');
  };

  const applyI18n = () => {
    $('title').textContent = t('title');
    $('label-structure').textContent = t('structure_graph');
    $('label-inspector').textContent = t('detail_inspector');
    $('label-edit').textContent = t('edit_preview');
    $('label-diff-toggle').textContent = t('diff_overlay');
    $('label-calls-toggle').textContent = t('show_calls_edges');
    $('label-lang').textContent = t('lang');
    $('legend-added').textContent = t('added');
    $('legend-removed').textContent = t('removed');
    $('legend-inferred').textContent = t('inferred');
    $('tab-timeline').textContent = t('timeline_tab');
    $('tab-causality').textContent = t('causality_tab');
    $('tab-diff').textContent = t('diff_tab');
    $('tab-debug').textContent = t('debug_tab');
    $('edit-hint').textContent = t('edit_hint');
    $('edit-label-operation').textContent = t('operation');
    $('edit-label-payload').textContent = t('payload_json');
    $('edit-label-reason').textContent = t('reason');
    $('edit-propose-btn').textContent = t('propose');
    $('edit-apply-btn').textContent = t('apply');
    $('edit-cancel-btn').textContent = t('cancel');
    $('search-input').setAttribute('placeholder', t('search_placeholder'));
    $('runtime-source').textContent = `${t('runtime_source')}: ${state.meta.runtime_source || 'unknown'}`;
    $('runtime-warning-jump').textContent = t('jump_to_diagnostic');
    $('runtime-warning-toggle').textContent = state.diagnosticsCollapsed ? t('expand') : t('collapse');
    $('inspector-raw-toggle').textContent = state.inspectorRawVisible ? t('hide_raw_json') : t('show_raw_json');
    renderRuntimeWarningBanner();
  };

  const graphData = () => {
    const layerName = effectiveLayer();
    const payload = layerPayload(layerName);
    const nodesById = payload.nodesById || {};
    const edgesById = payload.edgesById || {};

    let nodeIds = [...(payload.nodeIds || [])];
    const edgeIds = [...(payload.edgeIds || [])];

    if (layerName !== 'cluster' && state.focusCluster) {
      nodeIds = nodeIds.filter((id) => clusterKeyForNode(nodesById[id]) === state.focusCluster);
    }

    if (layerName === 'detail' && state.focusFile) {
      nodeIds = nodeIds.filter((id) => String(nodesById[id]?.path || '') === state.focusFile);
    }

    const nodeSet = new Set(nodeIds);
    const selectedEdges = edgeIds
      .map((id) => edgesById[id])
      .filter(Boolean)
      .filter((edge) => nodeSet.has(String(edge.source)) && nodeSet.has(String(edge.target)));

    return {
      layerName,
      nodesById,
      edgesById,
      nodeIds,
      edges: selectedEdges,
      adjacency: payload.adjacency || { out: {}, in: {} },
    };
  };

  const filterNodes = (graph) => {
    const q = state.search.trim().toLowerCase();
    const nodes = graph.nodeIds
      .map((id) => graph.nodesById[id])
      .filter(Boolean)
      .filter((node) => {
        if (state.languageFilter && String(node.language || '') !== state.languageFilter) return false;
        if (state.kindFilter && String(node.kind || '') !== state.kindFilter) return false;
        if (!q) return true;
        const hay = [node.label, node.path, node.kind, node.language, node.folder_category]
          .map((value) => String(value || '').toLowerCase())
          .join(' ');
        return hay.includes(q);
      });

    if (graph.layerName === 'detail') {
      const visibleIdSet = new Set(visibleNodeIdsByViewport(nodes));
      return nodes.filter((node) => visibleIdSet.has(String(node.id)));
    }
    return nodes;
  };

  const filterEdges = (graph, visibleNodes) => {
    const visible = new Set(visibleNodes.map((node) => String(node.id)));
    return graph.edges.filter((edge) => {
      if (!visible.has(String(edge.source)) || !visible.has(String(edge.target))) return false;
      const edgeType = String(edge.edge_type || '');
      if (!state.showCallsEdges && edgeType === 'calls') return false;
      if (state.edgeFilter && edgeType !== state.edgeFilter) return false;
      return true;
    });
  };

  const transformed = (x, y) => ({
    x: x * state.transform.scale + state.transform.x,
    y: y * state.transform.scale + state.transform.y,
  });

  const drawEdges = (graph, edges) => {
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

    const stride = edgeStride(state.transform.scale, graph.layerName);
    edges.forEach((edge, idx) => {
      if (idx % stride !== 0) return;
      const p = edge.points || {};
      const s = transformed(Number(p.sx || 0), Number(p.sy || 0));
      const c1 = transformed(Number(p.c1x || 0), Number(p.c1y || 0));
      const c2 = transformed(Number(p.c2x || 0), Number(p.c2y || 0));
      const tNode = transformed(Number(p.tx || 0), Number(p.ty || 0));

      if (edge.inferred) ctx.setLineDash([5, 5]);
      else ctx.setLineDash([]);

      const diffState = state.diffOverlay ? String(edge.diff_state || 'unchanged') : 'unchanged';
      if (diffState === 'added') ctx.strokeStyle = 'rgba(133, 241, 187, 0.72)';
      else if (diffState === 'removed') ctx.strokeStyle = 'rgba(255, 123, 151, 0.78)';
      else if (edge.inferred) ctx.strokeStyle = 'rgba(255, 208, 112, 0.58)';
      else if (graph.layerName === 'cluster') ctx.strokeStyle = 'rgba(120, 188, 255, 0.6)';
      else ctx.strokeStyle = 'rgba(140, 175, 239, 0.42)';

      if (state.selectedNodeId && String(edge.source) !== state.selectedNodeId && String(edge.target) !== state.selectedNodeId) {
        ctx.globalAlpha = 0.18;
      } else {
        ctx.globalAlpha = 1;
      }

      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.bezierCurveTo(c1.x, c1.y, c2.x, c2.y, tNode.x, tNode.y);
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

  const renderClusters = (graph, visibleNodes) => {
    const layer = $('cluster-layer');
    if (graph.layerName === 'cluster') {
      layer.innerHTML = '';
      return;
    }

    const clusters = state.viewModel?.clusters || [];
    const visibleSet = new Set(visibleNodes.map((node) => String(node.id)));
    const html = clusters
      .filter((cluster) => (cluster.node_ids || []).some((id) => visibleSet.has(String(id))))
      .map((cluster) => `
        <div class="cluster-box" style="left:${cluster.x}px;top:${cluster.y}px;width:${cluster.w}px;height:${cluster.h}px;">
          <div class="cluster-title">${escapeHtml(cluster.title)} (${Number(cluster.node_count || 0)})</div>
        </div>
      `)
      .join('');
    layer.innerHTML = html;
  };

  const nodeBadge = (node, graph) => {
    if (graph.layerName === 'cluster') {
      const count = Number(node.metadata?.node_count || node.loc || 0);
      return `${count} nodes`;
    }
    const m = node.metrics || {};
    return `${node.kind || 'node'} · ${Number(m.out_degree || 0)}f ${Number(m.in_degree || 0)}r · ${Number(m.loc || 0)}L`;
  };

  const renderNodes = (graph, visibleNodes) => {
    const layer = $('node-layer');
    const limit = maxDomNodes(state.transform.scale, graph.layerName);
    const nodes = visibleNodes.slice(0, limit);

    const html = nodes
      .map((node) => {
        const layout = node.layout || { x: 0, y: 0, w: 220, h: 72 };
        const selected = state.selectedNodeId === String(node.id) ? 'selected' : '';
        const diffState = state.diffOverlay ? String(node.diff_state || 'unchanged') : 'unchanged';
        const diffClass = diffState === 'added' || diffState === 'removed' ? diffState : '';
        const clusterClass = String(node.kind || '') === 'cluster' ? 'cluster-card' : '';
        return `
          <div class="node-card ${selected} ${diffClass} ${clusterClass}" data-node-id="${escapeHtml(node.id)}" style="left:${layout.x}px;top:${layout.y}px;width:${layout.w}px;height:${layout.h}px;">
            <div class="node-title" title="${escapeHtml(node.label)}">${escapeHtml(node.label)}</div>
            <div class="node-meta"><span>${escapeHtml(nodeBadge(node, graph))}</span></div>
          </div>
        `;
      })
      .join('');

    layer.innerHTML = html;

    layer.querySelectorAll('.node-card').forEach((el) => {
      el.addEventListener('click', (ev) => {
        ev.stopPropagation();
        const nodeId = String(el.getAttribute('data-node-id') || '');
        const node = graph.nodesById[nodeId] || allNodesById()[nodeId];
        if (!node) return;

        if (graph.layerName === 'cluster') {
          const key = String(node.metadata?.cluster_key || '').toLowerCase();
          state.focusCluster = key;
          state.focusFile = '';
          state.currentLayer = 'structural';
          state.selectedNodeId = '';
          state.userAdjustedView = false;
          fitGraphToView({ renderNow: true, markInteracted: false });
          return;
        }

        state.selectedNodeId = nodeId;
        render();
      });

      el.addEventListener('dblclick', (ev) => {
        ev.stopPropagation();
        if (graph.layerName !== 'structural') return;
        const nodeId = String(el.getAttribute('data-node-id') || '');
        const node = graph.nodesById[nodeId];
        if (!node) return;
        const kind = String(node.kind || '');
        if (kind !== 'file' && kind !== 'class') return;
        state.currentLayer = 'detail';
        state.focusFile = String(node.path || '');
        state.selectedNodeId = nodeId;
        state.userAdjustedView = false;
        fitGraphToView({ renderNow: true, markInteracted: false });
      });
    });
  };

  const selectedNeighborhood = (graph) => {
    const id = state.selectedNodeId;
    if (!id) return { hop1: [], hop2: [] };

    const out = graph.adjacency?.out || {};
    const inMap = graph.adjacency?.in || {};
    const hop1Set = new Set([...(out[id] || []), ...(inMap[id] || [])]);
    const hop2Set = new Set();
    hop1Set.forEach((nodeId) => {
      (out[nodeId] || []).forEach((childId) => hop2Set.add(childId));
      (inMap[nodeId] || []).forEach((parentId) => hop2Set.add(parentId));
    });
    hop2Set.delete(id);

    return { hop1: [...hop1Set], hop2: [...hop2Set] };
  };

  const renderSelectionOverlay = (graph) => {
    const layer = $('selection-layer');
    const selected = state.selectedNodeId;
    const node = graph.nodesById[selected] || allNodesById()[selected];
    if (!selected || !node) {
      layer.innerHTML = '';
      return;
    }

    const neighborhood = selectedNeighborhood(graph);
    const ids = [selected, ...neighborhood.hop1, ...neighborhood.hop2];

    layer.innerHTML = ids
      .map((id) => {
        const entry = graph.nodesById[id] || allNodesById()[id];
        if (!entry || !entry.layout) return '';
        const l = entry.layout;
        const color =
          id === selected
            ? 'rgba(133, 241, 187, 0.75)'
            : neighborhood.hop1.includes(id)
              ? 'rgba(125, 178, 255, 0.62)'
              : 'rgba(255, 208, 112, 0.5)';
        return `<div style="position:absolute;left:${l.x - 3}px;top:${l.y - 3}px;width:${l.w + 6}px;height:${l.h + 6}px;border:1px solid ${color};border-radius:12px;pointer-events:none;"></div>`;
      })
      .join('');
  };

  const renderInspector = (graph) => {
    const selected = state.selectedNodeId;
    const node = graph.nodesById[selected] || allNodesById()[selected];
    if (!selected || !node) {
      $('inspector-content').textContent = t('select_node_hint');
      $('inspector-raw').textContent = '';
      return;
    }

    const clusterKey = clusterKeyForNode(node);
    const summary = [
      `<strong>${escapeHtml(node.label)}</strong>`,
      `${escapeHtml(node.kind || 'node')} · ${escapeHtml(node.language || '')}`,
      `${escapeHtml(node.path || '')}`,
      `${escapeHtml(t('cluster'))}: ${escapeHtml(clusterKey || '-')}`,
    ];

    $('inspector-content').innerHTML = `<div>${summary.join('<br/>')}</div>`;
    $('inspector-raw').textContent = fmt({ node, runtime_source: state.meta.runtime_source });
    $('inspector-raw').classList.toggle('hidden', !state.inspectorRawVisible);
    $('inspector-raw-toggle').textContent = state.inspectorRawVisible ? t('hide_raw_json') : t('show_raw_json');
  };

  const renderBottom = () => {
    const data = {
      timeline: state.timeline,
      causality: state.causality,
      diff: state.diff,
      debug: {
        view_model_stats: state.viewModel?.stats,
        transform: state.transform,
        layer: effectiveLayer(),
        focus: {
          cluster: state.focusCluster,
          file: state.focusFile,
        },
        filters: {
          search: state.search,
          language: state.languageFilter,
          kind: state.kindFilter,
          edge: state.edgeFilter,
          diff_overlay: state.diffOverlay,
          show_calls: state.showCallsEdges,
        },
      },
    };

    $('bottom-content').textContent = fmt(data[state.activeTab] || data.timeline);
    ['timeline', 'causality', 'diff', 'debug'].forEach((name) => {
      const button = $(`tab-${name}`);
      if (!button) return;
      button.classList.toggle('active', state.activeTab === name);
    });
  };

  const renderBreadcrumb = () => {
    const breadcrumb = $('breadcrumb');
    const cluster = state.focusCluster;
    const file = state.focusFile;
    const parts = [];
    parts.push(`<button type="button" data-bc="all">All</button>`);
    if (cluster) {
      parts.push('>');
      parts.push(`<button type="button" data-bc="cluster">${escapeHtml(cluster)}</button>`);
    }
    if (file) {
      const name = file.split('/').pop() || file;
      parts.push('>');
      parts.push(`<span>${escapeHtml(name)}</span>`);
    }
    breadcrumb.innerHTML = parts.join(' ');

    breadcrumb.querySelectorAll('button[data-bc="all"]').forEach((el) => {
      el.addEventListener('click', () => {
        state.currentLayer = 'cluster';
        state.focusCluster = '';
        state.focusFile = '';
        state.selectedNodeId = '';
        state.userAdjustedView = false;
        fitGraphToView({ renderNow: true, markInteracted: false });
      });
    });
    breadcrumb.querySelectorAll('button[data-bc="cluster"]').forEach((el) => {
      el.addEventListener('click', () => {
        state.currentLayer = 'structural';
        state.focusFile = '';
        state.selectedNodeId = '';
        state.userAdjustedView = false;
        fitGraphToView({ renderNow: true, markInteracted: false });
      });
    });
  };

  const renderSearchResults = () => {
    const container = $('search-results');
    const q = state.search.trim().toLowerCase();
    if (!q) {
      container.textContent = '';
      return;
    }

    const nodes = Object.values(allNodesById());
    const matches = nodes
      .filter((node) => {
        const hay = [node.label, node.path, node.kind, node.folder_category]
          .map((value) => String(value || '').toLowerCase())
          .join(' ');
        return hay.includes(q);
      })
      .slice(0, 8);

    if (matches.length === 0) {
      container.textContent = 'No matches';
      return;
    }

    container.innerHTML = matches
      .map(
        (node) =>
          `<div class="search-item"><span>${escapeHtml(node.label)} <small>(${escapeHtml(node.kind)})</small></span><button data-go="${escapeHtml(node.id)}">Go</button></div>`
      )
      .join('');

    container.querySelectorAll('button[data-go]').forEach((el) => {
      el.addEventListener('click', () => {
        const nodeId = String(el.getAttribute('data-go') || '');
        const node = allNodesById()[nodeId];
        if (!node) return;
        state.currentLayer = 'detail';
        state.focusCluster = clusterKeyForNode(node);
        state.focusFile = String(node.path || '');
        state.selectedNodeId = nodeId;
        state.userAdjustedView = false;
        fitGraphToView({ renderNow: true, markInteracted: true });
      });
    });
  };

  const render = () => {
    if (!state.viewModel) return;

    const graph = graphData();
    const nodes = filterNodes(graph);
    const edges = filterEdges(graph, nodes);

    applyLayerTransform();
    renderClusters(graph, nodes);
    renderNodes(graph, nodes);
    renderSelectionOverlay(graph);
    drawEdges(graph, edges);
    renderInspector(graph);
    renderBottom();
    renderBreadcrumb();
    renderSearchResults();

    const stats = state.viewModel.stats || {};
    const layerLabel = effectiveLayer();
    $('stats-strip').textContent = `${layerLabel} · ${stats.node_count || 0} nodes · ${stats.edge_count || 0} edges · ${stats.cluster_count || 0} clusters`;
  };

  const graphBounds = () => {
    const graph = graphData();
    const nodes = graph.nodeIds.map((id) => graph.nodesById[id]).filter(Boolean);
    if (nodes.length === 0) return { minX: 0, minY: 0, width: 1600, height: 1000 };

    const minX = Math.min(...nodes.map((n) => Number(n.layout?.x || 0)));
    const minY = Math.min(...nodes.map((n) => Number(n.layout?.y || 0)));
    const maxX = Math.max(...nodes.map((n) => Number(n.layout?.x || 0) + Number(n.layout?.w || 0)));
    const maxY = Math.max(...nodes.map((n) => Number(n.layout?.y || 0) + Number(n.layout?.h || 0)));
    return {
      minX,
      minY,
      width: Math.max(1, maxX - minX),
      height: Math.max(1, maxY - minY),
    };
  };

  const fitGraphToView = ({ renderNow = true, markInteracted = false } = {}) => {
    if (!state.viewModel) return;
    const stage = $('graph-stage').getBoundingClientRect();
    if (stage.width <= 0 || stage.height <= 0) return;

    const bounds = graphBounds();
    const padding = 36;
    const targetW = Math.max(1, stage.width - padding * 2);
    const targetH = Math.max(1, stage.height - padding * 2);
    const nextScale = clamp(Math.min(targetW / bounds.width, targetH / bounds.height), 0.2, 1.8);

    state.transform.scale = nextScale;
    state.transform.x = stage.width / 2 - (bounds.minX + bounds.width / 2) * nextScale;
    state.transform.y = stage.height / 2 - (bounds.minY + bounds.height / 2) * nextScale;
    if (markInteracted) state.userAdjustedView = true;
    if (renderNow) render();
  };

  const fitSelected = ({ markInteracted = true } = {}) => {
    const id = state.selectedNodeId;
    const node = allNodesById()[id] || layerPayload('cluster').nodesById?.[id];
    if (!id || !node || !node.layout) return;

    const stage = $('graph-stage').getBoundingClientRect();
    const l = node.layout;
    state.transform.scale = clamp(state.transform.scale, 0.45, 1.5);
    state.transform.x = stage.width / 2 - (l.x + l.w / 2) * state.transform.scale;
    state.transform.y = stage.height / 2 - (l.y + l.h / 2) * state.transform.scale;
    if (markInteracted) state.userAdjustedView = true;
    render();
  };

  const setupFilters = () => {
    const setOptions = (el, values, labelKey, selectedValue) => {
      const options = [`<option value="">${t(labelKey)}</option>`];
      values.forEach((value) => {
        const selected = selectedValue === value ? ' selected' : '';
        options.push(`<option value="${escapeHtml(value)}"${selected}>${escapeHtml(value)}</option>`);
      });
      el.innerHTML = options.join('');
    };

    const filters = state.viewModel?.filters || {};
    setOptions($('language-filter'), filters.languages || [], 'all_languages', state.languageFilter);
    setOptions($('kind-filter'), filters.kinds || [], 'all_kinds', state.kindFilter);
    setOptions($('edge-filter'), filters.edge_types || [], 'all_edges', state.edgeFilter);
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
      const node = allNodesById()[selected];
      if (!selected || !node) {
        $('edit-status').textContent = 'Select a file/class node first.';
        return;
      }

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

    $('calls-toggle').addEventListener('change', (ev) => {
      state.showCallsEdges = Boolean(ev.target.checked);
      render();
    });

    $('lang-select').addEventListener('change', (ev) => {
      state.locale = String(ev.target.value || 'ko');
      applyI18n();
      setupFilters();
      render();
    });

    ['timeline', 'causality', 'diff', 'debug'].forEach((name) => {
      const btn = $(`tab-${name}`);
      btn.addEventListener('click', () => {
        state.activeTab = name;
        renderBottom();
      });
    });

    $('inspector-raw-toggle').addEventListener('click', () => {
      state.inspectorRawVisible = !state.inspectorRawVisible;
      render();
    });

    $('runtime-warning-toggle').addEventListener('click', () => {
      state.diagnosticsCollapsed = !state.diagnosticsCollapsed;
      renderRuntimeWarningBanner();
    });

    $('runtime-warning-jump').addEventListener('click', () => {
      const nodeId = findDiagnosticNodeId();
      if (!nodeId) return;
      state.currentLayer = 'detail';
      const node = allNodesById()[nodeId];
      state.focusCluster = node ? clusterKeyForNode(node) : '';
      state.focusFile = node ? String(node.path || '') : '';
      state.selectedNodeId = nodeId;
      state.userAdjustedView = false;
      fitGraphToView({ renderNow: true, markInteracted: true });
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
      state.userAdjustedView = true;
    });

    window.addEventListener('mousemove', (ev) => {
      if (!state.drag.active) return;
      state.transform.x = state.drag.ox + (ev.clientX - state.drag.sx);
      state.transform.y = state.drag.oy + (ev.clientY - state.drag.sy);
      applyLayerTransform();
      const graph = graphData();
      drawEdges(graph, filterEdges(graph, filterNodes(graph)));
    });

    window.addEventListener('mouseup', () => {
      state.drag.active = false;
    });

    stage.addEventListener(
      'wheel',
      (ev) => {
        ev.preventDefault();
        const delta = ev.deltaY < 0 ? 1.08 : 0.92;
        const old = state.transform.scale;
        const next = clamp(old * delta, 0.2, 2.0);

        const rect = stage.getBoundingClientRect();
        const cx = ev.clientX - rect.left;
        const cy = ev.clientY - rect.top;
        const wx = (cx - state.transform.x) / old;
        const wy = (cy - state.transform.y) / old;

        state.transform.scale = next;
        state.transform.x = cx - wx * next;
        state.transform.y = cy - wy * next;
        state.userAdjustedView = true;
        render();
      },
      { passive: false }
    );

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
        if (state.selectedNodeId) fitSelected({ markInteracted: true });
        else fitGraphToView({ renderNow: true, markInteracted: true });
      }
    });

    window.addEventListener('resize', () => {
      if (!state.userAdjustedView) {
        fitGraphToView({ renderNow: true, markInteracted: false });
      } else {
        render();
      }
    });
  };

  const bootstrap = async () => {
    state.i18n = await loadJson('i18n.json', 'i18n');
    state.meta = await loadJson('meta.json', 'meta');

    const [map, timeline, causality, diff] = await Promise.all([
      loadJson('map.json', 'map'),
      loadJson('timeline.json', 'timeline'),
      loadJson('causality.json', 'causality'),
      loadJson('diff.json', 'diff'),
    ]);

    state.map = map;
    state.timeline = timeline;
    state.causality = causality;
    state.diff = diff;

    try {
      state.viewModel = await loadJson('view_model.json', 'view_model');
    } catch (_) {
      state.viewModel = fallbackViewModel(map, timeline, causality, diff);
    }

    state.locale = state.meta.locale || 'ko';
    $('lang-select').value = state.locale;

    const defaults = state.viewModel?.ui_defaults || {};
    state.currentLayer = String(defaults.default_layer || 'cluster');
    state.focusCluster = String(defaults.focus_cluster || '').toLowerCase();
    state.showCallsEdges = false;
    $('calls-toggle').checked = state.showCallsEdges;

    applyI18n();
    setupFilters();
    setupEvents();
    setupEditDrawer();

    state.userAdjustedView = false;
    fitGraphToView({ renderNow: false, markInteracted: false });
    render();
  };

  bootstrap().catch((err) => {
    console.error('Visualizer bootstrap failed', err);
    const el = $('inspector-content');
    if (el) {
      el.textContent = `Visualizer bootstrap failed:\n${String(err)}\n\nOpen offline.html when file protocol blocks fetch.`;
    }
  });
})();
