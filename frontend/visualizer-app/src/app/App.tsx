import { useEffect, useMemo, useRef, useState } from 'react';
import Graph from 'graphology';
import Sigma from 'sigma';

import { buildVisibleGraph } from '../graph/visible';
import { useVisualizerStore } from '../state/useVisualizerStore';
import type { GraphBundle, SearchResultItem, VisualizerPayload, ViewModelNode } from '../types/visualizer';

function nodeColor(kind: string): string {
  if (kind === 'cluster') return '#6bc8ff';
  if (kind === 'file') return '#7eb5ff';
  if (kind === 'class') return '#8ad29a';
  if (kind === 'function') return '#e5af63';
  if (kind === 'signal') return '#f47fb0';
  if (kind === 'error') return '#ff6a80';
  if (kind === 'warning') return '#ffd36c';
  return '#9fb1d8';
}

function nodeSize(kind: string): number {
  if (kind === 'cluster') return 12;
  if (kind === 'file' || kind === 'class') return 7;
  if (kind === 'function') return 5;
  return 6;
}

function ratioToMode(ratio: number): 'cluster' | 'structural' | 'detail' {
  if (ratio > 1.35) return 'cluster';
  if (ratio > 0.75) return 'structural';
  return 'detail';
}

function shortestPathUndirected(
  adjacency: { in?: Record<string, string[]>; out?: Record<string, string[]> } | undefined,
  start: string,
  goal: string
): string[] {
  if (!start || !goal) return [];
  if (start === goal) return [start];
  const visited = new Set<string>([start]);
  const parent = new Map<string, string>();
  const queue: string[] = [start];

  while (queue.length > 0) {
    const node = queue.shift() as string;
    const neighbors = [...(adjacency?.in?.[node] ?? []), ...(adjacency?.out?.[node] ?? [])];
    for (const next of neighbors) {
      if (visited.has(next)) continue;
      visited.add(next);
      parent.set(next, node);
      if (next === goal) {
        const path: string[] = [goal];
        let cursor = goal;
        while (parent.has(cursor)) {
          cursor = parent.get(cursor) as string;
          path.push(cursor);
          if (cursor === start) break;
        }
        return path.reverse();
      }
      queue.push(next);
    }
  }
  return [];
}

function useNodeLookup(bundle: GraphBundle | null) {
  return useMemo(() => {
    const lookup = new Map<string, { label: string; path: string; kind: string; clusterId: string }>();
    if (bundle == null) return lookup;
    const pool = bundle.string_pool ?? [];
    for (const node of bundle.nodes ?? []) {
      lookup.set(node.id, {
        label: String(pool[node.label_i] ?? node.id),
        path: String(pool[node.path_i] ?? ''),
        kind: node.kind,
        clusterId: node.cluster_id,
      });
    }
    return lookup;
  }, [bundle]);
}

function summarizeNode(node: ViewModelNode | undefined, fallback: { label: string; path: string; kind: string } | undefined) {
  return {
    id: node?.id ?? fallback?.label ?? '',
    kind: node?.kind ?? fallback?.kind ?? 'unknown',
    label: node?.label ?? fallback?.label ?? '',
    path: node?.path ?? fallback?.path ?? '',
    inDegree: Number(node?.metrics?.in_degree ?? 0),
    outDegree: Number(node?.metrics?.out_degree ?? 0),
    loc: Number(node?.metrics?.loc ?? 0),
    metadata: node?.metadata ?? {},
  };
}

function clusterDisplayName(clusterId: string, payload: VisualizerPayload): string {
  const clusters = payload.view_model?.clusters ?? [];
  const cluster = clusters.find((item) => String(item.id) === clusterId);
  if (cluster) return String(cluster.title || cluster.key || clusterId);
  return clusterId.replace('cluster::', '');
}

export function App() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const minimapRef = useRef<HTMLCanvasElement | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const [fps, setFps] = useState(0);

  const payload = useVisualizerStore((s) => s.payload);
  const bundle = useVisualizerStore((s) => s.bundle);
  const viewModel = useVisualizerStore((s) => s.viewModel);
  const mode = useVisualizerStore((s) => s.mode);
  const callsEnabled = useVisualizerStore((s) => s.callsEnabled);
  const focusScope = useVisualizerStore((s) => s.focusScope);
  const selectedNodeId = useVisualizerStore((s) => s.selectedNodeId);
  const selectedClusterId = useVisualizerStore((s) => s.selectedClusterId);
  const kHop = useVisualizerStore((s) => s.kHop);
  const pathNodeIds = useVisualizerStore((s) => s.pathNodeIds);
  const edgeTypeEnabled = useVisualizerStore((s) => s.edgeTypeEnabled);
  const searchQuery = useVisualizerStore((s) => s.searchQuery);
  const searchResults = useVisualizerStore((s) => s.searchResults);
  const searchIndex = useVisualizerStore((s) => s.searchIndex);
  const visibleNodeCount = useVisualizerStore((s) => s.visibleNodeCount);
  const visibleEdgeCount = useVisualizerStore((s) => s.visibleEdgeCount);
  const edgesSampled = useVisualizerStore((s) => s.edgesSampled);
  const toast = useVisualizerStore((s) => s.toast);
  const rawJsonOpen = useVisualizerStore((s) => s.rawJsonOpen);
  const overlay = useVisualizerStore((s) => s.overlay);
  const diagnosticsCollapsed = useVisualizerStore((s) => s.diagnosticsCollapsed);

  const setMode = useVisualizerStore((s) => s.setMode);
  const setSearchQuery = useVisualizerStore((s) => s.setSearchQuery);
  const setSearchResults = useVisualizerStore((s) => s.setSearchResults);
  const setSearchIndex = useVisualizerStore((s) => s.setSearchIndex);
  const selectNode = useVisualizerStore((s) => s.selectNode);
  const selectCluster = useVisualizerStore((s) => s.selectCluster);
  const drillToCluster = useVisualizerStore((s) => s.drillToCluster);
  const drillToDetail = useVisualizerStore((s) => s.drillToDetail);
  const showPathScope = useVisualizerStore((s) => s.showPathScope);
  const toggleCalls = useVisualizerStore((s) => s.toggleCalls);
  const toggleEdgeType = useVisualizerStore((s) => s.toggleEdgeType);
  const setVisibleMetrics = useVisualizerStore((s) => s.setVisibleMetrics);
  const goBack = useVisualizerStore((s) => s.goBack);
  const goForward = useVisualizerStore((s) => s.goForward);
  const setToast = useVisualizerStore((s) => s.setToast);
  const toggleRawJson = useVisualizerStore((s) => s.toggleRawJson);
  const toggleDiagnosticsCollapsed = useVisualizerStore((s) => s.toggleDiagnosticsCollapsed);

  const nodeLookup = useNodeLookup(bundle);

  const visible = useMemo(() => {
    if (viewModel == null) return { nodes: [], edges: [], sampled: false };
    return buildVisibleGraph({
      viewModel,
      mode,
      focusScope,
      selectedNodeId,
      selectedClusterId,
      kHop,
      pathNodeIds,
      callsEnabled,
      edgeTypeEnabled,
    });
  }, [viewModel, mode, focusScope, selectedNodeId, selectedClusterId, kHop, pathNodeIds, callsEnabled, edgeTypeEnabled]);

  const selectedNode = useMemo(() => {
    const fromView = viewModel?.nodesById?.[selectedNodeId];
    const fromBundle = nodeLookup.get(selectedNodeId);
    return summarizeNode(fromView, fromBundle);
  }, [viewModel, nodeLookup, selectedNodeId]);

  const clusterCards = useMemo(() => {
    if (bundle == null) return [];
    const pool = bundle.string_pool ?? [];
    return (bundle.clusters ?? [])
      .map((cluster) => {
        const label = String(pool[cluster.label_i] ?? cluster.id);
        return {
          id: cluster.id,
          label,
          size: Number(cluster.metrics?.size ?? cluster.node_ids.length),
          external: Number(cluster.metrics?.external_w ?? 0),
          hot: Number(cluster.metrics?.hot ?? 0),
        };
      })
      .sort((a, b) => b.size - a.size);
  }, [bundle]);

  const runtimeDiagnostics = useMemo(() => {
    const diagnostics = payload.meta?.runtime_diagnostics;
    return Array.isArray(diagnostics) ? diagnostics : [];
  }, [payload.meta]);

  const activeDiagnostic = useMemo(() => {
    if (visibleEdgeCount > 12000) {
      return {
        level: 'warning',
        code: 'density_over_budget',
        message: `과밀도 감지: 현재 ${visibleEdgeCount.toLocaleString()} edges 표시 중`,
        hint: 'calls를 끄고 선택 범위를 줄여 가독성을 복구하세요.',
      };
    }
    if (runtimeDiagnostics.length > 0) {
      const first = runtimeDiagnostics[0] as Record<string, unknown>;
      return {
        level: String(first.level ?? 'warning'),
        code: String(first.code ?? 'runtime_diagnostic'),
        message: String(first.message ?? '런타임 진단 이슈가 감지되었습니다.'),
        hint: String(first.hint ?? '원인 확인 후 점프 버튼으로 관련 노드를 탐색하세요.'),
      };
    }
    return null;
  }, [runtimeDiagnostics, visibleEdgeCount]);

  useEffect(() => {
    setVisibleMetrics(visible.nodes.length, visible.edges.length, visible.sampled);
  }, [setVisibleMetrics, visible.nodes.length, visible.edges.length, visible.sampled]);

  useEffect(() => {
    if (toast === '') return;
    const timer = window.setTimeout(() => setToast(''), 2200);
    return () => window.clearTimeout(timer);
  }, [toast, setToast]);

  useEffect(() => {
    if (bundle == null) return;
    const worker = new Worker(new URL('../workers/search.worker.ts', import.meta.url), { type: 'module' });
    workerRef.current = worker;
    worker.postMessage({
      type: 'index',
      payload: {
        stringPool: bundle.string_pool ?? [],
        items: bundle.search_index?.items ?? [],
      },
    });
    worker.onmessage = (event: MessageEvent) => {
      const data = event.data as { type: string; payload?: unknown };
      if (data.type !== 'search-result') return;
      const rows = Array.isArray(data.payload) ? data.payload : [];
      const mapped: SearchResultItem[] = rows.map((row) => {
        const item = row as Record<string, unknown>;
        return {
          nodeId: String(item.nodeId ?? ''),
          kind: String(item.kind ?? ''),
          label: String(item.label ?? ''),
          path: String(item.path ?? ''),
        };
      });
      setSearchResults(mapped);
    };
    return () => {
      worker.terminate();
      workerRef.current = null;
    };
  }, [bundle, setSearchResults]);

  useEffect(() => {
    if (workerRef.current == null) return;
    workerRef.current.postMessage({ type: 'search', payload: { query: searchQuery, limit: 120 } });
  }, [searchQuery]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isInput = target?.tagName === 'INPUT' || target?.tagName === 'TEXTAREA';

      if ((event.key === '/' && !isInput) || ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k')) {
        event.preventDefault();
        searchRef.current?.focus();
        return;
      }
      if (event.altKey && event.key === 'ArrowLeft') {
        event.preventDefault();
        goBack();
        return;
      }
      if (event.altKey && event.key === 'ArrowRight') {
        event.preventDefault();
        goForward();
        return;
      }
      if (event.key.toLowerCase() === 'c' && !isInput) {
        event.preventDefault();
        toggleCalls();
        return;
      }
      if (event.key.toLowerCase() === 'f' && !isInput) {
        event.preventDefault();
        const sigma = sigmaRef.current;
        if (sigma == null || selectedNodeId === '') return;
        const attrs = sigma.getGraph().getNodeAttributes(selectedNodeId) as { x?: number; y?: number };
        if (attrs && Number.isFinite(attrs.x) && Number.isFinite(attrs.y)) {
          sigma.getCamera().animate({ x: Number(attrs.x), y: Number(attrs.y), ratio: 0.45 }, { duration: 280 });
        }
        return;
      }
      if (event.key === 'Escape') {
        setSearchQuery('');
        setSearchResults([]);
      }
    };

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [goBack, goForward, selectedNodeId, setSearchQuery, setSearchResults, toggleCalls]);

  useEffect(() => {
    const canvas = minimapRef.current;
    if (canvas == null) return;
    const ctx = canvas.getContext('2d');
    if (ctx == null) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#0f1730';
    ctx.fillRect(0, 0, width, height);
    if (visible.nodes.length === 0) return;

    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;

    for (const node of visible.nodes) {
      const x = Number(node.layout?.x ?? 0);
      const y = Number(node.layout?.y ?? 0);
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x);
      maxY = Math.max(maxY, y);
    }

    const spanX = Math.max(1, maxX - minX);
    const spanY = Math.max(1, maxY - minY);

    for (const node of visible.nodes) {
      const x = Number(node.layout?.x ?? 0);
      const y = Number(node.layout?.y ?? 0);
      const nx = ((x - minX) / spanX) * (width - 8) + 4;
      const ny = ((y - minY) / spanY) * (height - 8) + 4;
      ctx.fillStyle = node.id === selectedNodeId ? '#75ffd9' : '#5a87d7';
      ctx.fillRect(nx, ny, 2, 2);
    }

    ctx.strokeStyle = '#2f5aa0';
    ctx.strokeRect(1, 1, width - 2, height - 2);
  }, [visible.nodes, selectedNodeId]);

  useEffect(() => {
    const container = containerRef.current;
    if (container == null) return;
    if (viewModel == null) return;

    const graph = new Graph();
    for (const node of visible.nodes) {
      const x = Number(node.layout?.x ?? 0);
      const y = Number(node.layout?.y ?? 0);
      const isSelected = node.id === selectedNodeId || node.id === selectedClusterId;
      const label = node.label || nodeLookup.get(node.id)?.label || node.id;
      graph.addNode(node.id, {
        x,
        y,
        size: isSelected ? nodeSize(node.kind) + 4 : nodeSize(node.kind),
        label,
        color: isSelected ? '#88ffe0' : nodeColor(node.kind),
      });
    }

    for (const edge of visible.edges) {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
      const key = edge.id || `${edge.source}->${edge.target}:${edge.edge_type}`;
      if (graph.hasEdge(key)) continue;
      graph.addEdgeWithKey(key, edge.source, edge.target, {
        size: Math.max(0.5, Math.min(5, Number(edge.confidence ?? 1))),
        color: edge.edge_type === 'calls' ? '#ff9a7c' : '#5b86d7',
      });
    }

    sigmaRef.current?.kill();
    const sigma = new Sigma(graph, container, {
      renderLabels: mode !== 'cluster',
      renderEdgeLabels: false,
      labelDensity: 0.08,
      labelGridCellSize: 100,
      minCameraRatio: 0.03,
      maxCameraRatio: 3.0,
      allowInvalidContainer: true,
    });
    sigmaRef.current = sigma;

    const camera = sigma.getCamera();
    camera.on('updated', () => {
      const ratio = camera.getState().ratio;
      const semanticMode = ratioToMode(ratio);
      if (semanticMode !== mode) {
        useVisualizerStore.getState().setMode(semanticMode);
      }
    });

    sigma.on('clickNode', ({ node }) => {
      const id = String(node);
      const vmNode = viewModel.nodesById?.[id];
      if (vmNode?.kind === 'cluster' || id.startsWith('cluster::')) {
        selectCluster(id);
      } else {
        selectNode(id);
      }
    });

    sigma.on('doubleClickNode', ({ node }) => {
      const id = String(node);
      const vmNode = viewModel.nodesById?.[id];
      if (vmNode?.kind === 'cluster' || id.startsWith('cluster::')) {
        drillToCluster(id);
      } else {
        drillToDetail(id, 2);
      }
    });

    sigma.on('clickStage', () => {
      useVisualizerStore.setState({ selectedNodeId: '', selectedClusterId: '' });
    });

    if (selectedNodeId && graph.hasNode(selectedNodeId)) {
      const attrs = graph.getNodeAttributes(selectedNodeId) as { x: number; y: number };
      camera.animate({ x: attrs.x, y: attrs.y, ratio: 0.45 }, { duration: 280 });
    } else if (selectedClusterId && graph.hasNode(selectedClusterId)) {
      const attrs = graph.getNodeAttributes(selectedClusterId) as { x: number; y: number };
      camera.animate({ x: attrs.x, y: attrs.y, ratio: 0.7 }, { duration: 280 });
    } else {
      camera.animatedReset({ duration: 220 });
    }

    return () => {
      sigma.kill();
      sigmaRef.current = null;
    };
  }, [visible.nodes, visible.edges, mode, selectedNodeId, selectedClusterId, viewModel, nodeLookup, selectNode, selectCluster, drillToCluster, drillToDetail]);

  const onSearchFocus = (item: SearchResultItem) => {
    setSearchQuery(item.label);
    selectNode(item.nodeId);
    setSearchIndex(Math.max(0, searchResults.findIndex((row) => row.nodeId === item.nodeId)));
    const sigma = sigmaRef.current;
    if (sigma == null) return;
    if (!sigma.getGraph().hasNode(item.nodeId)) {
      useVisualizerStore.getState().drillToDetail(item.nodeId, 2);
      return;
    }
    const attrs = sigma.getGraph().getNodeAttributes(item.nodeId) as { x?: number; y?: number };
    if (attrs && Number.isFinite(attrs.x) && Number.isFinite(attrs.y)) {
      sigma.getCamera().animate({ x: Number(attrs.x), y: Number(attrs.y), ratio: 0.4 }, { duration: 260 });
    }
  };

  const onAutoFixDensity = () => {
    if (callsEnabled) toggleCalls();
    useVisualizerStore.setState({ mode: 'structural', focusScope: 'clusterSubgraph', kHop: 2, toast: '과밀도 자동 수정이 적용되었습니다.' });
  };

  const onShowPaths = () => {
    if (viewModel == null || selectedNodeId === '') {
      setToast('경로를 보려면 먼저 노드를 선택하세요.');
      return;
    }
    const entries = Object.values(viewModel.nodesById ?? {});
    if (entries.length === 0) {
      setToast('경로 계산 대상이 없습니다.');
      return;
    }
    const hub = entries
      .filter((item) => item.id !== selectedNodeId)
      .sort((a, b) => {
        const aDegree = Number(a.metrics?.in_degree ?? 0) + Number(a.metrics?.out_degree ?? 0);
        const bDegree = Number(b.metrics?.in_degree ?? 0) + Number(b.metrics?.out_degree ?? 0);
        return bDegree - aDegree;
      })[0];
    if (hub == null) {
      setToast('허브 노드를 찾지 못했습니다.');
      return;
    }
    const path = shortestPathUndirected(viewModel.adjacency, selectedNodeId, hub.id);
    if (path.length < 2) {
      setToast('경로를 찾지 못했습니다.');
      return;
    }
    showPathScope(path);
    setToast(`Path view: ${path.length} nodes`);
  };

  const breadcrumb = useMemo(() => {
    const parts = ['All'];
    if (selectedClusterId) parts.push(clusterDisplayName(selectedClusterId, payload));
    if (selectedNodeId) parts.push(selectedNode.label || selectedNodeId);
    return parts;
  }, [selectedClusterId, selectedNodeId, selectedNode, payload]);

  const totalNodes = Number(bundle?.meta?.node_count ?? (bundle?.nodes?.length ?? 0));
  const totalEdges = Number(bundle?.meta?.edge_count ?? ((bundle?.edges?.length ?? 0) + (bundle?.calls_edges?.length ?? 0)));
  const clusterCount = Number(bundle?.clusters?.length ?? 0);

  useEffect(() => {
    let raf = 0;
    let frames = 0;
    let windowStart = performance.now();

    const tick = (now: number) => {
      frames += 1;
      const elapsed = now - windowStart;
      if (elapsed >= 1000) {
        setFps(Math.round((frames * 1000) / elapsed));
        frames = 0;
        windowStart = now;
      }
      raf = window.requestAnimationFrame(tick);
    };
    raf = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(raf);
  }, []);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="logo">Project Visualizer</div>
        <input
          ref={searchRef}
          className="search"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && searchResults.length > 0) {
              onSearchFocus(searchResults[Math.max(0, searchIndex)]);
            }
          }}
          placeholder="Search nodes, paths, types..."
        />
        <select className="mode" value={mode} onChange={(event) => setMode(event.target.value as 'cluster' | 'structural' | 'detail')}>
          <option value="cluster">Cluster</option>
          <option value="structural">Structural</option>
          <option value="detail">Detail</option>
        </select>
        <label className="toggle"><input type="checkbox" checked={callsEnabled} onChange={() => toggleCalls()} /> Calls</label>
      </header>

      <div className="kpi-strip">
        <span>Nodes {totalNodes.toLocaleString()}</span>
        <span>Edges {totalEdges.toLocaleString()}</span>
        <span>Clusters {clusterCount.toLocaleString()}</span>
        <span>Visible {visibleNodeCount.toLocaleString()} / {totalNodes.toLocaleString()}</span>
        <span>Visible edges {visibleEdgeCount.toLocaleString()}</span>
        <span>FPS {fps}</span>
        {edgesSampled ? <span className="badge">Edges sampled</span> : null}
      </div>

      {activeDiagnostic != null ? (
        <div className="diag-banner">
          <div>
            <strong>{activeDiagnostic.message}</strong>
            <div>{activeDiagnostic.hint}</div>
          </div>
          <div className="diag-actions">
            {activeDiagnostic.code === 'density_over_budget' ? (
              <button onClick={onAutoFixDensity}>Fix Now</button>
            ) : null}
            <button onClick={toggleDiagnosticsCollapsed}>{diagnosticsCollapsed ? 'Expand' : 'Collapse'}</button>
          </div>
        </div>
      ) : null}

      <div className="content-grid">
        <aside className="left-panel">
          <div className="breadcrumb">{breadcrumb.join(' > ')}</div>
          <div className="cluster-list">
            {clusterCards.map((cluster) => (
              <button key={cluster.id} className={`cluster-card ${selectedClusterId === cluster.id ? 'active' : ''}`} onClick={() => selectCluster(cluster.id)} onDoubleClick={() => drillToCluster(cluster.id)}>
                <div className="cluster-title">{cluster.label}</div>
                <div className="cluster-meta">{cluster.size} nodes · ext {cluster.external.toFixed(0)} · hot {cluster.hot.toFixed(2)}</div>
              </button>
            ))}
          </div>

          <div className="quick-filters">
            <div className="filter-title">Quick Filters</div>
            {Object.keys(edgeTypeEnabled).sort().map((edgeType) => (
              <label key={edgeType}>
                <input type="checkbox" checked={Boolean(edgeTypeEnabled[edgeType])} onChange={() => toggleEdgeType(edgeType)} /> {edgeType}
              </label>
            ))}
          </div>
        </aside>

        <main className="canvas-panel">
          <div ref={containerRef} className="graph-canvas" />
          <canvas ref={minimapRef} className="minimap" width={160} height={110} />
        </main>

        <aside className="right-panel">
          <h3>Detail Inspector</h3>
          {selectedNode.id === '' ? (
            <p className="muted">노드 또는 클러스터를 선택하면 요약이 표시됩니다.</p>
          ) : (
            <>
              <div className="summary-card">
                <div className="summary-title">{selectedNode.label || selectedNode.id}</div>
                <div>Kind: {selectedNode.kind}</div>
                <div>Path: {selectedNode.path || '-'}</div>
                <div>Degree: in {selectedNode.inDegree} / out {selectedNode.outDegree}</div>
                <div>LOC: {selectedNode.loc}</div>
              </div>
              <div className="inspector-actions">
                <button onClick={() => selectedNodeId && drillToDetail(selectedNodeId, 1)}>1-hop</button>
                <button onClick={() => selectedNodeId && drillToDetail(selectedNodeId, 2)}>2-hop</button>
                <button onClick={() => selectedNodeId && drillToDetail(selectedNodeId, 3)}>3-hop</button>
                <button onClick={onShowPaths}>Show paths</button>
              </div>
              <button className="raw-toggle" onClick={toggleRawJson}>{rawJsonOpen ? 'Hide Raw JSON' : 'Show Raw JSON'}</button>
              {rawJsonOpen ? <pre className="raw-json">{JSON.stringify(selectedNode.metadata, null, 2)}</pre> : null}
            </>
          )}
        </aside>
      </div>

      {(overlay === 'searchOpen' || searchQuery.trim() !== '') ? (
        <section className="search-drawer">
          <div className="drawer-head">
            <strong>{searchResults.length} results</strong>
            <span>for &quot;{searchQuery}&quot;</span>
          </div>
          <div className="result-list">
            {searchResults.length === 0 ? <div className="muted">검색 결과가 없습니다.</div> : null}
            {searchResults.map((item, index) => (
              <div key={`${item.nodeId}-${index}`} className={`result-row ${index === searchIndex ? 'active' : ''}`}>
                <div className="result-text">
                  <div>{item.label}</div>
                  <small>{item.kind} · {item.path}</small>
                </div>
                <div className="result-actions">
                  <button onClick={() => onSearchFocus(item)}>Focus</button>
                  <button onClick={() => selectNode(item.nodeId)}>Pin</button>
                  <button onClick={() => drillToDetail(item.nodeId, 2)}>2-hop</button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {toast !== '' ? <div className="toast">{toast}</div> : null}
    </div>
  );
}
