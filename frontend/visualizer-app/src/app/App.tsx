import { useEffect, useMemo, useRef, useState } from 'react';

import { BoardRenderer } from '../graph/renderers/board_renderer';
import { Canvas2DRenderer } from '../graph/renderers/canvas2d_renderer';
import { SigmaRenderer } from '../graph/renderers/sigma_renderer';
import type {
  GraphRenderer,
  GraphRendererCallbacks,
  RenderFrame,
  RendererBackend,
} from '../graph/renderers/types';
import { buildVisibleGraph } from '../graph/visible';
import { useVisualizerStore } from '../state/useVisualizerStore';
import type {
  BoardModel,
  BoardModelV2,
  BoardV2LegendItem,
  GraphBundle,
  SearchResultItem,
  ViewModelEdge,
  ViewModelNode,
  VisualizerMode,
  VisualizerPayload,
} from '../types/visualizer';

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

function normalizeNodePositions(nodes: ViewModelNode[]): Map<string, { x: number; y: number }> {
  const result = new Map<string, { x: number; y: number }>();
  if (nodes.length === 0) return result;

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  for (const node of nodes) {
    const x = Number(node.layout?.x ?? 0);
    const y = Number(node.layout?.y ?? 0);
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }

  const centerX = (minX + maxX) / 2;
  const centerY = (minY + maxY) / 2;
  const spanX = Math.max(1, maxX - minX);
  const spanY = Math.max(1, maxY - minY);
  const scale = Math.max(spanX, spanY) / 2;

  for (const node of nodes) {
    const x = Number(node.layout?.x ?? 0);
    const y = Number(node.layout?.y ?? 0);
    result.set(node.id, {
      x: (x - centerX) / scale,
      y: (y - centerY) / scale,
    });
  }
  return result;
}

function shortestPathUndirected(
  adjacency: { in?: Record<string, string[]>; out?: Record<string, string[]> } | undefined,
  start: string,
  goal: string,
): string[] {
  if (start === '' || goal === '') return [];
  if (start === goal) return [start];

  const visited = new Set<string>([start]);
  const parent = new Map<string, string>();
  const queue: string[] = [start];

  while (queue.length > 0) {
    const current = queue.shift() as string;
    const neighbors = [...(adjacency?.in?.[current] ?? []), ...(adjacency?.out?.[current] ?? [])];
    for (const next of neighbors) {
      if (visited.has(next)) continue;
      visited.add(next);
      parent.set(next, current);
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

function supportsWebGL(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch (_error) {
    return false;
  }
}

function shouldUseWebglDetail(): boolean {
  try {
    const params = new URLSearchParams(window.location.search);
    return params.get('renderer') === 'webgl';
  } catch (_error) {
    return false;
  }
}

function classifyRendererError(message: string): string {
  const lowered = message.toLowerCase();
  if (lowered.includes('already exists')) return 'duplicate_edges';
  if (lowered.includes('webgl') || lowered.includes('blendfunc')) return 'webgl_init_failed';
  return 'render_exception';
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

function summarizeNode(
  node: ViewModelNode | undefined,
  fallback: { label: string; path: string; kind: string } | undefined,
) {
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

function pickClusterActionNode(boardModel: BoardModel | null, boardModelV2: BoardModelV2 | null, clusterId: string): string {
  if (clusterId.trim() === '') return '';
  if (boardModelV2 != null) {
    const lane = boardModelV2.lanes.find((item) => String(item.id) === clusterId);
    if (lane != null && Array.isArray(lane.cards) && lane.cards.length > 0) {
      const sorted = [...lane.cards].sort((a, b) => {
        const aDegree = Number(a.stats?.in ?? 0) + Number(a.stats?.out ?? 0);
        const bDegree = Number(b.stats?.in ?? 0) + Number(b.stats?.out ?? 0);
        if (bDegree !== aDegree) return bDegree - aDegree;
        return String(a.title).localeCompare(String(b.title));
      });
      return String(sorted[0]?.id ?? '').trim();
    }
  }
  if (boardModel == null) return '';
  const hotspot = (boardModel.hotspots ?? []).find((item) => String(item.cluster_id ?? '') === clusterId);
  if (hotspot && String(hotspot.node_id).trim() !== '') return String(hotspot.node_id);
  const cluster = (boardModel.clusters ?? []).find((item) => item.id === clusterId);
  if (cluster == null || !Array.isArray(cluster.cards) || cluster.cards.length === 0) return '';
  const sorted = [...cluster.cards].sort((a, b) => {
    const aDegree = Number(a.stats?.in ?? 0) + Number(a.stats?.out ?? 0);
    const bDegree = Number(b.stats?.in ?? 0) + Number(b.stats?.out ?? 0);
    if (bDegree !== aDegree) return bDegree - aDegree;
    return String(a.title).localeCompare(String(b.title));
  });
  return String(sorted[0]?.id ?? '').trim();
}

function pickBestClusterId(clusterCards: Array<{ id: string }>, selectedClusterId: string): string {
  if (selectedClusterId.trim() !== '') return selectedClusterId;
  return String(clusterCards[0]?.id ?? '').trim();
}

function getBoardModel(payload: VisualizerPayload): BoardModel | null {
  const fromView = payload.view_model?.board_model;
  if (fromView && Array.isArray(fromView.clusters) && Array.isArray(fromView.links) && Array.isArray(fromView.hotspots)) {
    return fromView;
  }
  const fromBundle = payload.graph_bundle?.board_model;
  if (fromBundle && Array.isArray(fromBundle.clusters) && Array.isArray(fromBundle.links) && Array.isArray(fromBundle.hotspots)) {
    return fromBundle;
  }
  return null;
}

function getBoardModelV2(payload: VisualizerPayload): BoardModelV2 | null {
  const fromView = payload.view_model?.board_model_v2;
  if (fromView && Array.isArray(fromView.lanes) && Array.isArray(fromView.links) && Array.isArray(fromView.legend)) {
    return fromView;
  }
  const fromBundle = payload.graph_bundle?.board_model_v2;
  if (fromBundle && Array.isArray(fromBundle.lanes) && Array.isArray(fromBundle.links) && Array.isArray(fromBundle.legend)) {
    return fromBundle;
  }
  return null;
}

function legendColorForType(edgeType: string, legend: BoardV2LegendItem[]): string {
  const item = legend.find((row) => String(row.edge_type) === edgeType);
  if (item != null && String(item.color).trim() !== '') return String(item.color);
  if (edgeType === 'extends') return '#8ad29a';
  if (edgeType === 'emits') return '#f3b06d';
  if (edgeType === 'loads') return '#b7a2ff';
  if (edgeType === 'calls') return '#ff8e74';
  return '#6bc8ff';
}

function dominantEdgeType(typeBreakdown: Record<string, number>): string {
  const entries = Object.entries(typeBreakdown ?? {});
  if (entries.length === 0) return 'contains';
  entries.sort((a, b) => Number(b[1]) - Number(a[1]));
  return String(entries[0][0] ?? 'contains');
}

function legendStyleForType(edgeType: string, legend: BoardV2LegendItem[]): string {
  const item = legend.find((row) => String(row.edge_type) === edgeType);
  if (item != null && String(item.style).trim() !== '') return String(item.style);
  if (edgeType === 'emits') return 'dashed';
  if (edgeType === 'loads') return 'dotted';
  return 'solid';
}

function defaultLegend(): BoardV2LegendItem[] {
  return [
    { edge_type: 'contains', label: 'Contains', color: '#6bc8ff', style: 'solid', default_visible: true },
    { edge_type: 'extends', label: 'Extends', color: '#8ad29a', style: 'solid', default_visible: true },
    { edge_type: 'emits', label: 'Emits', color: '#f3b06d', style: 'dashed', default_visible: false },
    { edge_type: 'loads', label: 'Loads', color: '#b7a2ff', style: 'dotted', default_visible: false },
    { edge_type: 'calls', label: 'Calls', color: '#ff8e74', style: 'solid', default_visible: false },
  ];
}

function displayCardTitle(node: ViewModelNode, fallback: { label: string; path: string } | undefined): string {
  const rawLabel = String(node.label ?? fallback?.label ?? '').trim();
  if (rawLabel !== '' && rawLabel !== '(anonymous)') return rawLabel;
  const path = String(node.path ?? fallback?.path ?? '').trim();
  if (path !== '') {
    const parts = path.split('/');
    return String(parts[parts.length - 1] ?? path);
  }
  return String(node.id);
}

function boardFrameFromDetailVisible(args: {
  visibleNodes: ViewModelNode[];
  visibleEdges: ViewModelEdge[];
  selectedNodeId: string;
  selectedClusterId: string;
  payload: VisualizerPayload;
  nodeLookup: Map<string, { label: string; path: string; kind: string; clusterId: string }>;
  legend: BoardV2LegendItem[];
}): RenderFrame['board'] {
  const { visibleNodes, visibleEdges, selectedNodeId, selectedClusterId, payload, nodeLookup, legend } = args;
  const nodes = visibleNodes.filter((node) => String(node.kind) !== 'cluster');
  const renderLegend = legend.map((item) => ({
    edgeType: String(item.edge_type),
    label: String(item.label),
    color: String(item.color),
    style: String(item.style),
    defaultVisible: Boolean(item.default_visible),
  }));
  if (nodes.length === 0) return { clusters: [], links: [], legend: renderLegend };

  const nodeById = new Map<string, ViewModelNode>();
  for (const node of nodes) nodeById.set(String(node.id), node);
  const nodeIdSet = new Set(nodes.map((node) => String(node.id)));

  const basename = (path: string): string => {
    const trimmed = path.trim();
    if (trimmed === '') return '';
    const parts = trimmed.split('/');
    return String(parts[parts.length - 1] ?? trimmed);
  };

  const groupKeyForNode = (node: ViewModelNode): string => {
    const lookup = nodeLookup.get(String(node.id));
    const path = String(node.path ?? lookup?.path ?? '').trim();
    if (path !== '') return `path::${path}`;
    return `id::${String(node.id)}`;
  };

  type DetailGroup = {
    key: string;
    path: string;
    nodes: ViewModelNode[];
    representative: ViewModelNode;
    cardId: string;
    kind: string;
    title: string;
    inDegree: number;
    outDegree: number;
    loc: number;
    functions: number;
    classes: number;
    signals: number;
    relation: string;
    hop: number;
  };

  const representativeRank = (node: ViewModelNode): [number, number, number] => {
    const kind = String(node.kind ?? '').toLowerCase();
    const kindRank =
      kind === 'file' ? 0 :
        kind === 'class' ? 1 :
          kind === 'scene' ? 2 :
            kind === 'resource' ? 3 :
              kind === 'signal' ? 4 :
                kind === 'function' ? 8 : 5;
    const degree = Number(node.metrics?.in_degree ?? 0) + Number(node.metrics?.out_degree ?? 0);
    const loc = Number(node.metrics?.loc ?? 0);
    return [kindRank, -degree, -loc];
  };

  const groupsMap = new Map<string, { key: string; path: string; nodes: ViewModelNode[] }>();
  for (const node of nodes) {
    const key = groupKeyForNode(node);
    const lookup = nodeLookup.get(String(node.id));
    const path = String(node.path ?? lookup?.path ?? '').trim();
    if (!groupsMap.has(key)) {
      groupsMap.set(key, { key, path, nodes: [] });
    }
    groupsMap.get(key)?.nodes.push(node);
  }

  const adjacency = new Map<string, Set<string>>();
  const directIn = new Set<string>();
  const directOut = new Set<string>();
  for (const edge of visibleEdges) {
    const source = String(edge.source);
    const target = String(edge.target);
    if (!nodeIdSet.has(source) || !nodeIdSet.has(target)) continue;
    if (!adjacency.has(source)) adjacency.set(source, new Set());
    if (!adjacency.has(target)) adjacency.set(target, new Set());
    adjacency.get(source)?.add(target);
    adjacency.get(target)?.add(source);
    if (source === selectedNodeId) directOut.add(target);
    if (target === selectedNodeId) directIn.add(source);
  }
  const hopById = new Map<string, number>();
  if (selectedNodeId !== '' && nodeIdSet.has(selectedNodeId)) {
    const queue: Array<{ id: string; hop: number }> = [{ id: selectedNodeId, hop: 0 }];
    hopById.set(selectedNodeId, 0);
    while (queue.length > 0) {
      const current = queue.shift() as { id: string; hop: number };
      const neighbors = adjacency.get(current.id) ?? new Set<string>();
      for (const next of neighbors) {
        if (hopById.has(next)) continue;
        const hop = current.hop + 1;
        hopById.set(next, hop);
        if (hop < 5) queue.push({ id: next, hop });
      }
    }
  }

  const relationForNode = (nodeId: string): { label: string; hop: number } => {
    if (selectedNodeId === '') return { label: 'scope', hop: -1 };
    if (nodeId === selectedNodeId) return { label: 'anchor', hop: 0 };
    const hop = Number(hopById.get(nodeId) ?? -1);
    if (hop === 1) {
      const isIn = directIn.has(nodeId);
      const isOut = directOut.has(nodeId);
      if (isIn && isOut) return { label: '1-hop in/out', hop };
      if (isIn) return { label: '1-hop in', hop };
      if (isOut) return { label: '1-hop out', hop };
      return { label: '1-hop', hop };
    }
    if (hop >= 2) return { label: `${hop}-hop`, hop };
    return { label: 'related', hop };
  };

  const groups: DetailGroup[] = [];
  for (const entry of groupsMap.values()) {
    if (entry.nodes.length === 0) continue;
    const sortedByRank = [...entry.nodes].sort((a, b) => {
      const [a0, a1, a2] = representativeRank(a);
      const [b0, b1, b2] = representativeRank(b);
      if (a0 !== b0) return a0 - b0;
      if (a1 !== b1) return a1 - b1;
      if (a2 !== b2) return a2 - b2;
      return String(a.id).localeCompare(String(b.id));
    });
    const representative = sortedByRank[0];
    const hasAnchor = selectedNodeId !== '' && entry.nodes.some((node) => String(node.id) === selectedNodeId);

    let inDegree = 0;
    let outDegree = 0;
    let loc = 0;
    let functions = 0;
    let classes = 0;
    let signals = 0;
    let fallbackIn = 0;
    let fallbackOut = 0;
    const groupNodeIds = new Set(entry.nodes.map((node) => String(node.id)));
    let minHop = Number.POSITIVE_INFINITY;
    let hasDirectIn = false;
    let hasDirectOut = false;

    for (const node of entry.nodes) {
      const kind = String(node.kind ?? '').toLowerCase();
      const nId = String(node.id);
      const nIn = Number(node.metrics?.in_degree ?? 0);
      const nOut = Number(node.metrics?.out_degree ?? 0);
      fallbackIn += nIn;
      fallbackOut += nOut;
      loc = Math.max(loc, Number(node.metrics?.loc ?? 0));
      if (kind === 'function') functions += 1;
      if (kind === 'class') classes += 1;
      if (kind === 'signal') signals += 1;
      if (kind !== 'function') {
        inDegree += nIn;
        outDegree += nOut;
      }
      const hop = Number(hopById.get(nId) ?? -1);
      if (hop >= 0) minHop = Math.min(minHop, hop);
      if (directIn.has(nId)) hasDirectIn = true;
      if (directOut.has(nId)) hasDirectOut = true;
    }

    if (inDegree === 0 && outDegree === 0) {
      inDegree = fallbackIn;
      outDegree = fallbackOut;
    }

    let relation = 'related';
    let hop = Number.isFinite(minHop) ? minHop : -1;
    if (selectedNodeId === '') {
      relation = 'scope';
      hop = -1;
    } else if (hasAnchor) {
      relation = 'anchor';
      hop = 0;
    } else if (hop === 1) {
      if (hasDirectIn && hasDirectOut) relation = '1-hop in/out';
      else if (hasDirectIn) relation = '1-hop in';
      else if (hasDirectOut) relation = '1-hop out';
      else relation = '1-hop';
    } else if (hop >= 2) {
      relation = `${hop}-hop`;
    }

    const representativeLookup = nodeLookup.get(String(representative.id));
    const repTitle = displayCardTitle(representative, representativeLookup);
    const pathTitle = basename(entry.path);
    const title = pathTitle !== '' ? pathTitle : repTitle;
    const cardId = hasAnchor ? selectedNodeId : String(representative.id);
    const kind = entry.path !== '' ? 'file' : String(representative.kind ?? 'unknown');
    groups.push({
      key: entry.key,
      path: entry.path,
      nodes: entry.nodes,
      representative,
      cardId,
      kind,
      title,
      inDegree,
      outDegree,
      loc,
      functions,
      classes,
      signals,
      relation,
      hop,
    });
  }

  const sortedGroups = [...groups].sort((a, b) => {
    const aSelected = a.cardId === selectedNodeId ? 1 : 0;
    const bSelected = b.cardId === selectedNodeId ? 1 : 0;
    if (bSelected !== aSelected) return bSelected - aSelected;
    const aHop = a.hop < 0 ? 999 : a.hop;
    const bHop = b.hop < 0 ? 999 : b.hop;
    if (aHop !== bHop) return aHop - bHop;
    const aDegree = a.inDegree + a.outDegree;
    const bDegree = b.inDegree + b.outDegree;
    if (bDegree !== aDegree) return bDegree - aDegree;
    if (b.functions !== a.functions) return b.functions - a.functions;
    return a.title.localeCompare(b.title);
  });

  const laneId = selectedClusterId !== '' ? selectedClusterId : `detail::${selectedNodeId || 'scope'}`;
  const laneTitle = selectedClusterId !== ''
    ? `${clusterDisplayName(selectedClusterId, payload)} · Detail`
    : 'Detail scope';
  const panelX = 40;
  const panelY = 40;
  const panelW = 1320;
  const cardW = 280;
  const cardH = 106;
  const gapX = 16;
  const gapY = 14;
  const padX = 16;
  const padY = 50;
  const columns = Math.max(1, Math.floor((panelW - padX * 2 + gapX) / (cardW + gapX)));

  const cards = sortedGroups.map((group, index) => {
    const col = index % columns;
    const row = Math.floor(index / columns);
    return {
      id: group.cardId,
      title: group.title,
      kind: group.kind,
      path: group.path,
      x: panelX + padX + col * (cardW + gapX),
      y: panelY + padY + row * (cardH + gapY),
      w: cardW,
      h: cardH,
      stats: {
        inDegree: group.inDegree,
        outDegree: group.outDegree,
        loc: group.loc,
        functions: group.functions,
        classes: group.classes,
        signals: group.signals,
        relation: group.relation,
        hop: group.hop,
      },
    };
  });

  const groupByNodeId = new Map<string, DetailGroup>();
  for (const group of sortedGroups) {
    for (const node of group.nodes) {
      groupByNodeId.set(String(node.id), group);
    }
  }

  const cardIdByGroupKey = new Map<string, string>();
  for (const group of sortedGroups) {
    cardIdByGroupKey.set(group.key, group.cardId);
  }

  const linkBuckets = new Map<
    string,
    {
      sourceGroup: DetailGroup;
      targetGroup: DetailGroup;
      count: number;
      typeBreakdown: Record<string, number>;
      evidenceRefs: Array<Record<string, unknown>>;
    }
  >();
  for (const edge of visibleEdges) {
    const sourceNodeId = String(edge.source);
    const targetNodeId = String(edge.target);
    const sourceGroup = groupByNodeId.get(sourceNodeId);
    const targetGroup = groupByNodeId.get(targetNodeId);
    if (sourceGroup == null || targetGroup == null) continue;
    if (sourceGroup.key === targetGroup.key) continue;
    const edgeType = String(edge.edge_type ?? 'contains');
    const count = Math.max(1, Number((edge.metadata as Record<string, unknown> | undefined)?.count ?? 1));
    const bucketKey = `${sourceGroup.key}->${targetGroup.key}`;
    if (!linkBuckets.has(bucketKey)) {
      linkBuckets.set(bucketKey, {
        sourceGroup,
        targetGroup,
        count: 0,
        typeBreakdown: {},
        evidenceRefs: [],
      });
    }
    const bucket = linkBuckets.get(bucketKey) as {
      sourceGroup: DetailGroup;
      targetGroup: DetailGroup;
      count: number;
      typeBreakdown: Record<string, number>;
      evidenceRefs: Array<Record<string, unknown>>;
    };
    bucket.count += count;
    bucket.typeBreakdown[edgeType] = Number(bucket.typeBreakdown[edgeType] ?? 0) + count;
    if (bucket.evidenceRefs.length < 8) {
      const sourceNode = nodeById.get(sourceNodeId);
      const targetNode = nodeById.get(targetNodeId);
      const sourceLookup = nodeLookup.get(sourceNodeId);
      const targetLookup = nodeLookup.get(targetNodeId);
      const relation = relationForNode(targetNodeId);
      bucket.evidenceRefs.push({
        source_node: sourceNodeId,
        target_node: targetNodeId,
        edge_type: edgeType,
        source_label: sourceNode ? displayCardTitle(sourceNode, sourceLookup) : String(sourceLookup?.label ?? sourceNodeId),
        target_label: targetNode ? displayCardTitle(targetNode, targetLookup) : String(targetLookup?.label ?? targetNodeId),
        source_path: String(sourceNode?.path ?? sourceLookup?.path ?? ''),
        target_path: String(targetNode?.path ?? targetLookup?.path ?? ''),
        source_line: Number((edge.metadata as Record<string, unknown> | undefined)?.source_line ?? -1),
        target_line: Number((edge.metadata as Record<string, unknown> | undefined)?.target_line ?? -1),
        reason: `${edgeType} · ${relation.label}`,
      });
    }
  }

  const links = [...linkBuckets.values()]
    .sort((a, b) => b.count - a.count)
    .slice(0, 320)
    .map((bucket, index) => {
      const dominantType = dominantEdgeType(bucket.typeBreakdown);
      return {
        id: `detail_link::${index}::${bucket.sourceGroup.key}->${bucket.targetGroup.key}`,
        sourceClusterId: laneId,
        targetClusterId: laneId,
        sourceCardId: String(cardIdByGroupKey.get(bucket.sourceGroup.key) ?? bucket.sourceGroup.cardId),
        targetCardId: String(cardIdByGroupKey.get(bucket.targetGroup.key) ?? bucket.targetGroup.cardId),
        count: bucket.count,
        typeBreakdown: bucket.typeBreakdown,
        evidenceRefs: bucket.evidenceRefs,
        color: legendColorForType(dominantType, legend),
        style: legendStyleForType(dominantType, legend),
        defaultVisible: true,
      };
    });

  const rows = Math.max(1, Math.ceil(cards.length / columns));
  const panelH = Math.max(240, padY + rows * (cardH + gapY) + 24);

  return {
    clusters: [
      {
        id: laneId,
        title: laneTitle,
        x: panelX,
        y: panelY,
        w: panelW,
        h: panelH,
        cards,
        hiddenCards: 0,
        summary: {
          nodeCount: cards.length,
          externalCount: links.reduce((acc, item) => acc + Number(item.count), 0),
          hot: 0,
          fileCount: cards.filter((card) => card.kind === 'file').length,
          functionCount: cards.reduce((acc, card) => acc + Number(card.stats.functions ?? 0), 0),
          classCount: cards.reduce((acc, card) => acc + Number(card.stats.classes ?? 0), 0),
        },
      },
    ],
    links,
    legend: renderLegend,
  };
}

function boardFrameFromModelV2(
  boardModel: BoardModelV2,
  mode: VisualizerMode,
  selectedClusterId: string,
  edgeTypeEnabled: Record<string, boolean>,
  callsEnabled: boolean,
  clusterPreviewCardLimit: number,
): RenderFrame['board'] {
  const sortedLanes = [...boardModel.lanes].sort((a, b) => {
    const aSize = Number(a.summary?.file_count ?? a.cards.length);
    const bSize = Number(b.summary?.file_count ?? b.cards.length);
    return bSize - aSize;
  });
  const legend = [...boardModel.legend];

  if (mode === 'cluster') {
    const panelW = 420;
    const panelH = 236;
    const gapX = 24;
    const gapY = 20;
    const cols = sortedLanes.length <= 4 ? 2 : 3;
    const externalByLane = new Map<string, number>();
    for (const lane of sortedLanes) {
      const laneId = String(lane.id);
      const external = boardModel.links
        .filter((link) => String(link.source_lane) === laneId || String(link.target_lane) === laneId)
        .reduce((acc, item) => acc + Number(item.count ?? 0), 0);
      externalByLane.set(laneId, external);
    }

    const clusters = sortedLanes.map((lane, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      const panelX = 40 + col * (panelW + gapX);
      const panelY = 40 + row * (panelH + gapY);
      const previewCards = [...lane.cards]
        .sort((a, b) => {
          const degreeA = Number(a.stats?.in ?? 0) + Number(a.stats?.out ?? 0);
          const degreeB = Number(b.stats?.in ?? 0) + Number(b.stats?.out ?? 0);
          if (degreeB !== degreeA) return degreeB - degreeA;
          return String(a.title).localeCompare(String(b.title));
        })
        .slice(0, Math.max(1, clusterPreviewCardLimit))
        .map((card, index) => {
          const previewCol = index % 2;
          const previewRow = Math.floor(index / 2);
          const cardW = 196;
          const cardH = 74;
          return {
            id: String(card.id),
            title: String(card.title),
            kind: String(card.kind),
            path: String(card.path ?? ''),
            x: panelX + 16 + previewCol * (cardW + 10),
            y: panelY + 68 + previewRow * (cardH + 10),
            w: cardW,
            h: cardH,
            stats: {
              inDegree: Number(card.stats?.in ?? 0),
              outDegree: Number(card.stats?.out ?? 0),
              loc: Number(card.stats?.loc ?? 0),
              functions: Number(card.stats?.functions ?? 0),
              classes: Number(card.stats?.classes ?? 0),
              signals: Number(card.stats?.signals ?? 0),
            },
          };
        });
      return {
        id: String(lane.id),
        title: String(lane.title),
        x: panelX,
        y: panelY,
        w: panelW,
        h: panelH,
        cards: previewCards,
        hiddenCards: Math.max(
          0,
          Number(lane.summary?.total_card_count ?? (Number(lane.hidden_items_count ?? 0) + Number(lane.cards.length)))
            - previewCards.length,
        ),
        summary: {
          nodeCount: Number(lane.summary?.node_count ?? lane.cards.length),
          externalCount: Number(externalByLane.get(String(lane.id)) ?? 0),
          hot: Number(lane.summary?.hot ?? 0),
          fileCount: Number(lane.summary?.file_count ?? lane.cards.length),
          functionCount: Number(lane.summary?.function_count ?? 0),
          classCount: Number(lane.summary?.class_count ?? 0),
        },
      };
    });
    const laneIdSet = new Set(clusters.map((lane) => lane.id));
    const links = boardModel.links
      .filter((link) => laneIdSet.has(String(link.source_lane)) && laneIdSet.has(String(link.target_lane)))
      .map((link) => {
        const edgeType = dominantEdgeType(link.type_breakdown ?? {});
        const legendItem = legend.find((row) => String(row.edge_type) === edgeType);
        const defaultVisible = Boolean(legendItem?.default_visible ?? true);
        const filterVisible =
          typeof edgeTypeEnabled[edgeType] === 'boolean' ? Boolean(edgeTypeEnabled[edgeType]) : defaultVisible;
        if ((edgeType === 'calls' && !callsEnabled) || !filterVisible) {
          return null;
        }
        return {
          id: String(link.id),
          sourceClusterId: String(link.source_lane),
          targetClusterId: String(link.target_lane),
          count: Number(link.count ?? 0),
          typeBreakdown: { ...(link.type_breakdown ?? {}) },
          evidenceRefs: Array.isArray(link.evidence_refs) ? [...link.evidence_refs] : [],
          color: legendColorForType(edgeType, legend),
          style: String(legendItem?.style ?? 'solid'),
          defaultVisible: Boolean(legendItem?.default_visible ?? true),
        };
      })
      .filter((item): item is NonNullable<typeof item> => item != null);
    const renderLegend = legend.map((item) => ({
      edgeType: String(item.edge_type),
      label: String(item.label),
      color: String(item.color),
      style: String(item.style),
      defaultVisible: Boolean(item.default_visible),
    }));
    return { clusters, links, legend: renderLegend };
  }

  const focusLaneId = selectedClusterId !== '' ? selectedClusterId : String(sortedLanes[0]?.id ?? '');
  const focusLane = sortedLanes.find((lane) => String(lane.id) === focusLaneId);
  if (focusLane == null) return { clusters: [], links: [], legend: [] };

  const panelX = 40;
  const panelY = 40;
  const panelW = 1280;
  const cardW = 256;
  const cardH = 106;
  const gapX = 16;
  const gapY = 16;
  const padX = 16;
  const padY = 52;
  const cardsLimit = Number.MAX_SAFE_INTEGER;
  const columns = Math.max(1, Math.floor((panelW - padX * 2 + gapX) / (cardW + gapX)));
  const cards = [...focusLane.cards]
    .sort((a, b) => {
      const degreeA = Number(a.stats?.in ?? 0) + Number(a.stats?.out ?? 0);
      const degreeB = Number(b.stats?.in ?? 0) + Number(b.stats?.out ?? 0);
      if (degreeB !== degreeA) return degreeB - degreeA;
      return String(a.title).localeCompare(String(b.title));
    })
    .slice(0, cardsLimit)
    .map((card, index) => {
      const col = index % columns;
      const row = Math.floor(index / columns);
      return {
        id: String(card.id),
        title: String(card.title),
        kind: String(card.kind),
        path: String(card.path ?? ''),
        x: panelX + padX + col * (cardW + gapX),
        y: panelY + padY + row * (cardH + gapY),
        w: cardW,
        h: cardH,
        stats: {
          inDegree: Number(card.stats?.in ?? 0),
          outDegree: Number(card.stats?.out ?? 0),
          loc: Number(card.stats?.loc ?? 0),
          functions: Number(card.stats?.functions ?? 0),
          classes: Number(card.stats?.classes ?? 0),
          signals: Number(card.stats?.signals ?? 0),
        },
      };
    });
  const rows = Math.max(1, Math.ceil(cards.length / columns));
  const panelH = Math.max(240, padY + rows * (cardH + gapY) + 24);
  const links = boardModel.links
    .filter((link) => String(link.source_lane) === String(focusLane.id) || String(link.target_lane) === String(focusLane.id))
    .map((link) => {
      const edgeType = dominantEdgeType(link.type_breakdown ?? {});
      const legendItem = legend.find((row) => String(row.edge_type) === edgeType);
      const defaultVisible = Boolean(legendItem?.default_visible ?? true);
      const filterVisible =
        typeof edgeTypeEnabled[edgeType] === 'boolean' ? Boolean(edgeTypeEnabled[edgeType]) : defaultVisible;
      if ((edgeType === 'calls' && !callsEnabled) || !filterVisible) {
        return null;
      }
      return {
        id: String(link.id),
        sourceClusterId: String(link.source_lane),
        targetClusterId: String(link.target_lane),
        count: Number(link.count ?? 0),
        typeBreakdown: { ...(link.type_breakdown ?? {}) },
        evidenceRefs: Array.isArray(link.evidence_refs) ? [...link.evidence_refs] : [],
        color: legendColorForType(edgeType, legend),
        style: String(legendItem?.style ?? 'solid'),
        defaultVisible: Boolean(legendItem?.default_visible ?? true),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item != null);
  const renderLegend = legend.map((item) => ({
    edgeType: String(item.edge_type),
    label: String(item.label),
    color: String(item.color),
    style: String(item.style),
    defaultVisible: Boolean(item.default_visible),
  }));

  return {
    clusters: [
      {
        id: String(focusLane.id),
        title: String(focusLane.title),
        x: panelX,
        y: panelY,
        w: panelW,
        h: panelH,
        cards,
        hiddenCards: Math.max(
          0,
          Number(focusLane.summary?.total_card_count ?? (Number(focusLane.hidden_items_count ?? 0) + Number(focusLane.cards.length)))
            - cards.length,
        ),
        summary: {
          nodeCount: Number(focusLane.summary?.node_count ?? focusLane.cards.length),
          externalCount: links.reduce((acc, item) => acc + Number(item.count), 0),
          hot: Number(focusLane.summary?.hot ?? 0),
          fileCount: Number(focusLane.summary?.file_count ?? focusLane.cards.length),
          functionCount: Number(focusLane.summary?.function_count ?? 0),
          classCount: Number(focusLane.summary?.class_count ?? 0),
        },
      },
    ],
    links,
    legend: renderLegend,
  };
}

function boardFrameFromModel(boardModel: BoardModel, mode: VisualizerMode, selectedClusterId: string): RenderFrame['board'] {
  const sortedClusters = [...boardModel.clusters].sort((a, b) => {
    const aSize = Number(a.summary?.node_count ?? a.cards.length);
    const bSize = Number(b.summary?.node_count ?? b.cards.length);
    return bSize - aSize;
  });

  if (mode === 'cluster') {
    const panelW = 430;
    const panelH = 210;
    const gapX = 36;
    const gapY = 28;
    const cols = Math.max(2, Math.min(3, Math.ceil(Math.sqrt(sortedClusters.length || 1))));

    const clusters = sortedClusters.map((cluster, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      const x = 40 + col * (panelW + gapX);
      const y = 40 + row * (panelH + gapY);
      const previewCards = [...cluster.cards]
        .filter((card) => card.kind !== 'function')
        .slice(0, 4)
        .map((card, cardIndex) => {
          const previewCol = cardIndex % 2;
          const previewRow = Math.floor(cardIndex / 2);
          const cardW = 184;
          const cardH = 52;
          return {
            id: card.id,
            title: card.title,
            kind: card.kind,
            x: x + 16 + previewCol * (cardW + 10),
            y: y + 68 + previewRow * (cardH + 8),
            w: cardW,
            h: cardH,
            path: card.path,
            stats: {
              inDegree: Number(card.stats?.in ?? 0),
              outDegree: Number(card.stats?.out ?? 0),
              loc: Number(card.stats?.loc ?? 0),
              functions: Number(card.stats?.functions ?? 0),
              classes: Number(card.stats?.classes ?? 0),
              signals: Number(card.stats?.signals ?? 0),
            },
          };
        });

      return {
        id: cluster.id,
        title: cluster.title,
        x,
        y,
        w: panelW,
        h: panelH,
        cards: previewCards,
        hiddenCards: Math.max(0, Number(cluster.summary?.file_count ?? cluster.cards.length) - previewCards.length),
        summary: {
          nodeCount: Number(cluster.summary?.node_count ?? cluster.cards.length),
          externalCount: Number(cluster.summary?.external_count ?? 0),
          hot: Number(cluster.summary?.hot ?? 0),
          fileCount: Number(cluster.summary?.file_count ?? cluster.cards.length),
          functionCount: Number(cluster.summary?.function_count ?? 0),
          classCount: Number(cluster.summary?.class_count ?? 0),
        },
      };
    });

    const clusterIds = new Set(clusters.map((cluster) => cluster.id));
    const links = boardModel.links
      .filter((link) => clusterIds.has(link.source_cluster) && clusterIds.has(link.target_cluster))
      .map((link) => ({
        sourceClusterId: link.source_cluster,
        targetClusterId: link.target_cluster,
        count: Number(link.count ?? 0),
      }));

    return { clusters, links };
  }

  const focusClusterId =
    selectedClusterId !== ''
      ? selectedClusterId
      : sortedClusters[0]?.id ?? '';
  const focusCluster = sortedClusters.find((cluster) => cluster.id === focusClusterId);
  if (focusCluster == null) {
    return { clusters: [], links: [] };
  }

  const panelX = 40;
  const panelY = 40;
  const panelW = 1280;
  const cardW = 256;
  const cardH = 102;
  const gapX = 16;
  const gapY = 14;
  const padX = 16;
  const padY = 48;
  const cardsLimit = 24;
  const columns = Math.max(1, Math.floor((panelW - padX * 2 + gapX) / (cardW + gapX)));

  const priorityKinds = new Set(['file', 'class', 'scene', 'resource', 'signal', 'system', 'entity', 'node']);
  const nonFunction = focusCluster.cards.filter((card) => card.kind !== 'function');
  const sourceCards = nonFunction.length > 0 ? nonFunction : [...focusCluster.cards];
  const cards = sourceCards
    .map((card) => {
      const degree = Number(card.stats?.in ?? 0) + Number(card.stats?.out ?? 0);
      const kind = String(card.kind ?? 'unknown');
      const kindRank = priorityKinds.has(kind) ? 0 : kind === 'function' ? 2 : 1;
      return { card, degree, kindRank };
    })
    .sort((a, b) => {
      if (a.kindRank !== b.kindRank) return a.kindRank - b.kindRank;
      if (b.degree !== a.degree) return b.degree - a.degree;
      return String(a.card.title).localeCompare(String(b.card.title));
    })
    .slice(0, cardsLimit)
    .map(({ card }, index) => {
      const col = index % columns;
      const row = Math.floor(index / columns);
      return {
        id: card.id,
        title: card.title,
        kind: card.kind,
        path: card.path,
        x: panelX + padX + col * (cardW + gapX),
        y: panelY + padY + row * (cardH + gapY),
        w: cardW,
        h: cardH,
        stats: {
          inDegree: Number(card.stats?.in ?? 0),
          outDegree: Number(card.stats?.out ?? 0),
          loc: Number(card.stats?.loc ?? 0),
          functions: Number(card.stats?.functions ?? 0),
          classes: Number(card.stats?.classes ?? 0),
          signals: Number(card.stats?.signals ?? 0),
        },
      };
    });
  const rows = Math.max(1, Math.ceil(cards.length / columns));
  const panelH = Math.max(220, padY + rows * (cardH + gapY) + 24);
  const totalFileCards = Number(focusCluster.summary?.file_count ?? focusCluster.cards.length);

  return {
    clusters: [
      {
        id: focusCluster.id,
        title: focusCluster.title,
        x: panelX,
        y: panelY,
        w: panelW,
        h: panelH,
        cards,
        hiddenCards: Math.max(0, totalFileCards - cards.length),
        summary: {
          nodeCount: Number(focusCluster.summary?.node_count ?? focusCluster.cards.length),
          externalCount: Number(focusCluster.summary?.external_count ?? 0),
          hot: Number(focusCluster.summary?.hot ?? 0),
          fileCount: Number(focusCluster.summary?.file_count ?? focusCluster.cards.length),
          functionCount: Number(focusCluster.summary?.function_count ?? 0),
          classCount: Number(focusCluster.summary?.class_count ?? 0),
        },
      },
    ],
    links: [],
  };
}

export function App() {
  const graphHostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<GraphRenderer | null>(null);
  const rendererCallbacksRef = useRef<GraphRendererCallbacks | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const minimapRef = useRef<HTMLCanvasElement | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const autoSelectedClusterRef = useRef('');

  const [fps, setFps] = useState(0);
  const [rendererBackend, setRendererBackend] = useState<RendererBackend>('board_canvas');
  const [rendererErrorCode, setRendererErrorCode] = useState('none');
  const [rendererError, setRendererError] = useState('');
  const [clusterSort, setClusterSort] = useState<'size' | 'external' | 'hot'>('size');
  const [selectedLinkId, setSelectedLinkId] = useState('');

  const payload = useVisualizerStore((state) => state.payload);
  const bundle = useVisualizerStore((state) => state.bundle);
  const viewModel = useVisualizerStore((state) => state.viewModel);
  const mode = useVisualizerStore((state) => state.mode);
  const callsEnabled = useVisualizerStore((state) => state.callsEnabled);
  const focusScope = useVisualizerStore((state) => state.focusScope);
  const selectedNodeId = useVisualizerStore((state) => state.selectedNodeId);
  const selectedClusterId = useVisualizerStore((state) => state.selectedClusterId);
  const kHop = useVisualizerStore((state) => state.kHop);
  const pathNodeIds = useVisualizerStore((state) => state.pathNodeIds);
  const edgeTypeEnabled = useVisualizerStore((state) => state.edgeTypeEnabled);
  const searchQuery = useVisualizerStore((state) => state.searchQuery);
  const searchResults = useVisualizerStore((state) => state.searchResults);
  const searchIndex = useVisualizerStore((state) => state.searchIndex);
  const visibleNodeCount = useVisualizerStore((state) => state.visibleNodeCount);
  const visibleEdgeCount = useVisualizerStore((state) => state.visibleEdgeCount);
  const edgesSampled = useVisualizerStore((state) => state.edgesSampled);
  const toast = useVisualizerStore((state) => state.toast);
  const rawJsonOpen = useVisualizerStore((state) => state.rawJsonOpen);
  const overlay = useVisualizerStore((state) => state.overlay);
  const diagnosticsCollapsed = useVisualizerStore((state) => state.diagnosticsCollapsed);
  const lastNavigationReason = useVisualizerStore((state) => state.lastNavigationReason);
  const structuralExpandedLaneId = useVisualizerStore((state) => state.structuralExpandedLaneId);

  const setMode = useVisualizerStore((state) => state.setMode);
  const setSearchQuery = useVisualizerStore((state) => state.setSearchQuery);
  const setSearchResults = useVisualizerStore((state) => state.setSearchResults);
  const setSearchIndex = useVisualizerStore((state) => state.setSearchIndex);
  const selectNode = useVisualizerStore((state) => state.selectNode);
  const drillToCluster = useVisualizerStore((state) => state.drillToCluster);
  const drillToDetail = useVisualizerStore((state) => state.drillToDetail);
  const showPathScope = useVisualizerStore((state) => state.showPathScope);
  const toggleCalls = useVisualizerStore((state) => state.toggleCalls);
  const toggleEdgeType = useVisualizerStore((state) => state.toggleEdgeType);
  const setVisibleMetrics = useVisualizerStore((state) => state.setVisibleMetrics);
  const goBack = useVisualizerStore((state) => state.goBack);
  const goForward = useVisualizerStore((state) => state.goForward);
  const setToast = useVisualizerStore((state) => state.setToast);
  const toggleRawJson = useVisualizerStore((state) => state.toggleRawJson);
  const toggleDiagnosticsCollapsed = useVisualizerStore((state) => state.toggleDiagnosticsCollapsed);

  const nodeLookup = useNodeLookup(bundle);
  const boardModel = useMemo(() => getBoardModel(payload), [payload]);
  const boardModelV2 = useMemo(() => getBoardModelV2(payload), [payload]);
  const relationshipEvidence = useMemo(() => {
    const fromView = Array.isArray(payload.view_model?.relationship_evidence) ? payload.view_model?.relationship_evidence : [];
    if (fromView.length > 0) return fromView;
    return Array.isArray(payload.graph_bundle?.relationship_evidence) ? payload.graph_bundle?.relationship_evidence : [];
  }, [payload.view_model?.relationship_evidence, payload.graph_bundle?.relationship_evidence]);
  const uiDefaults = useMemo(() => {
    return {
      detailRequiresAnchor: Boolean(
        bundle?.ui_defaults?.detail_requires_anchor
          ?? viewModel?.ui_defaults?.detail_requires_anchor
          ?? true,
      ),
      structuralAutoselect: String(
        bundle?.ui_defaults?.structural_autoselect
          ?? viewModel?.ui_defaults?.structural_autoselect
          ?? 'top_file_card',
      ),
      clusterPreviewCardLimit: Number(
        bundle?.ui_defaults?.cluster_preview_card_limit
          ?? viewModel?.ui_defaults?.cluster_preview_card_limit
          ?? 4,
      ),
      structuralShowAllOnMore: Boolean(
        bundle?.ui_defaults?.structural_show_all_on_more
          ?? viewModel?.ui_defaults?.structural_show_all_on_more
          ?? true,
      ),
    };
  }, [bundle?.ui_defaults, viewModel?.ui_defaults]);

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

  const selectedClusterSummary = useMemo(() => {
    if (selectedClusterId === '') return null;
    if (boardModelV2 != null) {
      const lane = boardModelV2.lanes.find((item) => String(item.id) === selectedClusterId);
      if (lane != null) {
        return {
          title: String(lane.title),
          nodeCount: Number(lane.summary?.node_count ?? lane.cards.length),
          externalCount: Number(
            boardModelV2.links
              .filter((link) => String(link.source_lane) === selectedClusterId || String(link.target_lane) === selectedClusterId)
              .reduce((acc, item) => acc + Number(item.count ?? 0), 0),
          ),
          hot: Number(lane.summary?.hot ?? 0),
          fileCount: Number(lane.summary?.file_count ?? lane.cards.length),
          functionCount: Number(lane.summary?.function_count ?? 0),
          classCount: Number(lane.summary?.class_count ?? 0),
        };
      }
    }
    if (boardModel == null) return null;
    const cluster = boardModel.clusters.find((item) => item.id === selectedClusterId);
    if (cluster == null) return null;
    return {
      title: cluster.title,
      nodeCount: Number(cluster.summary?.node_count ?? cluster.cards.length),
      externalCount: Number(cluster.summary?.external_count ?? 0),
      hot: Number(cluster.summary?.hot ?? 0),
      fileCount: Number(cluster.summary?.file_count ?? cluster.cards.length),
      functionCount: Number(cluster.summary?.function_count ?? 0),
      classCount: Number(cluster.summary?.class_count ?? 0),
    };
  }, [boardModel, boardModelV2, selectedClusterId]);

  const selectedClusterTopCards = useMemo(() => {
    if (selectedClusterId.trim() === '') return [];
    const sourceCards = (() => {
      if (boardModelV2 != null) {
        const lane = boardModelV2.lanes.find((item) => String(item.id) === selectedClusterId);
        if (lane != null) return lane.cards.map((card) => ({
          id: String(card.id),
          title: String(card.title),
          kind: String(card.kind),
          path: String(card.path ?? ''),
          stats: { in: Number(card.stats?.in ?? 0), out: Number(card.stats?.out ?? 0), functions: Number(card.stats?.functions ?? 0), classes: Number(card.stats?.classes ?? 0) },
        }));
      }
      if (boardModel == null) return [];
      const cluster = boardModel.clusters.find((item) => item.id === selectedClusterId);
      return cluster?.cards ?? [];
    })();
    return [...sourceCards]
      .map((card) => {
        const degree = Number(card.stats?.in ?? 0) + Number(card.stats?.out ?? 0);
        const functions = Number(card.stats?.functions ?? 0);
        const classes = Number(card.stats?.classes ?? 0);
        return { card, degree, functions, classes };
      })
      .sort((a, b) => {
        if (b.degree !== a.degree) return b.degree - a.degree;
        if (b.functions !== a.functions) return b.functions - a.functions;
        if (b.classes !== a.classes) return b.classes - a.classes;
        return String(a.card.title).localeCompare(String(b.card.title));
      })
      .slice(0, 5)
      .map((entry) => entry.card);
  }, [boardModel, boardModelV2, selectedClusterId]);

  const clusterCards = useMemo(() => {
    let items: Array<{ id: string; label: string; size: number; external: number; hot: number }> = [];
    if (boardModelV2 != null) {
      items = boardModelV2.lanes.map((lane) => ({
        id: String(lane.id),
        label: String(lane.title),
        size: Number(lane.summary?.file_count ?? lane.cards.length),
        external: Number(
          boardModelV2.links
            .filter((link) => String(link.source_lane) === String(lane.id) || String(link.target_lane) === String(lane.id))
            .reduce((acc, item) => acc + Number(item.count ?? 0), 0),
        ),
        hot: Number(lane.summary?.hot ?? 0),
      }));
    } else if (bundle != null) {
      const pool = bundle.string_pool ?? [];
      items = (bundle.clusters ?? []).map((cluster) => ({
        id: cluster.id,
        label: String(pool[cluster.label_i] ?? cluster.id),
        size: Number(cluster.metrics?.size ?? cluster.node_ids.length),
        external: Number(cluster.metrics?.external_w ?? 0),
        hot: Number(cluster.metrics?.hot ?? 0),
      }));
    }

    const sorters = {
      size: (a: (typeof items)[number], b: (typeof items)[number]) => b.size - a.size,
      external: (a: (typeof items)[number], b: (typeof items)[number]) => b.external - a.external,
      hot: (a: (typeof items)[number], b: (typeof items)[number]) => b.hot - a.hot,
    };
    return items.sort(sorters[clusterSort]);
  }, [bundle, boardModelV2, clusterSort]);

  const hubCandidates = useMemo(() => {
    if (boardModelV2 != null) {
      const rows = boardModelV2.lanes.flatMap((lane) =>
        lane.cards.map((card) => ({
          id: String(card.id),
          label: String(card.title),
          degree: Number(card.stats?.in ?? 0) + Number(card.stats?.out ?? 0),
        })),
      );
      return rows.sort((a, b) => b.degree - a.degree).slice(0, 5);
    }
    const hotspots = boardModel?.hotspots ?? [];
    if (hotspots.length > 0) {
      return hotspots.slice(0, 5).map((item) => ({
        id: item.node_id,
        label: item.label,
        degree: Number(item.degree ?? 0),
      }));
    }
    if (viewModel == null) return [];
    return Object.values(viewModel.nodesById ?? {})
      .filter((node) => String(node.kind) !== 'cluster')
      .map((node) => ({
        id: String(node.id),
        label: String(node.label || node.id),
        degree: Number(node.metrics?.in_degree ?? 0) + Number(node.metrics?.out_degree ?? 0),
      }))
      .sort((a, b) => b.degree - a.degree)
      .slice(0, 5);
  }, [boardModel, boardModelV2, viewModel]);

  const runtimeDiagnostics = useMemo(() => {
    const diagnostics = payload.meta?.runtime_diagnostics;
    return Array.isArray(diagnostics) ? diagnostics : [];
  }, [payload.meta]);

  const clusterLayoutHealth = useMemo(() => {
    const health = viewModel?.cluster_layout_health;
    if (health == null || typeof health !== 'object') return null;
    return {
      overlapCount: Number((health as Record<string, unknown>).overlap_count ?? 0),
      duplicateAnchorCount: Number((health as Record<string, unknown>).duplicate_anchor_count ?? 0),
      maxDensityBand: String((health as Record<string, unknown>).max_density_band ?? 'unknown'),
    };
  }, [viewModel?.cluster_layout_health]);

  const boardFrame = useMemo(() => {
    const baseLegend = boardModelV2?.legend ?? defaultLegend();
    if (mode === 'detail') {
      return boardFrameFromDetailVisible({
        visibleNodes: visible.nodes,
        visibleEdges: visible.edges,
        selectedNodeId,
        selectedClusterId,
        payload,
        nodeLookup,
        legend: baseLegend,
      });
    }
    if (boardModelV2 != null) {
      return boardFrameFromModelV2(
        boardModelV2,
        mode,
        selectedClusterId,
        edgeTypeEnabled,
        callsEnabled,
        Math.max(1, uiDefaults.clusterPreviewCardLimit),
      );
    }
    if (boardModel == null) return undefined;
    return boardFrameFromModel(boardModel, mode, selectedClusterId);
  }, [
    boardModel,
    boardModelV2,
    mode,
    selectedClusterId,
    edgeTypeEnabled,
    callsEnabled,
    uiDefaults.clusterPreviewCardLimit,
    visible.nodes,
    visible.edges,
    selectedNodeId,
    payload,
    nodeLookup,
  ]);

  const activeLegend = useMemo(() => {
    if (boardFrame?.legend == null) return [];
    return boardFrame.legend;
  }, [boardFrame?.legend]);

  const laneTitleById = useMemo(() => {
    const mapping = new Map<string, string>();
    if (boardModelV2 != null) {
      for (const lane of boardModelV2.lanes) {
        mapping.set(String(lane.id), String(lane.title));
      }
    }
    for (const cluster of boardFrame?.clusters ?? []) {
      mapping.set(String(cluster.id), String(cluster.title));
    }
    return mapping;
  }, [boardModelV2, boardFrame?.clusters]);

  const selectedLinkSummary = useMemo(() => {
    if (selectedLinkId.trim() === '') return null;
    const links = boardFrame?.links ?? [];
    const link = links.find((item) => String(item.id) === selectedLinkId);
    if (link == null) return null;
    const firstEvidence = Array.isArray(link.evidenceRefs) && link.evidenceRefs.length > 0
      ? (link.evidenceRefs[0] as Record<string, unknown>)
      : null;
    const sourceCardId = typeof link.sourceCardId === 'string' ? link.sourceCardId : '';
    const targetCardId = typeof link.targetCardId === 'string' ? link.targetCardId : '';
    const sourceNode = sourceCardId !== '' ? viewModel?.nodesById?.[sourceCardId] : undefined;
    const targetNode = targetCardId !== '' ? viewModel?.nodesById?.[targetCardId] : undefined;
    const typeBreakdown = { ...(link.typeBreakdown ?? {}) };
    const typeEntries = Object.entries(typeBreakdown).sort((a, b) => Number(b[1]) - Number(a[1]));
    const dominantType = String(typeEntries[0]?.[0] ?? 'contains');
    const sourceTitle = sourceCardId !== ''
      ? String(
        firstEvidence?.source_label
          ?? sourceNode?.label
          ?? nodeLookup.get(sourceCardId)?.label
          ?? sourceCardId,
      )
      : laneTitleById.get(String(link.sourceClusterId)) ?? String(link.sourceClusterId);
    const targetTitle = targetCardId !== ''
      ? String(
        firstEvidence?.target_label
          ?? targetNode?.label
          ?? nodeLookup.get(targetCardId)?.label
          ?? targetCardId,
      )
      : laneTitleById.get(String(link.targetClusterId)) ?? String(link.targetClusterId);
    const fallbackEvidence = relationshipEvidence
      .filter((row) => {
        const sourceId = String((row as Record<string, unknown>).source_id ?? '');
        const targetId = String((row as Record<string, unknown>).target_id ?? '');
        return sourceId === String(link.sourceClusterId) && targetId === String(link.targetClusterId);
      })
      .flatMap((row) => {
        const refs = (row as Record<string, unknown>).evidence_refs;
        return Array.isArray(refs) ? refs : [];
      });
    const resolvedEvidenceRefs =
      Array.isArray(link.evidenceRefs) && link.evidenceRefs.length > 0
        ? [...link.evidenceRefs]
        : fallbackEvidence;
    return {
      id: String(link.id),
      source: String(link.sourceClusterId),
      target: String(link.targetClusterId),
      sourceTitle,
      targetTitle,
      count: Number(link.count ?? 0),
      typeBreakdown,
      dominantType,
      evidenceRefs: resolvedEvidenceRefs,
    };
  }, [boardFrame?.links, laneTitleById, selectedLinkId, viewModel?.nodesById, nodeLookup, relationshipEvidence]);

  const selectedNodeScopeReason = useMemo(() => {
    if (selectedNodeId.trim() === '') return '';
    for (const cluster of boardFrame?.clusters ?? []) {
      const card = cluster.cards.find((item) => String(item.id) === selectedNodeId);
      if (card != null && typeof card.stats.relation === 'string') {
        return String(card.stats.relation);
      }
    }
    return '';
  }, [boardFrame?.clusters, selectedNodeId]);

  const detailScopeSummary = useMemo(() => {
    if (mode !== 'detail') return '';
    const counter = new Map<string, number>();
    for (const cluster of boardFrame?.clusters ?? []) {
      for (const card of cluster.cards) {
        const relation = String(card.stats.relation ?? 'related');
        counter.set(relation, Number(counter.get(relation) ?? 0) + 1);
      }
    }
    const prioritized = ['anchor', '1-hop in', '1-hop out', '1-hop in/out', '2-hop', '3-hop', '4-hop', 'related'];
    const entries = Array.from(counter.entries());
    entries.sort((a, b) => {
      const ai = prioritized.indexOf(a[0]);
      const bi = prioritized.indexOf(b[0]);
      if (ai !== bi) return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
      return Number(b[1]) - Number(a[1]);
    });
    return entries.map(([key, value]) => `${key} ${value}`).join(' · ');
  }, [mode, boardFrame?.clusters]);

  const renderFrame = useMemo<RenderFrame>(() => {
    if (boardFrame != null) {
      return {
        mode,
        nodes: [],
        edges: [],
        board: boardFrame,
        selectedNodeId,
        selectedClusterId,
        selectedLinkId,
      };
    }

    const normalized = normalizeNodePositions(visible.nodes);
    return {
      mode,
      nodes: visible.nodes.map((node) => {
        const position = normalized.get(node.id) ?? { x: 0, y: 0 };
        const isSelected = node.id === selectedNodeId || node.id === selectedClusterId;
        const label = node.label || nodeLookup.get(node.id)?.label || node.id;
        return {
          id: node.id,
          label,
          kind: node.kind,
          x: position.x,
          y: position.y,
          size: isSelected ? nodeSize(node.kind) + 4 : nodeSize(node.kind),
          color: isSelected ? '#88ffe0' : nodeColor(node.kind),
        };
      }),
      edges: visible.edges.map((edge) => ({
        id: edge.id || `${edge.source}->${edge.target}:${edge.edge_type}`,
        source: edge.source,
        target: edge.target,
        size: Math.max(0.5, Math.min(5, Number(edge.confidence ?? 1))),
        color: edge.edge_type === 'calls' ? '#ff9a7c' : '#5b86d7',
      })),
      selectedNodeId,
      selectedClusterId,
      selectedLinkId,
    };
  }, [boardFrame, mode, selectedNodeId, selectedClusterId, selectedLinkId, visible.nodes, visible.edges, nodeLookup]);

  const createRendererCallbacks = (): GraphRendererCallbacks => ({
    onNodeClick: (nodeId: string) => {
      setSelectedLinkId('');
      const state = useVisualizerStore.getState();
      const vmNode = state.viewModel?.nodesById?.[nodeId];
      if (vmNode?.kind === 'cluster' || nodeId.startsWith('cluster::')) {
        state.drillToCluster(nodeId, 'cluster_click');
      } else {
        state.selectNode(nodeId);
      }
    },
    onNodeDoubleClick: (nodeId: string) => {
      setSelectedLinkId('');
      const state = useVisualizerStore.getState();
      const vmNode = state.viewModel?.nodesById?.[nodeId];
      if (vmNode?.kind === 'cluster' || nodeId.startsWith('cluster::')) {
        state.drillToCluster(nodeId, 'cluster_click');
      } else {
        state.drillToDetail(nodeId, 2, 'manual_mode');
      }
    },
    onMoreClick: (clusterId: string) => {
      setSelectedLinkId('');
      const state = useVisualizerStore.getState();
      state.drillToCluster(clusterId, 'more_click');
    },
    onEdgeClick: (edgeId: string) => {
      setSelectedLinkId(edgeId);
    },
    onStageClick: () => {
      setSelectedLinkId('');
      useVisualizerStore.setState((state) => {
        if (state.mode === 'detail') {
          return {};
        }
        return {
          selectedNodeId: '',
          selectedClusterId: state.mode === 'cluster' ? '' : state.selectedClusterId,
        };
      });
    },
  });

  const buildDetailRenderer = (
    host: HTMLElement,
    callbacks: GraphRendererCallbacks,
    allowWebgl: boolean,
  ): GraphRenderer | null => {
    if (allowWebgl && supportsWebGL()) {
      try {
        const sigma = new SigmaRenderer(callbacks);
        sigma.init(host);
        setRendererBackend('webgl_sigma');
        setRendererErrorCode('none');
        setRendererError('');
        return sigma;
      } catch (error) {
        const message = String(error);
        setRendererBackend('canvas2d_fallback');
        setRendererErrorCode(classifyRendererError(message));
        setRendererError(message);
      }
    }

    try {
      const canvas = new Canvas2DRenderer(callbacks);
      canvas.init(host);
      setRendererBackend('canvas2d_fallback');
      if (!allowWebgl) {
        setRendererErrorCode('none');
        setRendererError('');
      }
      return canvas;
    } catch (error) {
      const message = String(error);
      setRendererBackend('canvas2d_fallback');
      setRendererErrorCode(classifyRendererError(message));
      setRendererError(message);
      return null;
    }
  };

  useEffect(() => {
    rendererCallbacksRef.current = createRendererCallbacks();
  }, []);

  useEffect(() => {
    const host = graphHostRef.current;
    if (host == null) return;

    const callbacks = rendererCallbacksRef.current ?? createRendererCallbacks();
    rendererRef.current?.destroy();
    rendererRef.current = null;

    try {
      const board = new BoardRenderer(callbacks);
      board.init(host);
      rendererRef.current = board;
      setRendererBackend('board_canvas');
      setRendererErrorCode('none');
      setRendererError('');
    } catch (error) {
      const message = String(error);
      rendererRef.current = buildDetailRenderer(host, callbacks, shouldUseWebglDetail());
      setRendererErrorCode(classifyRendererError(message));
      setRendererError(message);
    }

    return () => {
      rendererRef.current?.destroy();
      rendererRef.current = null;
    };
  }, [mode]);

  useEffect(() => {
    setVisibleMetrics(visible.nodes.length, visible.edges.length, visible.sampled);
  }, [setVisibleMetrics, visible.nodes.length, visible.edges.length, visible.sampled]);

  useEffect(() => {
    if (toast === '') return;
    const timer = window.setTimeout(() => setToast(''), 2400);
    return () => window.clearTimeout(timer);
  }, [toast, setToast]);

  useEffect(() => {
    setSelectedLinkId('');
  }, [mode, selectedClusterId]);

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
    const onKeyDown = (event: KeyboardEvent) => {
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
        if (selectedNodeId !== '') rendererRef.current?.focusNode(selectedNodeId, 0.45);
        return;
      }
      if (event.key === 'Escape') {
        setSearchQuery('');
        setSearchResults([]);
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [goBack, goForward, selectedNodeId, setSearchQuery, setSearchResults, toggleCalls]);

  useEffect(() => {
    const renderer = rendererRef.current;
    if (renderer == null || viewModel == null) return;

    try {
      renderer.render(renderFrame);
    } catch (error) {
      const message = String(error);
      setRendererErrorCode(classifyRendererError(message));
      setRendererError(message);
      if (mode === 'detail' && renderer.backend === 'webgl_sigma' && graphHostRef.current != null) {
        const callbacks = rendererCallbacksRef.current ?? createRendererCallbacks();
        rendererRef.current?.destroy();
        rendererRef.current = buildDetailRenderer(graphHostRef.current, callbacks, false);
      }
      return;
    }

    if (selectedNodeId !== '') {
      const focused = renderer.focusNode(selectedNodeId, 0.42);
      if (!focused && mode !== 'detail') {
        drillToDetail(selectedNodeId, 2, 'manual_mode');
      }
      return;
    }

    if (selectedClusterId !== '') {
      renderer.focusNode(selectedClusterId, 0.62);
      return;
    }

    renderer.fit();
  }, [renderFrame, viewModel, selectedNodeId, selectedClusterId, mode, drillToDetail]);

  useEffect(() => {
    if (mode !== 'structural') return;
    if (uiDefaults.structuralAutoselect !== 'top_file_card') return;
    if (selectedClusterId.trim() === '') return;
    if (selectedNodeId.trim() !== '') return;

    const stateKey = `${mode}:${selectedClusterId}`;
    if (autoSelectedClusterRef.current === stateKey) return;
    const candidate = pickClusterActionNode(boardModel, boardModelV2, selectedClusterId);
    if (candidate === '') return;

    autoSelectedClusterRef.current = stateKey;
    selectNode(candidate);
    window.requestAnimationFrame(() => {
      rendererRef.current?.focusNode(candidate, 0.46);
    });
  }, [mode, selectedClusterId, selectedNodeId, boardModel, boardModelV2, selectNode, uiDefaults.structuralAutoselect]);

  useEffect(() => {
    const canvas = minimapRef.current;
    if (canvas == null || mode !== 'detail' || boardFrame != null) return;
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
  }, [mode, visible.nodes, selectedNodeId, boardFrame]);

  const onSearchFocus = (item: SearchResultItem) => {
    const clusterId = nodeLookup.get(item.nodeId)?.clusterId ?? '';
    if (mode === 'cluster' && clusterId !== '') {
      drillToCluster(clusterId, 'search_focus');
    }
    selectNode(item.nodeId);
    setSearchIndex(Math.max(0, searchResults.findIndex((row) => row.nodeId === item.nodeId)));
    const focused = rendererRef.current?.focusNode(item.nodeId, 0.4) ?? false;
    if (!focused) {
      drillToDetail(item.nodeId, 2, 'search_focus');
    }
  };

  const onAutoFixDensity = () => {
    if (callsEnabled) toggleCalls();
    useVisualizerStore.setState({
      mode: 'structural' as VisualizerMode,
      focusScope: 'clusterSubgraph',
      kHop: 2,
      toast: '과밀도 자동 수정이 적용되었습니다.',
    });
  };

  const openClusterTopHotspot = () => {
    const candidate = pickClusterActionNode(boardModel, boardModelV2, selectedClusterId);
    if (candidate === '') {
      setToast('선택된 클러스터에서 이동할 노드를 찾지 못했습니다.');
      return;
    }
    selectNode(candidate);
    window.requestAnimationFrame(() => {
      rendererRef.current?.focusNode(candidate, 0.42);
    });
  };

  const openClusterDetail = () => {
    const candidate = pickClusterActionNode(boardModel, boardModelV2, selectedClusterId);
    if (candidate === '') {
      setToast('선택된 클러스터에서 Detail로 이동할 노드를 찾지 못했습니다.');
      return;
    }
    drillToDetail(candidate, 2, 'guided_flow');
  };

  const openLargestCluster = () => {
    const topCluster = String(clusterCards[0]?.id ?? '').trim();
    if (topCluster === '') {
      setToast('클러스터를 찾지 못했습니다.');
      return;
    }
    drillToCluster(topCluster, 'guided_flow');
    setToast('가장 큰 클러스터로 이동했습니다.');
  };

  const openGuidedHotspot = () => {
    const targetClusterId = pickBestClusterId(clusterCards, selectedClusterId);
    if (targetClusterId === '') {
      setToast('핫스팟을 찾을 클러스터가 없습니다.');
      return;
    }
    if (selectedClusterId !== targetClusterId) {
      drillToCluster(targetClusterId, 'guided_flow');
    }
    const candidate = pickClusterActionNode(boardModel, boardModelV2, targetClusterId);
    if (candidate === '') {
      setToast('선택한 클러스터에 핫스팟 노드가 없습니다.');
      return;
    }
    selectNode(candidate);
    window.requestAnimationFrame(() => {
      rendererRef.current?.focusNode(candidate, 0.46);
    });
  };

  const openGuidedDetail = () => {
    const targetClusterId = pickBestClusterId(clusterCards, selectedClusterId);
    if (targetClusterId !== '' && selectedClusterId !== targetClusterId) {
      drillToCluster(targetClusterId, 'guided_flow');
    }
    const candidate = selectedNodeId.trim() !== '' ? selectedNodeId : pickClusterActionNode(boardModel, boardModelV2, targetClusterId);
    if (candidate === '') {
      setToast('Detail로 이동할 노드를 찾지 못했습니다.');
      return;
    }
    drillToDetail(candidate, 2, 'guided_flow');
  };

  const onShowPaths = () => {
    if (viewModel == null || selectedNodeId === '') {
      setToast('경로를 보려면 먼저 노드를 선택하세요.');
      return;
    }
    const entries = Object.values(viewModel.nodesById ?? {});
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

  const jumpToHub = (nodeId: string) => {
    if (nodeId === '') return;
    selectNode(nodeId);
    const focused = rendererRef.current?.focusNode(nodeId, 0.4) ?? false;
    if (!focused) {
      drillToDetail(nodeId, 2, 'guided_flow');
    }
  };

  const modeGuide = useMemo(() => {
    if (mode === 'cluster') return '1) 기능군(레인) 선택 → 2) +more(펼치기) 또는 더블클릭으로 Structural 진입.';
    if (mode === 'structural') return '1) 파일 카드 선택 → 2) 오른쪽 요약/링크 근거 확인 → 3) 필요 시 더블클릭 Detail.';
    if (selectedNodeId.trim() !== '') {
      return `Detail 카드는 선택 노드 기준 관계(anchor/1-hop/2-hop)로 표시됩니다. 현재: ${selectedNode.label || selectedNodeId} · ${detailScopeSummary || 'related scope'}`;
    }
    return 'Detail에서도 카드 기반으로 표시됩니다. 카드 선택 후 1-hop/2-hop/3-hop 또는 Show paths로 연결 원인을 추적하세요.';
  }, [mode, selectedNodeId, selectedNode.label, detailScopeSummary]);

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
    let startedAt = performance.now();
    const tick = (now: number) => {
      frames += 1;
      const elapsed = now - startedAt;
      if (elapsed >= 1000) {
        setFps(Math.round((frames * 1000) / elapsed));
        frames = 0;
        startedAt = now;
      }
      raf = window.requestAnimationFrame(tick);
    };
    raf = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(raf);
  }, []);

  const activeDiagnostic = useMemo(() => {
    if (rendererBackend !== 'board_canvas' && rendererError !== '' && rendererErrorCode !== 'none') {
      const warningLevel = rendererBackend === 'canvas2d_fallback' ? 'warning' : 'error';
      return {
        level: warningLevel,
        code: rendererErrorCode,
        message: rendererBackend === 'canvas2d_fallback'
          ? 'WebGL 경로가 실패해 Canvas2D 폴백으로 동작 중입니다.'
          : '렌더러 오류가 발생했습니다.',
        hint: rendererError,
      };
    }
    if (clusterLayoutHealth && (clusterLayoutHealth.overlapCount > 0 || clusterLayoutHealth.duplicateAnchorCount > 0)) {
      return {
        level: 'warning',
        code: 'cluster_layout_overlap',
        message: `클러스터 레이아웃 경고: overlap=${clusterLayoutHealth.overlapCount}, duplicate_anchor=${clusterLayoutHealth.duplicateAnchorCount}`,
        hint: `max density band: ${clusterLayoutHealth.maxDensityBand}`,
      };
    }
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
        hint: String(first.hint ?? '원인 확인 후 관련 노드로 이동하세요.'),
      };
    }
    return null;
  }, [rendererBackend, rendererError, rendererErrorCode, clusterLayoutHealth, visibleEdgeCount, runtimeDiagnostics]);

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
        <select
          className="mode"
          value={mode}
          onChange={(event) => {
            const next = event.target.value as VisualizerMode;
            if (next === 'detail' && uiDefaults.detailRequiresAnchor && selectedNodeId.trim() === '') {
              setToast('Detail 모드는 먼저 노드를 선택한 뒤 사용하세요. Structural에서 카드/Hub를 먼저 선택하세요.');
              return;
            }
            setMode(next, 'manual_mode');
          }}
        >
          <option value="cluster">Cluster</option>
          <option value="structural">Structural</option>
          <option value="detail">Detail</option>
        </select>
        <label className="toggle">
          <input type="checkbox" checked={callsEnabled} onChange={() => toggleCalls()} />
          {' '}Calls
        </label>
      </header>

      <div className="mode-guide">{modeGuide}</div>

      <div className="kpi-strip">
        <span>Nodes {totalNodes.toLocaleString()}</span>
        <span>Edges {totalEdges.toLocaleString()}</span>
        <span>Clusters {clusterCount.toLocaleString()}</span>
        <span>Visible {visibleNodeCount.toLocaleString()} / {totalNodes.toLocaleString()}</span>
        <span>Visible edges {visibleEdgeCount.toLocaleString()}</span>
        <span>FPS {fps}</span>
        <span className="badge">Backend {rendererBackend.replace('_', ' ')}</span>
        {edgesSampled ? <span className="badge">Edges sampled</span> : null}
      </div>

      {activeLegend.length > 0 ? (
        <div className="legend-strip">
          {activeLegend.map((item) => (
            <span key={item.edgeType} className={`legend-item ${edgeTypeEnabled[item.edgeType] ? 'is-enabled' : ''}`}>
              <i style={{ color: item.color }}>{item.style === 'dashed' ? '╌' : item.style === 'dotted' ? '⋯' : '—'}</i>
              {item.label}
              {edgeTypeEnabled[item.edgeType] ? ' ON' : ' OFF'}
            </span>
          ))}
        </div>
      ) : null}

      {activeDiagnostic != null ? (
        <div className={`diag-banner ${activeDiagnostic.level === 'error' ? 'critical' : ''}`}>
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
              <button
                key={cluster.id}
                className={`cluster-card ${selectedClusterId === cluster.id ? 'active' : ''}`}
                onClick={() => drillToCluster(cluster.id, 'cluster_click')}
                onDoubleClick={() => drillToCluster(cluster.id, 'cluster_click')}
              >
                <div className="cluster-title">{cluster.label}</div>
                <div className="cluster-meta">
                  {cluster.size} nodes · ext {cluster.external.toFixed(0)} · hot {cluster.hot.toFixed(2)}
                </div>
              </button>
            ))}
          </div>

          <div className="workflow-panel">
            <div className="filter-title">Guided Flow</div>
            <button className="workflow-step" onClick={openLargestCluster}>
              1) Largest cluster
            </button>
            <button className="workflow-step" onClick={openGuidedHotspot}>
              2) Top hotspot
            </button>
            <button className="workflow-step" onClick={openGuidedDetail}>
              3) Open Detail 2-hop
            </button>
          </div>

          <div className="quick-filters">
            <div className="filter-row">
              <span className="filter-title">Cluster sort</span>
              <select
                className="cluster-sort"
                value={clusterSort}
                onChange={(event) => setClusterSort(event.target.value as 'size' | 'external' | 'hot')}
              >
                <option value="size">size</option>
                <option value="external">external</option>
                <option value="hot">hot</option>
              </select>
            </div>
            <div className="filter-title">Quick Filters</div>
            {Object.keys(edgeTypeEnabled).sort().map((edgeType) => (
              <label key={edgeType}>
                <input
                  type="checkbox"
                  checked={Boolean(edgeTypeEnabled[edgeType])}
                  onChange={() => toggleEdgeType(edgeType)}
                />
                {' '}{edgeType}
              </label>
            ))}
            <div className="filter-title">Hub Top5</div>
            <div className="hub-list">
              {hubCandidates.map((hub, index) => (
                <button key={hub.id} className="hub-item" onClick={() => jumpToHub(hub.id)}>
                  #{index + 1} {hub.label} ({hub.degree})
                </button>
              ))}
              {hubCandidates.length === 0 ? <span className="muted">no hubs</span> : null}
            </div>
          </div>
        </aside>

        <main className="canvas-panel">
          <div ref={graphHostRef} className="graph-canvas" />
          {mode === 'detail' && selectedNodeId.trim() === '' ? (
            <div className="graph-empty-hint">
              <div className="graph-empty-title">Detail 준비 단계</div>
              <div>왼쪽에서 기능군을 선택하고 카드 또는 Hub Top5를 클릭한 뒤 Detail(2-hop)로 들어가세요.</div>
            </div>
          ) : null}
          {rendererBackend === 'canvas2d_fallback' && rendererError !== '' ? (
            <div className="graph-error">
              <div className="graph-error-title">WebGL 경로 실패</div>
              <div className="graph-error-body">Canvas2D 폴백으로 동작 중입니다.</div>
              <code className="graph-error-code">{rendererError}</code>
            </div>
          ) : null}
          {mode === 'detail' && boardFrame == null ? (
            <canvas ref={minimapRef} className="minimap" width={160} height={110} />
          ) : null}
        </main>

        <aside className="right-panel">
          <h3>Detail Inspector</h3>
          {selectedLinkSummary != null ? (
            <div className="summary-card">
              <div className="summary-title">Link Evidence</div>
              <div>{selectedLinkSummary.sourceTitle} → {selectedLinkSummary.targetTitle}</div>
              <div>Count: {selectedLinkSummary.count}</div>
              <div>Dominant: {selectedLinkSummary.dominantType}</div>
              <div className="muted">
                왜 연결됨: {selectedLinkSummary.sourceTitle}에서 {selectedLinkSummary.targetTitle}로
                {' '}
                {selectedLinkSummary.dominantType}
                {' '}
                관계가 가장 많이 관측되었습니다.
              </div>
              <div className="summary-list">
                <div className="muted">Type breakdown</div>
                {Object.entries(selectedLinkSummary.typeBreakdown)
                  .sort((a, b) => Number(b[1]) - Number(a[1]))
                  .map(([key, value]) => (
                    <div key={key}>{key}: {Number(value)}</div>
                  ))}
              </div>
              <div className="summary-list">
                <div className="muted">Evidence (top {Math.min(3, selectedLinkSummary.evidenceRefs.length)})</div>
                {selectedLinkSummary.evidenceRefs.slice(0, 3).map((ref, index) => {
                  const row = ref as Record<string, unknown>;
                  return (
                    <div key={`${selectedLinkSummary.id}-evidence-${index}`} className="link-evidence-row">
                      <div>{String(row.edge_type ?? 'unknown')} · {String(row.source_label ?? row.source_node ?? '-')} → {String(row.target_label ?? row.target_node ?? '-')}</div>
                      <small>{String(row.source_path ?? '')}{Number(row.source_line ?? -1) > 0 ? `:${Number(row.source_line)}` : ''}</small>
                    </div>
                  );
                })}
                {selectedLinkSummary.evidenceRefs.length === 0 ? <div className="muted">근거 데이터 없음</div> : null}
              </div>
            </div>
          ) : null}
          {selectedNode.id === '' && selectedClusterSummary == null ? (
            <div className="summary-card">
              <div className="summary-title">Start here</div>
              <div>1) 왼쪽 클러스터 클릭</div>
              <div>2) 카드 클릭으로 요약 확인</div>
              <div>3) 더블클릭으로 Detail 진입</div>
            </div>
          ) : null}
          {selectedClusterSummary != null && selectedNode.id === '' ? (
            <div className="summary-card">
              <div className="summary-title">{selectedClusterSummary.title}</div>
              {lastNavigationReason === 'more_click' && structuralExpandedLaneId.trim() !== '' ? (
                <div className="muted">`+more`로 확장된 레인입니다. 카드를 클릭해 요약을 확인하세요.</div>
              ) : null}
              <div>Nodes: {selectedClusterSummary.nodeCount}</div>
              <div>Files: {selectedClusterSummary.fileCount} · Classes: {selectedClusterSummary.classCount}</div>
              <div>Functions: {selectedClusterSummary.functionCount}</div>
              <div>External: {selectedClusterSummary.externalCount}</div>
              <div>Hot: {selectedClusterSummary.hot.toFixed(2)}</div>
              {!uiDefaults.structuralShowAllOnMore ? (
                <div className="muted">현재 설정은 전체 카드 확장을 제한합니다.</div>
              ) : null}
              <div className="inspector-actions">
                <button onClick={openClusterTopHotspot}>Top hotspot</button>
                <button onClick={openClusterDetail}>Detail 2-hop</button>
                <button onClick={() => selectedClusterId && rendererRef.current?.focusNode(selectedClusterId, 0.6)}>
                  Focus cluster
                </button>
              </div>
              {selectedClusterTopCards.length > 0 ? (
                <div className="summary-list">
                  <div className="muted">Top files/classes</div>
                  {selectedClusterTopCards.map((card) => (
                    <button
                      key={card.id}
                      className="summary-link"
                      onClick={() => {
                        selectNode(card.id);
                        rendererRef.current?.focusNode(card.id, 0.46);
                      }}
                    >
                      {card.title}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          {selectedNode.id !== '' ? (
            <>
              <div className="summary-card">
                <div className="summary-title">{selectedNode.label || selectedNode.id}</div>
                <div>Kind: {selectedNode.kind}</div>
                <div>Path: {selectedNode.path || '-'}</div>
                <div>Degree: in {selectedNode.inDegree} / out {selectedNode.outDegree}</div>
                <div>LOC: {selectedNode.loc}</div>
                {mode === 'detail' ? (
                  <div className="muted">
                    왜 보임: {selectedNodeScopeReason || 'anchor'} · {detailScopeSummary || 'related scope'}
                  </div>
                ) : null}
              </div>
              <div className="inspector-actions">
                <button onClick={() => selectedNodeId && drillToDetail(selectedNodeId, 1, 'manual_mode')}>1-hop</button>
                <button onClick={() => selectedNodeId && drillToDetail(selectedNodeId, 2, 'manual_mode')}>2-hop</button>
                <button onClick={() => selectedNodeId && drillToDetail(selectedNodeId, 3, 'manual_mode')}>3-hop</button>
                <button onClick={onShowPaths}>Show paths</button>
              </div>
              <button className="raw-toggle" onClick={toggleRawJson}>
                {rawJsonOpen ? 'Hide Raw JSON' : 'Show Raw JSON'}
              </button>
              {rawJsonOpen ? <pre className="raw-json">{JSON.stringify(selectedNode.metadata, null, 2)}</pre> : null}
            </>
          ) : null}
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
                  <button onClick={() => drillToDetail(item.nodeId, 2, 'search_focus')}>2-hop</button>
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
