import type { GraphRenderer, GraphRendererCallbacks, RenderFrame, RenderNode } from './types';

interface PixelNode {
  id: string;
  x: number;
  y: number;
  r: number;
}

export class Canvas2DRenderer implements GraphRenderer {
  public readonly backend = 'canvas2d_fallback' as const;
  public error = '';

  private container: HTMLElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private ctx: CanvasRenderingContext2D | null = null;
  private callbacks: GraphRendererCallbacks;
  private frame: RenderFrame = { nodes: [], edges: [], mode: 'cluster' };
  private pixelNodes: PixelNode[] = [];
  private focusedNodeId = '';

  constructor(callbacks: GraphRendererCallbacks) {
    this.callbacks = callbacks;
  }

  init(container: HTMLElement): void {
    this.container = container;
    this.container.innerHTML = '';

    const canvas = document.createElement('canvas');
    canvas.className = 'graph-canvas-fallback';
    canvas.addEventListener('click', this.onClick);
    canvas.addEventListener('dblclick', this.onDoubleClick);

    this.container.appendChild(canvas);
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    if (this.ctx == null) {
      this.error = 'Canvas2D context unavailable';
      throw new Error(this.error);
    }

    window.addEventListener('resize', this.onResize);
    this.resize();
  }

  render(frame: RenderFrame): void {
    this.frame = frame;
    this.draw();
  }

  destroy(): void {
    window.removeEventListener('resize', this.onResize);
    if (this.canvas != null) {
      this.canvas.removeEventListener('click', this.onClick);
      this.canvas.removeEventListener('dblclick', this.onDoubleClick);
      this.canvas.remove();
    }
    this.canvas = null;
    this.ctx = null;
    this.container = null;
    this.pixelNodes = [];
    this.focusedNodeId = '';
  }

  fit(): void {
    this.focusedNodeId = '';
    this.draw();
  }

  focusNode(nodeId: string): boolean {
    this.focusedNodeId = nodeId;
    this.draw();
    return this.frame.nodes.some((node) => node.id === nodeId);
  }

  private onResize = (): void => {
    this.resize();
    this.draw();
  };

  private resize(): void {
    if (this.canvas == null) return;
    const rect = this.canvas.getBoundingClientRect();
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const width = Math.max(1, Math.round(rect.width * dpr));
    const height = Math.max(1, Math.round(rect.height * dpr));

    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }
  }

  private draw(): void {
    if (this.canvas == null || this.ctx == null) return;
    const ctx = this.ctx;
    const width = this.canvas.width;
    const height = this.canvas.height;

    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = '#071433';
    ctx.fillRect(0, 0, width, height);

    const point = (node: RenderNode): { x: number; y: number } => ({
      x: (node.x * 0.5 + 0.5) * width,
      y: (node.y * 0.5 + 0.5) * height,
    });

    const nodesById = new Map<string, RenderNode>();
    const pointsById = new Map<string, { x: number; y: number }>();
    for (const node of this.frame.nodes) {
      nodesById.set(node.id, node);
      pointsById.set(node.id, point(node));
    }

    this.pixelNodes = [];

    for (const edge of this.frame.edges) {
      const source = nodesById.get(edge.source);
      const target = nodesById.get(edge.target);
      if (source == null || target == null) continue;
      const sp = pointsById.get(source.id);
      const tp = pointsById.get(target.id);
      if (sp == null || tp == null) continue;

      ctx.beginPath();
      ctx.strokeStyle = edge.color;
      ctx.globalAlpha = 0.55;
      ctx.lineWidth = Math.max(1, edge.size);
      ctx.moveTo(sp.x, sp.y);
      ctx.lineTo(tp.x, tp.y);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    for (const node of this.frame.nodes) {
      const p = pointsById.get(node.id);
      if (p == null) continue;
      const radius = Math.max(3, node.size);
      this.pixelNodes.push({ id: node.id, x: p.x, y: p.y, r: radius + 4 });

      ctx.beginPath();
      ctx.arc(p.x, p.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = node.color;
      ctx.fill();

      if (this.focusedNodeId === node.id) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, radius + 4, 0, Math.PI * 2);
        ctx.strokeStyle = '#89ffd6';
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }
  }

  private onClick = (event: MouseEvent): void => {
    const nodeId = this.pickNode(event);
    if (nodeId == null) {
      this.callbacks.onStageClick();
      return;
    }
    this.callbacks.onNodeClick(nodeId);
  };

  private onDoubleClick = (event: MouseEvent): void => {
    const nodeId = this.pickNode(event);
    if (nodeId == null) {
      this.callbacks.onStageClick();
      return;
    }
    this.callbacks.onNodeDoubleClick(nodeId);
  };

  private pickNode(event: MouseEvent): string | null {
    if (this.canvas == null) return null;
    const rect = this.canvas.getBoundingClientRect();
    const dpr = Math.max(1, window.devicePixelRatio || 1);
    const x = (event.clientX - rect.left) * dpr;
    const y = (event.clientY - rect.top) * dpr;

    let best: PixelNode | null = null;
    let bestDistance = Number.POSITIVE_INFINITY;

    for (const node of this.pixelNodes) {
      const dx = x - node.x;
      const dy = y - node.y;
      const distance = Math.sqrt(dx * dx + dy * dy);
      if (distance <= node.r && distance < bestDistance) {
        best = node;
        bestDistance = distance;
      }
    }

    return best?.id ?? null;
  }
}
