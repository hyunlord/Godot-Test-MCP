(async () => {
  const load = async (name) => (await fetch(name)).json();
  const i18n = await load('i18n.json');
  const meta = await load('meta.json');
  const map = await load('map.json');
  const timeline = await load('timeline.json');
  const causality = await load('causality.json');
  const diff = await load('diff.json');

  let locale = meta.locale || 'ko';
  const t = (k) => ((i18n[locale] || i18n.ko || {})[k] || k);

  const applyLabels = () => {
    document.getElementById('title').textContent = t('title');
    document.getElementById('label-structure').textContent = t('structure_graph');
    document.getElementById('label-timeline').textContent = t('tick_timeline');
    document.getElementById('label-causality').textContent = t('causality_chain');
    document.getElementById('label-diff').textContent = t('diff_panel');
    document.getElementById('label-inspector').textContent = t('detail_inspector');
    document.getElementById('label-edit').textContent = t('edit_preview');
    document.getElementById('runtime-source').textContent = `${t('runtime_source')}: ${meta.runtime_source || 'unknown'}`;
  };

  const pretty = (obj) => JSON.stringify(obj, null, 2);
  document.getElementById('structure-content').textContent = pretty({ summary: map.summary, nodes: map.nodes.slice(0, 200), edges: map.edges.slice(0, 200) });
  document.getElementById('timeline-content').textContent = pretty(timeline);
  document.getElementById('causality-content').textContent = pretty(causality);
  document.getElementById('diff-content').textContent = pretty(diff);
  document.getElementById('inspector-content').textContent = pretty(meta);
  document.getElementById('edit-content').textContent = 'Edit proposals are shown via MCP responses.';

  const select = document.getElementById('lang-select');
  select.value = locale;
  select.addEventListener('change', () => {
    locale = select.value;
    applyLabels();
  });
  applyLabels();
})();
