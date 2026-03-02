import React from 'react';
import { createRoot } from 'react-dom/client';

import { App } from './app/App';
import { useVisualizerStore } from './state/useVisualizerStore';
import type { VisualizerPayload } from './types/visualizer';
import './styles.css';

async function loadPayload(): Promise<VisualizerPayload> {
  const inline = document.getElementById('visualizer-inline-data');
  const text = inline?.textContent?.trim() ?? '';
  if (text !== '' && text !== '__VISUALIZER_INLINE_DATA__') {
    try {
      return JSON.parse(text) as VisualizerPayload;
    } catch (_error) {
      // Continue with fallback fetch.
    }
  }

  const payload: VisualizerPayload = {};
  try {
    const [meta, map, timeline, causality, diff, viewModel, bundle] = await Promise.all([
      fetch('./meta.json').then((r) => r.json()),
      fetch('./map.json').then((r) => r.json()),
      fetch('./timeline.json').then((r) => r.json()),
      fetch('./causality.json').then((r) => r.json()),
      fetch('./diff.json').then((r) => r.json()),
      fetch('./view_model.json').then((r) => r.json()),
      fetch('./graph.bundle.json').then((r) => r.json()),
    ]);
    payload.meta = meta;
    payload.map = map;
    payload.timeline = timeline;
    payload.causality = causality;
    payload.diff = diff;
    payload.view_model = viewModel;
    payload.graph_bundle = bundle;
  } catch (error) {
    payload.meta = {
      runtime_diagnostics: [
        {
          level: 'error',
          code: 'bootstrap_failed',
          message: `Visualizer bootstrap failed: ${String(error)}`,
          hint: 'index.html에 inline data가 주입되었는지 확인하세요.',
        },
      ],
    };
  }
  return payload;
}

async function bootstrap(): Promise<void> {
  const payload = await loadPayload();
  useVisualizerStore.getState().hydrate(payload);

  const rootElement = document.getElementById('root');
  if (rootElement == null) {
    throw new Error('missing #root');
  }
  const root = createRoot(rootElement);
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}

bootstrap();
