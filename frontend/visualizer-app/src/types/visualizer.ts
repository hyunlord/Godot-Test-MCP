export type VisualizerMode = 'cluster' | 'structural' | 'detail';
export type FocusScope = 'global' | 'clusterSubgraph' | 'kHop' | 'pathSubgraph';
export type OverlayState = 'none' | 'searchOpen' | 'error' | 'empty' | 'densityWarning';
export type NavigationReason = 'cluster_click' | 'more_click' | 'search_focus' | 'guided_flow' | 'manual_mode';

export interface UIFlowState {
  lastNavigationReason: NavigationReason;
  structuralExpandedLaneId: string;
}

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

export interface BoardCard {
  id: string;
  title: string;
  kind: string;
  path?: string;
  stats?: { in?: number; out?: number; loc?: number; functions?: number; classes?: number; signals?: number };
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface BoardCluster {
  id: string;
  title: string;
  rect: { x: number; y: number; w: number; h: number };
  cards: BoardCard[];
  summary?: {
    node_count?: number;
    external_count?: number;
    hot?: number;
    file_count?: number;
    function_count?: number;
    class_count?: number;
    signal_count?: number;
  };
}

export interface BoardLink {
  source_cluster: string;
  target_cluster: string;
  count: number;
}

export interface BoardHotspot {
  node_id: string;
  label: string;
  degree: number;
  cluster_id?: string;
}

export interface BoardModel {
  clusters: BoardCluster[];
  links: BoardLink[];
  hotspots: BoardHotspot[];
}

export interface BoardV2LegendItem {
  edge_type: string;
  label: string;
  color: string;
  style: string;
  default_visible: boolean;
}

export interface BoardV2Card {
  id: string;
  group_id: string;
  title: string;
  kind: string;
  path: string;
  lane_key: string;
  confidence: number;
  source_signals: string[];
  stats: { in: number; out: number; loc: number; functions: number; classes: number; signals: number };
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface BoardV2Lane {
  id: string;
  key: string;
  title: string;
  rect: { x: number; y: number; w: number; h: number };
  cards: BoardV2Card[];
  hidden_items_count: number;
  summary: {
    node_count: number;
    file_count: number;
    function_count: number;
    class_count: number;
    signal_count: number;
    hot: number;
    preview_card_count?: number;
    total_card_count?: number;
  };
}

export interface BoardV2LinkEvidence {
  source_node: string;
  target_node: string;
  edge_type: string;
  source_label: string;
  target_label: string;
  source_path: string;
  target_path: string;
  source_line: number;
  target_line: number;
}

export interface BoardV2Link {
  id: string;
  source_lane: string;
  target_lane: string;
  count: number;
  type_breakdown: Record<string, number>;
  evidence_refs: BoardV2LinkEvidence[];
  points?: { sx: number; sy: number; c1x: number; c1y: number; c2x: number; c2y: number; tx: number; ty: number };
}

export interface BoardModelV2 {
  lanes: BoardV2Lane[];
  links: BoardV2Link[];
  legend: BoardV2LegendItem[];
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
    renderer_backend?: string;
    renderer_error_code?: string;
    renderer_error?: string;
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
    detail_requires_anchor?: boolean;
    structural_autoselect?: string;
    cluster_preview_card_limit?: number;
    structural_show_all_on_more?: boolean;
  };
  cluster_layout_health?: {
    overlap_count?: number;
    duplicate_anchor_count?: number;
    max_density_band?: string;
  };
  board_model?: BoardModel;
  board_model_v2?: BoardModelV2;
  classification?: {
    lane_strategy?: string;
    confidence?: number;
    source_signals?: Record<string, string[]>;
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
    detail_requires_anchor?: boolean;
    structural_autoselect?: string;
    cluster_preview_card_limit?: number;
    structural_show_all_on_more?: boolean;
  };
  cluster_layout_health?: {
    overlap_count?: number;
    duplicate_anchor_count?: number;
    max_density_band?: string;
  };
  board_model?: BoardModel;
  board_model_v2?: BoardModelV2;
  classification?: {
    lane_strategy?: string;
    confidence?: number;
    source_signals?: Record<string, string[]>;
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
