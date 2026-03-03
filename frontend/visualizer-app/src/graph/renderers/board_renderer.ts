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
    this.root.className = `board-root mode-${this.frame.mode}`;
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
    const scale = this.frame.mode === 'cluster'
      ? Math.max(0.9, Math.min(1.0, fitScale))
      : 1.0;
    const contentWidth = Math.max(width, Math.round(bounds.width * scale + CANVAS_PADDING * 2));
    const contentHeight = Math.max(height, Math.round(bounds.height * scale + CANVAS_PADDING * 2));
    this.root.style.width = `${contentWidth}px`;
    this.root.style.height = `${contentHeight}px`;
    const offsetX = this.frame.mode === 'cluster'
      ? CANVAS_PADDING + ((contentWidth - CANVAS_PADDING * 2) - bounds.width * scale) / 2
      : CANVAS_PADDING;
    const offsetY = this.frame.mode === 'cluster'
      ? CANVAS_PADDING + ((contentHeight - CANVAS_PADDING * 2) - bounds.height * scale) / 2
      : CANVAS_PADDING;

    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'board-links');
    svg.setAttribute('width', String(contentWidth));
    svg.setAttribute('height', String(contentHeight));
    this.root.appendChild(svg);

    const clusterLookup = new Map(board.clusters.map((cluster) => [cluster.id, cluster]));
    const cardCenterLookup = new Map<string, { x: number; y: number }>();
    for (const cluster of board.clusters) {
      const clusterOffsetX = offsetX + (cluster.x - bounds.minX) * scale;
      const clusterOffsetY = offsetY + (cluster.y - bounds.minY) * scale;
      for (const card of cluster.cards) {
        const cardX = Math.max(8, (card.x - cluster.x) * scale);
        const cardY = Math.max(36, (card.y - cluster.y) * scale);
        const minCardW = this.frame.mode === 'cluster' ? 188 : this.frame.mode === 'detail' ? 232 : 208;
        const minCardH = this.frame.mode === 'cluster' ? 76 : this.frame.mode === 'detail' ? 90 : 82;
        const cardW = Math.max(minCardW, card.w * scale);
        const cardH = Math.max(minCardH, card.h * scale);
        cardCenterLookup.set(card.id, {
          x: clusterOffsetX + cardX + cardW / 2,
          y: clusterOffsetY + cardY + cardH / 2,
        });
      }
    }

    for (const link of board.links) {
      let sx = 0;
      let sy = 0;
      let tx = 0;
      let ty = 0;
      let cardLink = false;
      if (typeof link.sourceCardId === 'string' && typeof link.targetCardId === 'string') {
        const sourceCard = cardCenterLookup.get(link.sourceCardId);
        const targetCard = cardCenterLookup.get(link.targetCardId);
        if (sourceCard != null && targetCard != null) {
          sx = sourceCard.x;
          sy = sourceCard.y;
          tx = targetCard.x;
          ty = targetCard.y;
          cardLink = true;
        }
      }
      if (!cardLink) {
        const source = clusterLookup.get(link.sourceClusterId);
        const target = clusterLookup.get(link.targetClusterId);
        if (source == null || target == null) continue;
        sx = offsetX + (source.x - bounds.minX + source.w / 2) * scale;
        sy = offsetY + (source.y - bounds.minY + source.h / 2) * scale;
        tx = offsetX + (target.x - bounds.minX + target.w / 2) * scale;
        ty = offsetY + (target.y - bounds.minY + target.h / 2) * scale;
      }
      const curve = cardLink
        ? Math.max(14, Math.abs(tx - sx) * 0.22)
        : Math.max(28, Math.abs(tx - sx) * 0.32);
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('class', 'board-link');
      if (cardLink) path.classList.add('is-card');
      if (this.frame.selectedLinkId === link.id) {
        path.classList.add('is-selected');
      }
      path.setAttribute('d', `M ${sx} ${sy} C ${sx + curve} ${sy}, ${tx - curve} ${ty}, ${tx} ${ty}`);
      path.setAttribute('stroke-width', String(Math.min(6, 1 + Math.log2(1 + Math.max(1, link.count)))));
      if (typeof link.color === 'string' && link.color.trim() !== '') {
        path.setAttribute('stroke', link.color);
      }
      if (link.style === 'dashed') {
        path.setAttribute('stroke-dasharray', '8 6');
      } else if (link.style === 'dotted') {
        path.setAttribute('stroke-dasharray', '2 6');
      }
      svg.appendChild(path);

      if (typeof this.callbacks.onEdgeClick === 'function') {
        const hit = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        hit.setAttribute('class', 'board-link-hit');
        hit.setAttribute('d', path.getAttribute('d') ?? '');
        hit.addEventListener('click', (event) => {
          event.stopPropagation();
          this.callbacks.onEdgeClick?.(link.id);
        });
        svg.appendChild(hit);
      }
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
      const summaryParts = [
        `${cluster.summary.nodeCount} nodes`,
        `files ${Number(cluster.summary.fileCount ?? 0)}`,
        `ext ${cluster.summary.externalCount}`,
        `hot ${cluster.summary.hot.toFixed(1)}`,
      ];
      summary.textContent = summaryParts.join(' · ');
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
        const minCardW = this.frame.mode === 'cluster' ? 188 : this.frame.mode === 'detail' ? 232 : 208;
        const minCardH = this.frame.mode === 'cluster' ? 76 : this.frame.mode === 'detail' ? 90 : 82;
        const cardW = Math.max(minCardW, card.w * scale);
        const cardH = Math.max(minCardH, card.h * scale);
        cardButton.style.left = `${cardX}px`;
        cardButton.style.top = `${cardY}px`;
        cardButton.style.width = `${cardW}px`;
        cardButton.style.height = `${cardH}px`;
        const detailParts = [
          card.kind,
          `${card.stats.inDegree}i ${card.stats.outDegree}o`,
          `${card.stats.loc}L`,
        ];
        if (typeof card.stats.relation === 'string' && card.stats.relation.trim() !== '') {
          detailParts.unshift(card.stats.relation);
        }
        if (Number(card.stats.functions ?? 0) > 0) {
          detailParts.push(`${Number(card.stats.functions)}f`);
        }
        cardButton.innerHTML = `<strong>${card.title}</strong><small>${detailParts.join(' · ')}</small>`;
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
        const more = document.createElement('button');
        more.className = 'board-more';
        more.type = 'button';
        more.textContent = `+${cluster.hiddenCards} more 펼치기`;
        more.title = '클릭하면 Structural로 이동해 숨겨진 카드를 볼 수 있습니다.';
        more.addEventListener('click', (event) => {
          event.stopPropagation();
          if (typeof this.callbacks.onMoreClick === 'function') {
            this.callbacks.onMoreClick(cluster.id);
            return;
          }
          this.callbacks.onNodeDoubleClick(cluster.id);
        });
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
