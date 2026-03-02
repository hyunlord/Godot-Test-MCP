export type VisualizerMode = 'cluster' | 'structural' | 'detail';
export type FocusScope = 'global' | 'clusterSubgraph' | 'kHop' | 'pathSubgraph';
export type OverlayState = 'none' | 'searchOpen' | 'error' | 'empty' | 'densityWarning';

export interface BundleNode {
  id: string;
  kind: string;
  cluster_id: string;
  label_i: number;
  path_i: number;
  metrics?: { in?: number; out?: number; hot?: number; loc?: number };
}

export interface BundleEdge {
  s: string;
  t: string;
  type: string;
  w?: number;
}

export interface BundleCluster {
  id: string;
  label_i: number;
  key_i: number;
  node_ids: string[];
  metrics?: { size?: number; external_w?: number; hot?: number };
}

export interface GraphBundle {
  schema_version: string;
  meta: {
    run_id?: string;
    project?: string;
    generated_at?: number;
    node_count?: number;
    edge_count?: number;
    runtime_source?: string;
  };
  string_pool: string[];
  node_kinds: string[];
  edge_types: string[];
  nodes: BundleNode[];
  edges: BundleEdge[];
  calls_edges: BundleEdge[];
  clusters: BundleCluster[];
  cluster_edges: Array<{ cs: string; ct: string; w?: number; types?: Record<string, number> }>;
  search_index?: { items?: Array<{ key_i: number; node_id: string; kind: string; path_i?: number }> };
  layouts?: Record<string, { positions?: Record<string, [number, number]> }>;
  ui_defaults?: {
    default_layer?: VisualizerMode;
    hidden_edge_types?: string[];
    collapsed_kinds?: string[];
    focus_cluster?: string;
  };
}

export interface ViewModelNode {
  id: string;
  kind: string;
  label: string;
  path?: string;
  folder_category?: string;
  language?: string;
  metadata?: Record<string, unknown>;
  metrics?: { in_degree?: number; out_degree?: number; loc?: number };
  layout?: { x?: number; y?: number; w?: number; h?: number; cluster_id?: string };
}

export interface ViewModelEdge {
  id: string;
  source: string;
  target: string;
  edge_type: string;
  confidence?: number;
  metadata?: Record<string, unknown>;
}

export interface ViewModelLayer {
  node_ids: string[];
  edge_ids: string[];
  nodesById?: Record<string, ViewModelNode>;
  edgesById?: Record<string, ViewModelEdge>;
}

export interface ViewModel {
  nodesById: Record<string, ViewModelNode>;
  edgesById: Record<string, ViewModelEdge>;
  adjacency?: { in?: Record<string, string[]>; out?: Record<string, string[]> };
  clusters?: Array<{ id: string; key: string; title: string; node_count: number }>;
  layers?: Record<VisualizerMode, ViewModelLayer>;
  ui_defaults?: {
    default_layer?: VisualizerMode;
    hidden_edge_types?: string[];
    focus_cluster?: string;
  };
}

export interface VisualizerPayload {
  i18n?: Record<string, Record<string, string>>;
  meta?: Record<string, unknown>;
  map?: Record<string, unknown>;
  timeline?: Record<string, unknown>;
  causality?: Record<string, unknown>;
  diff?: Record<string, unknown>;
  view_model?: ViewModel;
  graph_bundle?: GraphBundle;
}

export interface SearchResultItem {
  nodeId: string;
  label: string;
  path: string;
  kind: string;
}

export interface VisibleGraph {
  nodes: ViewModelNode[];
  edges: ViewModelEdge[];
  sampled: boolean;
}
