import { create } from 'zustand';
import type {
  FocusScope,
  GraphBundle,
  OverlayState,
  SearchResultItem,
  ViewModel,
  VisualizerMode,
  VisualizerPayload,
} from '../types/visualizer';

export interface HistoryEntry {
  mode: VisualizerMode;
  selectedNodeId: string;
  selectedClusterId: string;
  focusScope: FocusScope;
  kHop: number;
  pathNodeIds: string[];
}

interface StoreState {
  payload: VisualizerPayload;
  bundle: GraphBundle | null;
  viewModel: ViewModel | null;
  mode: VisualizerMode;
  focusScope: FocusScope;
  kHop: number;
  pathNodeIds: string[];
  overlay: OverlayState;
  callsEnabled: boolean;
  selectedNodeId: string;
  selectedClusterId: string;
  edgeTypeEnabled: Record<string, boolean>;
  searchQuery: string;
  searchResults: SearchResultItem[];
  searchIndex: number;
  history: HistoryEntry[];
  historyIndex: number;
  visibleNodeCount: number;
  visibleEdgeCount: number;
  edgesSampled: boolean;
  toast: string;
  rawJsonOpen: boolean;
  diagnosticsCollapsed: boolean;

  hydrate: (payload: VisualizerPayload) => void;
  setMode: (mode: VisualizerMode) => void;
  setOverlay: (overlay: OverlayState) => void;
  setSearchQuery: (query: string) => void;
  setSearchResults: (results: SearchResultItem[]) => void;
  selectNode: (nodeId: string) => void;
  selectCluster: (clusterId: string) => void;
  drillToCluster: (clusterId: string) => void;
  drillToDetail: (nodeId: string, hop?: number) => void;
  showPathScope: (pathNodeIds: string[]) => void;
  toggleEdgeType: (edgeType: string) => void;
  toggleCalls: () => void;
  setVisibleMetrics: (nodeCount: number, edgeCount: number, sampled: boolean) => void;
  setSearchIndex: (index: number) => void;
  pushHistory: () => void;
  goBack: () => void;
  goForward: () => void;
  setToast: (message: string) => void;
  toggleRawJson: () => void;
  toggleDiagnosticsCollapsed: () => void;
}

const INITIAL_HISTORY: HistoryEntry = {
  mode: 'cluster',
  selectedNodeId: '',
  selectedClusterId: '',
  focusScope: 'global',
  kHop: 2,
  pathNodeIds: [],
};

export const useVisualizerStore = create<StoreState>((set, get) => ({
  payload: {},
  bundle: null,
  viewModel: null,
  mode: 'cluster',
  focusScope: 'global',
  kHop: 2,
  pathNodeIds: [],
  overlay: 'none',
  callsEnabled: false,
  selectedNodeId: '',
  selectedClusterId: '',
  edgeTypeEnabled: {},
  searchQuery: '',
  searchResults: [],
  searchIndex: 0,
  history: [INITIAL_HISTORY],
  historyIndex: 0,
  visibleNodeCount: 0,
  visibleEdgeCount: 0,
  edgesSampled: false,
  toast: '',
  rawJsonOpen: false,
  diagnosticsCollapsed: false,

  hydrate: (payload) => {
    const bundle = payload.graph_bundle ?? null;
    const viewModel = payload.view_model ?? null;
    const defaultMode = bundle?.ui_defaults?.default_layer ?? viewModel?.ui_defaults?.default_layer ?? 'cluster';

    const edgeEnabled: Record<string, boolean> = {};
    const edgeTypes = Array.isArray(bundle?.edge_types) ? bundle!.edge_types : [];
    for (const edgeType of edgeTypes) {
      edgeEnabled[edgeType] = edgeType !== 'calls';
    }
    if (!('calls' in edgeEnabled)) edgeEnabled.calls = false;

    set({
      payload,
      bundle,
      viewModel,
      mode: defaultMode,
      edgeTypeEnabled: edgeEnabled,
      callsEnabled: false,
      selectedNodeId: '',
      selectedClusterId: viewModel?.ui_defaults?.focus_cluster ?? '',
      focusScope: 'global',
      kHop: 2,
      pathNodeIds: [],
      history: [
        {
          mode: defaultMode,
          selectedNodeId: '',
          selectedClusterId: viewModel?.ui_defaults?.focus_cluster ?? '',
          focusScope: 'global',
          kHop: 2,
          pathNodeIds: [],
        },
      ],
      historyIndex: 0,
    });
  },

  setMode: (mode) => set({ mode }),

  setOverlay: (overlay) => set({ overlay }),

  setSearchQuery: (query) => set({ searchQuery: query }),

  setSearchResults: (results) =>
    set({
      searchResults: results,
      searchIndex: 0,
      overlay: results.length > 0 ? 'searchOpen' : get().searchQuery.trim() ? 'searchOpen' : 'none',
    }),

  setSearchIndex: (index) => set({ searchIndex: index }),

  selectNode: (nodeId) =>
    set({
      selectedNodeId: nodeId,
      selectedClusterId: '',
      focusScope: get().mode === 'detail' ? 'kHop' : get().focusScope,
      pathNodeIds: [],
    }),

  selectCluster: (clusterId) =>
    set({
      selectedClusterId: clusterId,
      selectedNodeId: '',
      focusScope: 'clusterSubgraph',
      pathNodeIds: [],
    }),

  drillToCluster: (clusterId) => {
    set({
      mode: 'structural',
      selectedClusterId: clusterId,
      selectedNodeId: '',
      focusScope: 'clusterSubgraph',
      kHop: 2,
      pathNodeIds: [],
    });
    get().pushHistory();
  },

  drillToDetail: (nodeId, hop = 2) => {
    set({
      mode: 'detail',
      selectedNodeId: nodeId,
      selectedClusterId: '',
      focusScope: 'kHop',
      kHop: Math.max(1, Math.min(3, hop)),
      pathNodeIds: [],
    });
    get().pushHistory();
  },

  showPathScope: (pathNodeIds) => {
    const cleaned = pathNodeIds.filter((value) => value.trim() !== '');
    set({
      mode: 'detail',
      focusScope: cleaned.length > 1 ? 'pathSubgraph' : get().focusScope,
      pathNodeIds: cleaned,
    });
    if (cleaned.length > 1) {
      get().pushHistory();
    }
  },

  toggleEdgeType: (edgeType) => {
    const current = get().edgeTypeEnabled;
    const next = !Boolean(current[edgeType]);
    set({ edgeTypeEnabled: { ...current, [edgeType]: next } });
  },

  toggleCalls: () => {
    const mode = get().mode;
    if (mode !== 'detail') {
      set({ toast: 'calls edge는 Detail 모드에서만 표시됩니다.' });
      return;
    }
    const enabled = !get().callsEnabled;
    const current = { ...get().edgeTypeEnabled, calls: enabled };
    set({
      callsEnabled: enabled,
      edgeTypeEnabled: current,
      focusScope: enabled ? 'kHop' : get().focusScope,
      kHop: enabled ? Math.min(2, get().kHop) : get().kHop,
      pathNodeIds: enabled ? [] : get().pathNodeIds,
    });
  },

  setVisibleMetrics: (nodeCount, edgeCount, sampled) =>
    set({
      visibleNodeCount: nodeCount,
      visibleEdgeCount: edgeCount,
      edgesSampled: sampled,
      overlay: edgeCount > 12000 ? 'densityWarning' : get().overlay === 'densityWarning' ? 'none' : get().overlay,
    }),

  pushHistory: () => {
    const state = get();
    const entry: HistoryEntry = {
      mode: state.mode,
      selectedNodeId: state.selectedNodeId,
      selectedClusterId: state.selectedClusterId,
      focusScope: state.focusScope,
      kHop: state.kHop,
      pathNodeIds: state.pathNodeIds,
    };
    const head = state.history.slice(0, state.historyIndex + 1);
    head.push(entry);
    set({ history: head.slice(-100), historyIndex: Math.min(head.length - 1, 99) });
  },

  goBack: () => {
    const state = get();
    if (state.historyIndex <= 0) return;
    const nextIndex = state.historyIndex - 1;
    const entry = state.history[nextIndex];
    set({ ...entry, historyIndex: nextIndex });
  },

  goForward: () => {
    const state = get();
    if (state.historyIndex >= state.history.length - 1) return;
    const nextIndex = state.historyIndex + 1;
    const entry = state.history[nextIndex];
    set({ ...entry, historyIndex: nextIndex });
  },

  setToast: (message) => set({ toast: message }),

  toggleRawJson: () => set({ rawJsonOpen: !get().rawJsonOpen }),

  toggleDiagnosticsCollapsed: () => set({ diagnosticsCollapsed: !get().diagnosticsCollapsed }),
}));
