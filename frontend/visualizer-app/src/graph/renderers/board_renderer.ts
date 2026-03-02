import type { GraphRenderer, GraphRendererCallbacks, RenderFrame } from './types';

const CANVAS_PADDING = 28;

export class BoardRenderer implements GraphRenderer {
  public readonly backend = 'board_canvas' as const;
  public error = '';

  private container: HTMLElement | null = null;
  private root: HTMLDivElement | null = null;
  private callbacks: GraphRendererCallbacks;
  private frame: RenderFrame = { nodes: [], edges: [], mode: 'cluster' };
  private nodeElements = new Map<string, HTMLElement>();
  private clusterElements = new Map<string, HTMLElement>();
  private focusedElement: HTMLElement | null = null;

  constructor(callbacks: GraphRendererCallbacks) {
    this.callbacks = callbacks;
  }

  init(container: HTMLElement): void {
    this.container = container;
    this.container.innerHTML = '';

    const root = document.createElement('div');
    root.className = 'board-root';
    root.addEventListener('click', this.onStageClick);

    this.container.appendChild(root);
    this.root = root;
  }

  render(frame: RenderFrame): void {
    this.frame = frame;
    this.draw();
  }

  destroy(): void {
    if (this.root != null) {
      this.root.removeEventListener('click', this.onStageClick);
      this.root.remove();
    }
    this.container = null;
    this.root = null;
    this.nodeElements.clear();
    this.clusterElements.clear();
    this.focusedElement = null;
  }

  fit(): void {
    if (this.root == null) return;
    this.root.scrollTo({ top: 0, left: 0, behavior: 'smooth' });
  }

  focusNode(nodeId: string): boolean {
    const target = this.nodeElements.get(nodeId) ?? this.clusterElements.get(nodeId) ?? null;
    if (target == null) return false;

    if (this.focusedElement != null) {
      this.focusedElement.classList.remove('is-focused');
    }
    target.classList.add('is-focused');
    this.focusedElement = target;
    target.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
    return true;
  }

  private onStageClick = (event: MouseEvent): void => {
    if (event.target !== this.root) return;
    this.callbacks.onStageClick();
  };

  private draw(): void {
    if (this.root == null) return;
    this.root.innerHTML = '';
    this.nodeElements.clear();
    this.clusterElements.clear();
    this.focusedElement = null;

    const board = this.frame.board;
    if (board == null || board.clusters.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'board-empty';
      empty.textContent = 'No board data';
      this.root.appendChild(empty);
      return;
    }

    const bounds = this.bounds(board.clusters);
    const width = Math.max(1, this.root.clientWidth);
    const height = Math.max(1, this.root.clientHeight);
    const fitScale = Math.min(
      (width - CANVAS_PADDING * 2) / Math.max(1, bounds.width),
      (height - CANVAS_PADDING * 2) / Math.max(1, bounds.height),
    );
    const scale = Math.max(0.32, Math.min(1.0, fitScale));
    const offsetX = CANVAS_PADDING + ((width - CANVAS_PADDING * 2) - bounds.width * scale) / 2;
    const offsetY = CANVAS_PADDING + ((height - CANVAS_PADDING * 2) - bounds.height * scale) / 2;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'board-links');
    svg.setAttribute('width', String(width));
    svg.setAttribute('height', String(height));
    this.root.appendChild(svg);

    const clusterLookup = new Map(board.clusters.map((cluster) => [cluster.id, cluster]));

    for (const link of board.links) {
      const source = clusterLookup.get(link.sourceClusterId);
      const target = clusterLookup.get(link.targetClusterId);
      if (source == null || target == null) continue;

      const sx = offsetX + (source.x - bounds.minX + source.w / 2) * scale;
      const sy = offsetY + (source.y - bounds.minY + source.h / 2) * scale;
      const tx = offsetX + (target.x - bounds.minX + target.w / 2) * scale;
      const ty = offsetY + (target.y - bounds.minY + target.h / 2) * scale;
      const curve = Math.max(28, Math.abs(tx - sx) * 0.32);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('class', 'board-link');
      path.setAttribute('d', `M ${sx} ${sy} C ${sx + curve} ${sy}, ${tx - curve} ${ty}, ${tx} ${ty}`);
      path.setAttribute('stroke-width', String(Math.min(6, 1 + Math.log2(1 + Math.max(1, link.count)))));
      svg.appendChild(path);
    }

    for (const cluster of board.clusters) {
      const panel = document.createElement('section');
      panel.className = 'board-cluster';
      if (this.frame.selectedClusterId === cluster.id) {
        panel.classList.add('is-selected');
      }
      panel.style.left = `${offsetX + (cluster.x - bounds.minX) * scale}px`;
      panel.style.top = `${offsetY + (cluster.y - bounds.minY) * scale}px`;
      panel.style.width = `${Math.max(220, cluster.w * scale)}px`;
      panel.style.height = `${Math.max(140, cluster.h * scale)}px`;
      panel.dataset.clusterId = cluster.id;

      panel.addEventListener('click', (event) => {
        event.stopPropagation();
        this.callbacks.onNodeClick(cluster.id);
      });
      panel.addEventListener('dblclick', (event) => {
        event.stopPropagation();
        this.callbacks.onNodeDoubleClick(cluster.id);
      });

      const header = document.createElement('header');
      header.className = 'board-cluster-header';
      const title = document.createElement('h4');
      title.textContent = cluster.title;
      const summary = document.createElement('span');
      summary.textContent = `${cluster.summary.nodeCount} nodes · ext ${cluster.summary.externalCount} · hot ${cluster.summary.hot.toFixed(1)}`;
      header.appendChild(title);
      header.appendChild(summary);
      panel.appendChild(header);

      const cards = document.createElement('div');
      cards.className = 'board-cards';
      panel.appendChild(cards);

      for (const card of cluster.cards) {
        const cardButton = document.createElement('button');
        cardButton.className = 'board-card';
        if (this.frame.selectedNodeId === card.id) {
          cardButton.classList.add('is-selected');
        }

        const cardX = Math.max(8, (card.x - cluster.x) * scale);
        const cardY = Math.max(36, (card.y - cluster.y) * scale);
        const cardW = Math.max(140, card.w * scale);
        const cardH = Math.max(46, card.h * scale);
        cardButton.style.left = `${cardX}px`;
        cardButton.style.top = `${cardY}px`;
        cardButton.style.width = `${cardW}px`;
        cardButton.style.height = `${cardH}px`;
        cardButton.innerHTML = `<strong>${card.title}</strong><small>${card.kind} · ${card.stats.inDegree}i ${card.stats.outDegree}o · ${card.stats.loc}L</small>`;
        cardButton.addEventListener('click', (event) => {
          event.stopPropagation();
          this.callbacks.onNodeClick(card.id);
        });
        cardButton.addEventListener('dblclick', (event) => {
          event.stopPropagation();
          this.callbacks.onNodeDoubleClick(card.id);
        });
        cards.appendChild(cardButton);
        this.nodeElements.set(card.id, cardButton);
      }

      if (cluster.hiddenCards > 0) {
        const more = document.createElement('div');
        more.className = 'board-more';
        more.textContent = `+${cluster.hiddenCards} more`;
        panel.appendChild(more);
      }

      this.clusterElements.set(cluster.id, panel);
      this.root.appendChild(panel);
    }
  }

  private bounds(
    clusters: Array<{
      x: number;
      y: number;
      w: number;
      h: number;
    }>,
  ): { minX: number; minY: number; width: number; height: number } {
    let minX = Number.POSITIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;
    for (const cluster of clusters) {
      minX = Math.min(minX, cluster.x);
      minY = Math.min(minY, cluster.y);
      maxX = Math.max(maxX, cluster.x + cluster.w);
      maxY = Math.max(maxY, cluster.y + cluster.h);
    }
    return {
      minX,
      minY,
      width: Math.max(1, maxX - minX),
      height: Math.max(1, maxY - minY),
    };
  }
}
