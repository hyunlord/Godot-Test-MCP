interface SearchItem {
  key_i: number;
  node_id: string;
  kind: string;
  path_i?: number;
}

interface IndexPayload {
  stringPool: string[];
  items: SearchItem[];
}

interface SearchPayload {
  query: string;
  limit: number;
}

let pool: string[] = [];
let items: SearchItem[] = [];

self.onmessage = (event: MessageEvent) => {
  const data = event.data as { type: string; payload?: unknown };
  if (data.type === 'index') {
    const payload = data.payload as IndexPayload;
    pool = Array.isArray(payload?.stringPool) ? payload.stringPool : [];
    items = Array.isArray(payload?.items) ? payload.items : [];
    return;
  }

  if (data.type === 'search') {
    const payload = data.payload as SearchPayload;
    const query = String(payload?.query ?? '').trim().toLowerCase();
    const limit = Math.max(1, Math.min(200, Number(payload?.limit ?? 80)));

    if (query === '') {
      postMessage({ type: 'search-result', payload: [] });
      return;
    }

    const result: Array<{ nodeId: string; kind: string; label: string; path: string; score: number }> = [];
    for (const item of items) {
      const label = String(pool[item.key_i] ?? '');
      const path = String(pool[item.path_i ?? -1] ?? '');
      const hay = `${label} ${path}`.toLowerCase();
      const idx = hay.indexOf(query);
      if (idx < 0) continue;
      const score = idx + Math.abs(label.length - query.length) * 0.02;
      result.push({ nodeId: item.node_id, kind: item.kind, label, path, score });
    }

    result.sort((a, b) => a.score - b.score);
    postMessage({ type: 'search-result', payload: result.slice(0, limit) });
  }
};
