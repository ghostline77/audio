// Dialogue authoring owns its document, generation, and review state together.
export function dialogueFlow({api, button, el, toast, view, getBoot, getVoices}) {
  const $ = selector => document.querySelector(selector);
  const state = {doc:null, dirty:false, version:0, saving:null, timer:null, run:null, selected:new Set(), reviewJobs:[], busy:false, exportJob:null, selectionSaving:Promise.resolve(), selectionVersion:0};
  const safe = fn => async event => { try { await fn(event); } catch (e) { toast(e.message, true); } };
  const media = path => '/api/media?path=' + encodeURIComponent(path);
  function reviewStage(running) { for (const [index, step] of [...document.querySelectorAll('#review .workflow-steps li')].entries()) step.classList.toggle('active',index === (running ? 1 : 2)); }
  function updateStatus(message) { $('#draft-status').textContent = message || (state.dirty ? 'Saving changes…' : 'Saved automatically'); }
  function source() { if (state.doc) $('#source').value = JSON.stringify(state.doc.value, null, 2); }
  function changed() { state.dirty = true; state.version++; source(); updateStatus(); updateGenerate(); clearTimeout(state.timer); state.timer = setTimeout(() => save().catch(e => { updateStatus('Could not save — ' + e.message); toast(e.message, true); }), 800); }
  async function save() {
    clearTimeout(state.timer);
    if (state.saving) { await state.saving; if (state.dirty) return save(); return; }
    if (!state.doc || !state.dirty) return;
    const doc = state.doc, version = state.version;
    state.saving = (async () => {
      const result = await api('manifest', {path:doc.path, hash:doc.hash, value:doc.value});
      doc.hash = result.hash;
      if (state.version === version) state.dirty = false;
      for (const line of doc.value.lines) if (!line.id) { const saved = result.value.lines.find(old => old.key === line.key); if (saved) line.id = saved.id; }
      source(); updateStatus();
    })();
    try { await state.saving; } finally { state.saving = null; }
    if (state.dirty) return save();
  }
  function field(parent, title, value, setter, options) {
    const label = el('label', '', title), input = el(options ? 'select' : 'input');
    if (options) for (const [key, name] of options) { const option = el('option', '', name); option.value = key; input.append(option); }
    input.value = value || ''; input.oninput = () => { setter(input.value); changed(); }; label.append(input); parent.append(label); return input;
  }
  function renderLines() {
    const manifest = state.doc.value, root = $('#lines'); root.replaceChildren();
    if (!manifest.lines.length) { const empty = el('div', 'panel empty-state'); empty.append(el('h2', '', 'Write the first line.'), el('p', 'muted', 'Choose a voice and enter the words they should say.')); root.append(empty); }
    manifest.lines.forEach((line, index) => {
      const card = el('article', 'line'), heading = el('div', 'section-title');
      heading.append(el('h3', '', `Line ${index + 1}`), button(`Remove line ${index + 1}`, () => { manifest.lines.splice(index, 1); renderLines(); changed(); }, 'danger')); card.append(heading);
      const names = [...new Set([...(manifest.voice_library ? getVoices().map(v => v.name) : []), ...Object.keys(manifest.voices || {}), line.speaker].filter(Boolean))];
      field(card, `Voice for line ${index + 1}`, line.speaker, value => { line.speaker = value; if (value === 'V Female') line.gender = 'female'; else if (value === 'V Male') line.gender = 'male'; else line.gender = 'shared'; const binding = card.querySelector('details select'); if (binding) binding.value = line.gender; }, [['','Choose a voice…'], ...names.map(name => [name,name])]);
      const label = el('label', '', `Dialogue line ${index + 1}`), text = el('textarea'); text.value = line.text || ''; text.placeholder = 'Write what they say…'; text.oninput = () => { line.text = text.value; changed(); }; label.append(text); card.append(label);
      const details = el('details'); details.append(el('summary', '', 'Delivery & game binding'));
      field(details, `Delivery for line ${index + 1} (optional)`, line.instruction, value => { if (value) line.instruction = value; else delete line.instruction; });
      field(details, `Audio variant for line ${index + 1}`, line.gender || 'shared', value => line.gender = value, [['shared','Shared'],['female','Female player variant'],['male','Male player variant']]);
      details.append(el('p', 'muted', 'Localization ID and line key are assigned automatically and retained when the text changes.')); card.append(details); root.append(card);
    });
    source(); updateGenerate();
  }
  function updateGenerate() {
    if (!state.doc) return;
    const lines = state.doc.value.lines, takes = Number($('#takes-per-line').value), count = lines.length * takes;
    const incomplete = lines.findIndex(line => !line.speaker || !line.text?.trim());
    const knownModel = getBoot().models.find(model => model.path === $('#base-checkpoint').value); const ready = !knownModel || knownModel.downloaded; $('#generation-setup').hidden = ready;
    $('#generation-summary').textContent = lines.length ? `${lines.length} ${lines.length === 1 ? 'line' : 'lines'} × ${takes} ${takes === 1 ? 'take' : 'takes'} = ${count} audio files` : 'Add your first line to begin.';
    $('#generate-dialogue').textContent = state.busy ? 'Generating…' : `Generate ${count || ''} ${count === 1 ? 'take' : 'takes'}`;
    $('#generate-dialogue').disabled = state.busy || !lines.length || incomplete >= 0 || !ready;
    $('#generation-message').textContent = !ready ? 'Download a Base voice model in Models & setup before generating.' : incomplete >= 0 ? `Line ${incomplete + 1}: choose a voice and write its dialogue to continue.` : 'Ready to generate using the selected voice model.';
  }
  async function refreshDocuments() {
    const rows = await api('dialogues'), select = $('#saved-dialogues'); select.replaceChildren();
    if (!rows.length) { const option = el('option', '', 'No saved dialogues yet'); option.value = ''; select.append(option); }
    for (const row of rows) { const option = el('option', '', `${row.title} · ${row.lines} ${row.lines === 1 ? 'line' : 'lines'}`); option.value = row.path; select.append(option); }
    $('#open-dialogue').disabled = !rows.length;
  }
  async function showDocument(doc) {
    await save(); state.doc = doc; state.dirty = false; state.version = 0;
    $('#dialogue-start').hidden = true; $('#dialogue-editor').hidden = false;
    $('#dialogue-title').textContent = doc.value.title || 'Imported dialogue'; $('#rename-dialogue').value = doc.value.title || 'Imported dialogue';
    $('#namespace').value = doc.value.namespace || ''; $('#document-location').textContent = 'Saved in ' + doc.path;
    $('#takes-per-line').value = String(doc.value.candidates || 1); $('#generation-seed').value = doc.value.seed || 0;
    $('#cast-note').textContent = 'Using your reviewed cast. Voices and localization IDs are handled automatically.';
    localStorage.setItem('ghostline-audio-last-dialogue', doc.path); updateStatus(); renderLines(); view('dialogue');
  }
  async function openDocument(path) { await save(); await showDocument(await api('dialogue?path=' + encodeURIComponent(path))); }
  $('#new-dialogue-form').onsubmit = safe(async event => { event.preventDefault(); await save(); const doc = await api('new-dialogue', {title:$('#new-dialogue-title').value}); await showDocument(doc); addLine(); await save(); await refreshDocuments(); });
  $('#open-dialogue').onclick = safe(() => openDocument($('#saved-dialogues').value));
  $('#all-dialogues').onclick = safe(async () => { await save(); $('#dialogue-editor').hidden = true; $('#dialogue-start').hidden = false; localStorage.removeItem('ghostline-audio-last-dialogue'); await refreshDocuments(); });
  $('#import-dialogue').onclick = () => $('#import-dialogue-file').click();
  $('#import-dialogue-file').onchange = safe(async event => { const file = event.target.files[0]; if (!file) return; await save(); const doc = await api('import-dialogue', {text:await file.text(), filename:file.name}); await showDocument(doc); await refreshDocuments(); event.target.value = ''; toast('Imported. Existing localization IDs are preserved.'); });
  $('#import-dialogue-path-button').onclick = safe(async () => { await save(); const doc = await api('import-dialogue', {path:$('#import-dialogue-path').value}); await showDocument(doc); await refreshDocuments(); });
  function addLine() { state.doc.value.lines.push({key:'line-' + crypto.randomUUID(), speaker:'', text:'', gender:'shared'}); renderLines(); changed(); const fields = document.querySelectorAll('#lines select'); fields[fields.length - 2]?.focus(); }
  $('#add-line').onclick = addLine;
  $('#takes-per-line').onchange = () => { state.doc.value.candidates = Number($('#takes-per-line').value); changed(); };
  $('#generation-seed').onchange = () => { state.doc.value.seed = Number($('#generation-seed').value); changed(); };
  $('#rename-dialogue').oninput = () => { state.doc.value.title = $('#rename-dialogue').value; $('#dialogue-title').textContent = $('#rename-dialogue').value; changed(); };
  $('#preview-cast').onclick = () => view('library'); $('#generation-setup').onclick = () => view('setup');
  $('#download-dialogue').onclick = safe(async () => { await save(); const url = URL.createObjectURL(new Blob([JSON.stringify(state.doc.value,null,2) + '\n'],{type:'application/json'})); const a = el('a'); a.href = url; a.download = state.doc.path.split(/[\\/]/).pop(); a.click(); setTimeout(() => URL.revokeObjectURL(url),1000); });
  $('#generate-dialogue').onclick = safe(async () => {
    await save(); const job = await api('generate-dialogue', {path:state.doc.path, hash:state.doc.hash, checkpoint:$('#base-checkpoint').value});
    state.run = job; state.busy = true; reviewStage(true); $('#review-title').textContent = state.doc.value.title; $('#generation-progress').hidden = false; $('#review-empty').hidden = true; $('#takes').replaceChildren(); $('#export-panel').hidden = true; $('#review-error').hidden = true; $('#edit-dialogue').hidden = false;
    $('#generation-progress-detail').textContent = `Generating ${job.lines * job.takes} takes. Preparing the voice model can take a few minutes; you can keep writing while it runs.`;
    updateGenerate(); view('review'); await refreshRuns();
  });
  $('#start-dialogue').onclick = () => view('dialogue');
  $('#edit-dialogue').onclick = safe(async () => { if (state.run && state.doc?.path !== state.run.dialogue) await openDocument(state.run.dialogue); else view('dialogue'); });
  async function refreshRuns() {
    const runs = await api('runs'), select = $('#run-picker'); select.replaceChildren();
    for (const run of runs) { const option = el('option', '', `${run.title} · ${new Date(run.created).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})} · ${run.status}`); option.value = run.output; select.append(option); }
    $('#run-picker-label').hidden = !runs.length; if (state.run) select.value = state.run.output;
    return runs;
  }
  $('#run-picker').onchange = safe(async () => { const rows = await api('runs'); state.run = rows.find(run => run.output === $('#run-picker').value); if (state.run) await loadReview(); });
  function updateSelections(message) {
    const groups = new Set(state.reviewJobs.map(j => j.id + '/' + j.gender));
    $('#selection-status').textContent = message || `${state.selected.size} of ${groups.size} lines chosen · choices saved`;
    $('#export-takes').disabled = !state.selected.size || state.busy;
    $('#export-takes').textContent = state.selected.size ? `Export ${state.selected.size} selected ${state.selected.size === 1 ? 'line' : 'lines'}` : 'Choose a take to export';
  }
  function showExport(exported) { $('#export-result').hidden = false; $('#export-message').textContent = 'Your WAVs are ready. Saved in ' + exported.destination; $('#download-wavs').href = '/api/download?path=' + encodeURIComponent(exported.download); }
  async function selectTake(job) {
    $('#export-result').hidden = true;
    const previous = new Set(state.selected), version = ++state.selectionVersion;
    for (const item of state.reviewJobs) if (item.id === job.id && item.gender === job.gender) state.selected.delete(item.fingerprint);
    state.selected.add(job.fingerprint); updateSelections('Saving your choice…');
    const request = {output:state.run.output, fingerprints:[...state.selected]};
    state.selectionSaving = state.selectionSaving.catch(() => {}).then(() => api('selections',request));
    try { await state.selectionSaving; if (version === state.selectionVersion) updateSelections(); }
    catch (error) { if (version !== state.selectionVersion) throw error; state.selected = previous; for (const input of document.querySelectorAll('#takes input')) input.checked = previous.has(input.value); updateSelections('Choice was not saved'); throw error; }
  }
  async function loadReview() {
    const run = state.run; if (!run) return; reviewStage(run.status === 'running');
    $('#review-title').textContent = run.title; $('#review-empty').hidden = true; $('#edit-dialogue').hidden = false; $('#generation-progress').hidden = run.status !== 'running'; $('#export-result').hidden = true;
    if (run.status === 'running') return;
    let report; try { report = await api('review?output=' + encodeURIComponent(run.output)); }
    catch (error) { $('#review-error').hidden = false; $('#review-error').textContent = 'No takes were produced. Check the activity details, then return to Dialogue to try again.'; $('#export-panel').hidden = true; return; }
    state.reviewJobs = report.jobs; state.selected = new Set(report.selected); const root = $('#takes'); root.replaceChildren();
    $('#review-error').hidden = !report.failures?.length && run.status !== 'failed'; $('#review-error').textContent = report.failures?.length ? `${report.failures.length} lines could not be generated. Completed takes are available below; check Activity for details.` : 'Generation did not finish. Completed takes are available below.';
    const groups = new Map();
    for (const job of state.reviewJobs) {
      const key = job.id + '/' + job.gender;
      if (!groups.has(key)) { const card = el('article','take-group'); card.append(el('h2','',job.speaker),el('p','spoken-copy',job.text)); const fieldset = el('fieldset'); const legend = el('legend','muted','Choose a performance for this line'); fieldset.append(legend); card.append(fieldset); root.append(card); groups.set(key,fieldset); }
      const row = el('div','take'), radio = el('input'); radio.type = 'radio'; radio.name = key; radio.id = 'take-' + job.fingerprint; radio.value = job.fingerprint; radio.checked = state.selected.has(job.fingerprint); radio.onchange = safe(() => selectTake(job)); const label = el('label','',`Take ${job.candidate}`); label.htmlFor = radio.id; const audio = el('audio'); audio.controls = true; audio.preload = 'metadata'; audio.src = media(job.audio); row.append(radio,label,audio); groups.get(key).append(row);
    }
    $('#export-panel').hidden = !report.jobs.length; updateSelections(); if (report.export) showExport(report.export);
  }
  $('#export-takes').onclick = safe(async () => {
    await state.selectionSaving;
    const job = await api('export-dialogue', {output:state.run.output, fingerprints:[...state.selected], destination:$('#export-destination').value}); state.exportJob = job.id; $('#export-takes').disabled = true; $('#selection-status').textContent = 'Exporting selected WAVs…';
  });
  function models() {
    const models = getBoot().models.filter(m => m.key !== 'design'), select = $('#voice-model'), old = select.value; select.replaceChildren();
    for (const model of models) { const option = el('option','',model.key === 'base' ? '1.7B Base — recommended' : '0.6B Base — smaller model'); option.value = model.path; select.append(option); }
    select.value = old || models.find(m => m.downloaded)?.path || models[0]?.path || ''; $('#base-checkpoint').value = select.value;
    select.onchange = () => { $('#base-checkpoint').value = select.value; updateGenerate(); }; $('#base-checkpoint').oninput = updateGenerate;
    $('#generation-setup').hidden = models.some(m => m.downloaded);
  }
  async function jobs(jobs) {
    const running = jobs.some(job => job.status === 'running'); state.busy = running; updateGenerate();
    if (state.run) {
      const job = jobs.find(j => j.kind === 'dialogue' && j.output === state.run.output);
      if (job && job.status !== state.run.status) { state.run = {...state.run,...job}; if (job.status !== 'running') { await refreshRuns(); await loadReview(); view('review'); } }
    }
    const exported = jobs.find(j => j.id === state.exportJob);
    if (exported && exported.status !== 'running') {
      state.exportJob = null; updateSelections();
      if (exported.status === 'complete') showExport(exported);
      else toast('Export failed. Your choices are saved; check Activity and try again.',true);
    }
  }
  async function init() {
    models(); await refreshDocuments(); const runs = await refreshRuns();
    if (runs.length) { state.run = runs[0]; await loadReview(); }
    const last = localStorage.getItem('ghostline-audio-last-dialogue');
    if (last) try { await openDocument(last); } catch { localStorage.removeItem('ghostline-audio-last-dialogue'); }
  }
  window.addEventListener('beforeunload', event => { if (state.dirty) { event.preventDefault(); event.returnValue = ''; } });
  document.addEventListener('keydown', event => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's' && state.doc) { event.preventDefault(); save().catch(e => toast(e.message,true)); } });
  return {init,jobs,save};
}
