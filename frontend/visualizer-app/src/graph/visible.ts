import type { ViewModel, ViewModelEdge, ViewModelNode, VisibleGraph } from '../types/visualizer';

const NODE_BUDGET = 5000;
const EDGE_BUDGET = 12000;

function edgeWeight(edge: ViewModelEdge): number {
  const count = Number((edge.metadata as Record<string, unknown> | undefined)?.count ?? 0);
  if (Number.isFinite(count) && count > 0) return count;
  const confidence = Number(edge.confidence ?? 1);
  if (Number.isFinite(confidence) && confidence > 0) return confidence;
  return 1;
}

function bfsKhop(adjacency: { in?: Record<string, string[]>; out?: Record<string, string[]> }, start: string, k: number): Set<string> {
  const seen = new Set<string>();
  if (!start) return seen;
  let frontier = new Set<string>([start]);
  seen.add(start);
  for (let depth = 0; depth < k; depth += 1) {
    const next = new Set<string>();
    for (const node of frontier) {
      const incoming = adjacency.in?.[node] ?? [];
      const outgoing = adjacency.out?.[node] ?? [];
      for (const neighbor of [...incoming, ...outgoing]) {
        if (!seen.has(neighbor)) {
          seen.add(neighbor);
          next.add(neighbor);
        }
      }
    }
    frontier = next;
    if (frontier.size === 0) break;
  }
  return seen;
}

function withCallsFilter(edges: ViewModelEdge[], callsEnabled: boolean): ViewModelEdge[] {
  if (callsEnabled) return edges;
  return edges.filter((edge) => edge.edge_type !== 'calls');
}

function withEdgeTypes(edges: ViewModelEdge[], enabled: Record<string, boolean>): ViewModelEdge[] {
  return edges.filter((edge) => enabled[edge.edge_type] !== false);
}

export function buildVisibleGraph(args: {
  viewModel: ViewModel;
  mode: 'cluster' | 'structural' | 'detail';
  focusScope: 'global' | 'clusterSubgraph' | 'kHop' | 'pathSubgraph';
  selectedNodeId: string;
  selectedClusterId: string;
  kHop: number;
  pathNodeIds: string[];
  callsEnabled: boolean;
  edgeTypeEnabled: Record<string, boolean>;
}): VisibleGraph {
  const { viewModel, mode, focusScope, selectedNodeId, selectedClusterId, kHop, pathNodeIds, callsEnabled, edgeTypeEnabled } = args;
  const layers = (viewModel.layers ?? {}) as Record<
    string,
    {
      node_ids?: string[];
      edge_ids?: string[];
      nodesById?: Record<string, ViewModelNode>;
      edgesById?: Record<string, ViewModelEdge>;
    }
  >;
  const layer = layers[mode];
  const rootNodes = viewModel.nodesById ?? {};
  const rootEdges = viewModel.edgesById ?? {};

  const layerNodesById =
    layer?.nodesById && Object.keys(layer.nodesById).length > 0 ? layer.nodesById : rootNodes;
  const layerEdgesById =
    layer?.edgesById && Object.keys(layer.edgesById).length > 0 ? layer.edgesById : rootEdges;

  let nodeIds = Array.isArray(layer?.node_ids) ? [...layer.node_ids] : Object.keys(layerNodesById);
  let edgeIds = Array.isArray(layer?.edge_ids) ? [...layer.edge_ids] : Object.keys(layerEdgesById);

  if (mode === 'structural' && selectedClusterId) {
    const cluster = (viewModel.clusters ?? []).find((item) => String(item.id) === selectedClusterId);
    const focusKey = String(cluster?.key ?? '').toLowerCase();
    if (focusKey !== '') {
      nodeIds = nodeIds.filter((id) => String(layerNodesById[id]?.folder_category ?? '').toLowerCase() === focusKey);
    }
  }

  if (mode === 'detail' && focusScope === 'kHop' && selectedNodeId) {
    const adjacency = viewModel.adjacency ?? {};
    const scope = bfsKhop(adjacency, selectedNodeId, Math.max(1, Math.min(3, kHop)));
    if (scope.size > 0) {
      nodeIds = nodeIds.filter((id) => scope.has(id));
    }
  }

  if (mode === 'detail' && focusScope === 'pathSubgraph' && pathNodeIds.length > 1) {
    const pathSet = new Set(pathNodeIds);
    nodeIds = nodeIds.filter((id) => pathSet.has(id));
  }

  const nodeSet = new Set(nodeIds);
  let edges = edgeIds
    .map((edgeId) => layerEdgesById[edgeId])
    .filter((edge): edge is ViewModelEdge => Boolean(edge))
    .filter((edge) => nodeSet.has(edge.source) && nodeSet.has(edge.target));

  edges = withEdgeTypes(withCallsFilter(edges, callsEnabled), edgeTypeEnabled);

  let sampled = false;
  if (edges.length > EDGE_BUDGET) {
    sampled = true;
    edges = [...edges].sort((a, b) => edgeWeight(b) - edgeWeight(a)).slice(0, EDGE_BUDGET);
    const keep = new Set<string>();
    for (const edge of edges) {
      keep.add(edge.source);
      keep.add(edge.target);
    }
    nodeIds = nodeIds.filter((id) => keep.has(id)).slice(0, NODE_BUDGET);
  } else if (nodeIds.length > NODE_BUDGET) {
    sampled = true;
    nodeIds = nodeIds.slice(0, NODE_BUDGET);
    const keep = new Set(nodeIds);
    edges = edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target));
  }

  const nodes: ViewModelNode[] = nodeIds
    .map((id) => layerNodesById[id] ?? rootNodes[id])
    .filter((node): node is ViewModelNode => Boolean(node));

  return {
    nodes,
    edges,
    sampled,
  };
}
