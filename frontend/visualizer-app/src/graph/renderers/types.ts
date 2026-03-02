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
      summary: { nodeCount: number; externalCount: number; hot: number };
      cards: Array<{
        id: string;
        title: string;
        kind: string;
        x: number;
        y: number;
        w: number;
        h: number;
        stats: { inDegree: number; outDegree: number; loc: number };
      }>;
      hiddenCards: number;
    }>;
    links: Array<{
      sourceClusterId: string;
      targetClusterId: string;
      count: number;
    }>;
  };
  selectedNodeId?: string;
  selectedClusterId?: string;
}

export interface GraphRendererCallbacks {
  onNodeClick: (nodeId: string) => void;
  onNodeDoubleClick: (nodeId: string) => void;
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
