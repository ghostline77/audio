const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };
const media = path => '/api/media?path=' + encodeURIComponent(path);
function player(parent, label, path) { parent.append(el('p', 'muted', label)); const audio = el('audio'); audio.controls = true; audio.preload = 'none'; audio.src = media(path); parent.append(audio); }
let data, actor = 'All';
function render() {
  const root = document.querySelector('#comparison-cards'); root.replaceChildren();
  for (const item of data.items.filter(i => actor === 'All' || i.actor === actor)) {
    const card = el('article', 'panel'); card.append(el('h2', '', item.label + (data.selected_candidates?.[item.actor] === item.number ? ' · Selected' : '')), el('p', '', item.mission + ' — ' + item.context));
    const columns = el('div', 'two'), fresh = el('div'), old = el('div');
    fresh.append(el('h3', '', 'New reference'), el('p', '', item.reference_text)); player(fresh, 'Model reference · 24 kHz', item.reference_audio);
    player(fresh, 'New generated comparison', item.new_sample);
    old.append(el('h3', '', 'Earlier reference'), el('p', '', item.previous_reference_text)); player(old, 'Previous model reference', item.previous_reference_audio); player(old, 'Same text and seed · regenerated in this batch', item.previous_sample);
    columns.append(fresh, old); card.append(columns);
    const details = el('details'), summary = el('summary', '', 'Original exports & provenance'); details.append(summary);
    for (const source of item.sources) {
      const block = el('div', 'panel'); block.append(el('p', '', source.text)); player(block, 'Original decoded game recording · ' + source.signal.rate + ' Hz', source.original);
      block.append(el('p', 'muted', 'String ID ' + source.id + ' · ' + source.depot), el('p', 'muted', `Active scene event ${source.scene_evidence.event_node} · reachable from start · ${source.signal.clipped_samples} clipped samples`)); details.append(block);
    }
    const link = el('a', '', 'Mission context'); link.href = item.source_url; link.target = '_blank'; link.rel = 'noreferrer'; details.append(link); card.append(details);
    root.append(card);
  }
  for (const b of document.querySelectorAll('[data-actor]')) b.classList.toggle('primary', b.dataset.actor === actor);
}
for (const b of document.querySelectorAll('[data-actor]')) b.onclick = () => { actor = b.dataset.actor; render(); };
try { const path = new URLSearchParams(location.search).get('path'); if (!path) throw Error('A comparison manifest path is required'); const response = await fetch('/api/manifest?path=' + encodeURIComponent(path)); const result = await response.json(); if (!response.ok) throw Error(result.error); data = result.value; document.querySelector('#title').textContent = data.title; document.querySelector('#target').textContent = 'Generated dialogue: “' + data.target_text + '”'; document.querySelector('#note').textContent = data.note; document.querySelector('#selection-state').textContent = data.selected_candidates ? 'Selected for the active library: ' + Object.entries(data.selected_candidates).map(([name, number]) => name + ' ' + number).join(' · ') : 'These candidates have not replaced your active voices.'; render(); }
catch (e) { document.querySelector('#title').textContent = e.message; }
