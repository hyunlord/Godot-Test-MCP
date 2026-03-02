import Graph from 'graphology';
import Sigma from 'sigma';

import type { GraphRenderer, GraphRendererCallbacks, RenderFrame } from './types';

export class SigmaRenderer implements GraphRenderer {
  public readonly backend = 'webgl_sigma' as const;
  public error = '';

  private container: HTMLElement | null = null;
  private sigma: Sigma | null = null;
  private callbacks: GraphRendererCallbacks;

  constructor(callbacks: GraphRendererCallbacks) {
    this.callbacks = callbacks;
  }

  init(container: HTMLElement): void {
    this.container = container;
    this.container.innerHTML = '';
  }

  render(frame: RenderFrame): void {
    if (this.container == null) {
      throw new Error('sigma renderer is not initialized');
    }

    const graph = new Graph();
    for (const node of frame.nodes) {
      graph.addNode(node.id, {
        x: node.x,
        y: node.y,
        size: node.size,
        label: node.label,
        color: node.color,
      });
    }

    for (const edge of frame.edges) {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
      const key = edge.id || `${edge.source}->${edge.target}`;
      if (graph.hasEdge(key)) continue;
      graph.addEdgeWithKey(key, edge.source, edge.target, {
        size: edge.size,
        color: edge.color,
      });
    }

    this.sigma?.kill();
    this.sigma = null;

    try {
      this.sigma = new Sigma(graph, this.container, {
        renderLabels: frame.mode !== 'cluster',
        renderEdgeLabels: false,
        labelDensity: 0.08,
        labelGridCellSize: 100,
        minCameraRatio: 0.03,
        maxCameraRatio: 30.0,
        allowInvalidContainer: true,
      });
      this.error = '';
    } catch (error) {
      this.error = String(error);
      throw error;
    }

    this.sigma.on('clickNode', ({ node }) => {
      this.callbacks.onNodeClick(String(node));
    });

    this.sigma.on('doubleClickNode', ({ node }) => {
      this.callbacks.onNodeDoubleClick(String(node));
    });

    this.sigma.on('clickStage', () => {
      this.callbacks.onStageClick();
    });
  }

  destroy(): void {
    this.sigma?.kill();
    this.sigma = null;
    if (this.container != null) {
      this.container.innerHTML = '';
    }
  }

  fit(): void {
    if (this.sigma == null) return;
    this.sigma.getCamera().animatedReset({ duration: 220 });
  }

  focusNode(nodeId: string, ratio = 0.45): boolean {
    if (this.sigma == null) return false;
    const graph = this.sigma.getGraph();
    if (!graph.hasNode(nodeId)) return false;
    const attrs = graph.getNodeAttributes(nodeId) as { x?: number; y?: number };
    if (!Number.isFinite(attrs.x) || !Number.isFinite(attrs.y)) return false;
    this.sigma.getCamera().animate(
      { x: Number(attrs.x), y: Number(attrs.y), ratio },
      { duration: 280 },
    );
    return true;
  }
}
