import type { VisualizerMode } from '../../types/visualizer';

export type RendererBackend = 'webgl_sigma' | 'canvas2d_fallback';

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
