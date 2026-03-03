import type { VisualizerMode } from '../../types/visualizer';

export type RendererBackend = 'board_canvas' | 'webgl_sigma' | 'canvas2d_fallback';

export interface RenderNode {
  id: string;
  label: string;
  kind: string;
  color: string;
  size: number;
  x: number;
  y: number;
}

export interface RenderEdge {
  id: string;
  source: string;
  target: string;
  color: string;
  size: number;
}

export interface RenderFrame {
  nodes: RenderNode[];
  edges: RenderEdge[];
  mode: VisualizerMode;
  board?: {
    clusters: Array<{
      id: string;
      title: string;
      x: number;
      y: number;
      w: number;
      h: number;
      summary: {
        nodeCount: number;
        externalCount: number;
        hot: number;
        fileCount?: number;
        functionCount?: number;
        classCount?: number;
      };
      cards: Array<{
        id: string;
        title: string;
        kind: string;
        path?: string;
        x: number;
        y: number;
        w: number;
        h: number;
        stats: {
          inDegree: number;
          outDegree: number;
          loc: number;
          functions?: number;
          classes?: number;
          signals?: number;
          relation?: string;
          hop?: number;
        };
      }>;
      hiddenCards: number;
    }>;
    links: Array<{
      id: string;
      sourceClusterId: string;
      targetClusterId: string;
      sourceCardId?: string;
      targetCardId?: string;
      count: number;
      typeBreakdown?: Record<string, number>;
      evidenceRefs?: Array<Record<string, unknown>>;
      color?: string;
      style?: string;
      defaultVisible?: boolean;
    }>;
    legend?: Array<{
      edgeType: string;
      label: string;
      color: string;
      style: string;
      defaultVisible: boolean;
    }>;
  };
  selectedNodeId?: string;
  selectedClusterId?: string;
  selectedLinkId?: string;
}

export interface GraphRendererCallbacks {
  onNodeClick: (nodeId: string) => void;
  onNodeDoubleClick: (nodeId: string) => void;
  onMoreClick?: (clusterId: string) => void;
  onEdgeClick?: (edgeId: string) => void;
  onStageClick: () => void;
}

export interface GraphRenderer {
  readonly backend: RendererBackend;
  readonly error: string;
  init(container: HTMLElement): void;
  render(frame: RenderFrame): void;
  destroy(): void;
  fit(): void;
  focusNode(nodeId: string, ratio?: number): boolean;
}
