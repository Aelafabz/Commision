// ── Commission Dashboard — app.js ──────────────────────────────────────────
'use strict';

const API_BASE = '/api';

// ── State ──────────────────────────────────────────────────────────────────
const state = {
  records: [],
  logContent: '',
  logTimer: null,
  currentPipelineRunId: null,
  pipelinePollTimer: null,
};

// ── Navigation ─────────────────────────────────────────────────────────────
function showSection(name) {
  document.querySelectorAll('.page').forEach((el) => el.classList.add('hidden'));
  document.querySelectorAll('.nav-link').forEach((el) => el.classList.remove('active'));

  const page = document.getElementById(`page-${name}`);
  const nav = document.getElementById(`nav-${name}`);
  if (page) page.classList.remove('hidden');
  if (nav) nav.classList.add('active');

  if (name === 'records') loadRecords();
  if (name === 'export') loadLog();
  if (name === 'db') loadDbTables();
}

// ── API health check ───────────────────────────────────────────────────────
async function checkApiHealth() {
  const badge = document.getElementById('api-badge');
  const label = document.getElementById('api-status-text');
  try {
    const res = await fetch('/health');
    if (res.ok) {
      badge.className = 'api-badge ok';
      label.textContent = 'API online';
    } else {
      throw new Error('not ok');
    }
  } catch {
    badge.className = 'api-badge error';
    label.textContent = 'API offline';
  }
}

// ── Alert helper ───────────────────────────────────────────────────────────
function showAlert(id, message, type = 'info') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = message;
  el.className = `alert ${type}`;
}
function hideAlert(id) {
  const el = document.getElementById(id);
  if (el) el.className = 'alert hidden';
}

// ── Records ────────────────────────────────────────────────────────────────
async function loadRecords() {
  const tbody = document.getElementById('records-body');
  tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">Loading…</td></tr>';
  try {
    const res = await fetch(`${API_BASE}/records`);
    const data = await res.json();
    state.records = Array.isArray(data) ? data : [];
    renderRecords();
  } catch (err) {
    console.error(err);
    tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">Failed to load records.</td></tr>';
  }
}

function renderRecords() {
  const tbody = document.getElementById('records-body');
  const count = document.getElementById('records-count');

  if (!state.records.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty-cell">No records in the database yet.</td></tr>';
    if (count) count.textContent = '';
    return;
  }

  tbody.innerHTML = state.records
    .map(
      (r) => `
      <tr>
        <td>${r.id}</td>
        <td>${r.doctor_name || '—'}</td>
        <td>${r.service || '—'}</td>
        <td>${r.amount != null ? Number(r.amount).toLocaleString() : '—'}</td>
        <td>${r.category || '—'}</td>
        <td>${r.date ? new Date(r.date).toLocaleDateString() : '—'}</td>
      </tr>`
    )
    .join('');

  if (count) count.textContent = `${state.records.length} record${state.records.length !== 1 ? 's' : ''}`;
}

// ── Export ─────────────────────────────────────────────────────────────────
async function loadLog() {
  try {
    const res = await fetch(`${API_BASE}/export/log`);
    const payload = await res.json();
    const box = document.getElementById('log-box');
    if (box) {
      box.textContent = payload.content || 'No log output yet.';
      box.scrollTop = box.scrollHeight;
    }
  } catch (err) {
    console.error(err);
  }
}

function startLogPolling() {
  if (state.logTimer) clearInterval(state.logTimer);
  state.logTimer = setInterval(loadLog, 5000);
}

// ── DB Inspector ──────────────────────────────────────────────────────────
async function loadDbTables() {
  const list = document.getElementById('db-tables-list');
  const preview = document.getElementById('db-table-preview');
  if (list) list.innerHTML = 'Loading…';
  if (preview) preview.innerHTML = '<p class="empty-cell">Select a table to preview its columns and sample rows.</p>';
  try {
    const res = await fetch(`${API_BASE}/db/tables`);
    const payload = await res.json();
    const tables = payload.tables || [];
    const counts = payload.counts || {};
    if (!tables.length) {
      if (list) list.innerHTML = '<p class="empty-cell">No tables in database.</p>';
      return;
    }
    const items = tables.map(t => {
      const c = counts[t] == null ? '—' : counts[t];
      return `<div style="display:flex;align-items:center;justify-content:space-between;padding:0.45rem 0;border-bottom:1px solid var(--border)"><div><strong>${t}</strong><div class="field-hint" style="font-size:0.78rem">${c} rows</div></div><div><button class="btn btn-ghost btn-sm" onclick="window.viewDbTable('${t.replace(/'/g,"\\'")}')">View</button></div></div>`;
    }).join('');
    if (list) list.innerHTML = items;
  } catch (err) {
    console.error(err);
    if (list) list.innerHTML = '<p class="empty-cell">Failed to load tables.</p>';
  }
}

window.viewDbTable = async function(tableName) {
  const preview = document.getElementById('db-table-preview');
  if (!preview) return;
  preview.innerHTML = 'Loading…';
  try {
    const res = await fetch(`${API_BASE}/db/tables/${encodeURIComponent(tableName)}?limit=200`);
    if (!res.ok) throw new Error('Failed to fetch table');
    const payload = await res.json();
    const cols = payload.columns || [];
    const rows = payload.rows || [];
    const head = cols.map(c => `<th>${c.name}</th>`).join('');
    const body = rows.map(r => `<tr>${cols.map(c => `<td>${(r[c.name] ?? '')}</td>`).join('')}</tr>`).join('');
    if (!cols.length) {
      preview.innerHTML = '<p class="empty-cell">Table has no columns.</p>';
      return;
    }
    preview.innerHTML = `<div class="table-wrap"><table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body || '<tr><td class="empty-cell">No rows.</td></tr>'}</tbody></table></div>`;
  } catch (err) {
    console.error(err);
    preview.innerHTML = `<p class="empty-cell">Error: ${err.message}</p>`;
  }
}

async function loadDoctorSummary() {
  const preview = document.getElementById('db-table-preview');
  const list = document.getElementById('db-tables-list');
  if (list) list.innerHTML = 'Loading doctor summary…';
  if (preview) preview.innerHTML = '<p class="empty-cell">Loading doctor summary…</p>';
  try {
    const from = document.getElementById('db-from-date')?.value || '';
    const to = document.getElementById('db-to-date')?.value || '';
    const doctor = document.getElementById('db-doctor-name')?.value || '';
    const qs = new URLSearchParams();
    if (from) qs.set('from_date', from);
    if (to) qs.set('to_date', to);
    if (doctor) qs.set('doctor', doctor);
    const res = await fetch(`${API_BASE}/db/doctor_summary?` + qs.toString());
    if (!res.ok) throw new Error('Failed to fetch');
    const payload = await res.json();
    const date = payload.date || 'N/A';
    const summary = payload.summary || [];
    if (list) list.innerHTML = `<div class="field-hint">Date: ${date}</div><div style="margin-top:0.5rem">${summary.map(s=>`<div style="padding:0.45rem 0;border-bottom:1px solid var(--border)"><strong>${s.doctor_name}</strong> — ${Number(s.total).toLocaleString()} (${s.count} rows)</div>`).join('')}</div>`;
    if (!summary.length) {
      if (preview) preview.innerHTML = '<p class="empty-cell">No doctor data.</p>';
      return;
    }
    // display the first doctor's breakdown by default
    const first = summary[0];
    const cols = ['category','total'];
    const head = cols.map(c=>`<th>${c}</th>`).join('');
    const body = (first.categories||[]).map(r=>`<tr><td>${r.category}</td><td>${Number(r.total).toLocaleString()}</td></tr>`).join('');
    if (preview) preview.innerHTML = `<h3 style="margin-top:0">${first.doctor_name} — Total: ${Number(first.total).toLocaleString()} — Commission: ${Number(first.commission_amount).toLocaleString()} (@${(first.commission_rate*100).toFixed(1)}%)</h3><div class="table-wrap"><table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body || '<tr><td class="empty-cell">No category data.</td></tr>'}</tbody></table></div>`;
  } catch (err) {
    console.error(err);
    if (list) list.innerHTML = '<p class="empty-cell">Failed to load doctor summary.</p>';
    if (preview) preview.innerHTML = `<p class="empty-cell">Error: ${err.message}</p>`;
  }
}

// Export helpers
window.exportTable = async function(tableName) {
  try {
    const res = await fetch(`${API_BASE}/db/export/table/${encodeURIComponent(tableName)}`);
    if (!res.ok) throw new Error('Export failed');
    const text = await res.text();
    const blob = new Blob([text], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${tableName}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('Export failed: ' + err.message);
  }
}

window.exportDoctor = async function() {
  const doctor = document.getElementById('db-doctor-name')?.value || '';
  const from = document.getElementById('db-from-date')?.value || '';
  const to = document.getElementById('db-to-date')?.value || '';
  if (!doctor) return alert('Please enter a doctor name to export');
  const qs = new URLSearchParams({ doctor });
  if (from) qs.set('from_date', from);
  if (to) qs.set('to_date', to);
  try {
    const res = await fetch(`${API_BASE}/db/export/doctor?` + qs.toString());
    if (!res.ok) throw new Error('Export failed');
    const text = await res.text();
    const blob = new Blob([text], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${doctor.replace(/\s+/g,'_') || 'doctor'}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    alert('Export failed: ' + err.message);
  }
}
async function handleExportSubmit(event) {
  event.preventDefault();
  const btn = document.getElementById('submit-btn');
  const fromDate = document.getElementById('fromDate').value;
  const toDate = document.getElementById('toDate').value;
  const physicians = document.getElementById('physicians').value;

  btn.disabled = true;
  btn.innerHTML = loadingHtml('Starting…');
  hideAlert('export-alert');

  try {
    const res = await fetch(`${API_BASE}/export/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from_date: fromDate,
        to_date: toDate,
        physicians: physicians.split(',').map((n) => n.trim()).filter(Boolean),
      }),
    });
    const payload = await res.json();
    if (!res.ok) throw new Error(payload.detail || 'Export request failed');
    showAlert('export-alert', `Export queued (PID ${payload.pid}). Log file: ${payload.log_file}`, 'success');
    await loadLog();
    startLogPolling();
  } catch (err) {
    showAlert('export-alert', err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = exportBtnHtml();
  }
}

// ── Pipeline ───────────────────────────────────────────────────────────────
function setPipelineBadge(status) {
  const badge = document.getElementById('pipeline-badge');
  if (!badge) return;
  badge.textContent = status.charAt(0).toUpperCase() + status.slice(1);
  badge.className = `badge ${status}`;
}

function appendPipelineLog(lines) {
  const box = document.getElementById('pipeline-log');
  if (!box) return;
  if (Array.isArray(lines)) {
    box.textContent = lines.join('\n') || 'No output yet.';
  } else {
    box.textContent = String(lines);
  }
  box.scrollTop = box.scrollHeight;
}

function renderPipelineResults(results) {
  const wrap = document.getElementById('pipeline-results');
  if (!wrap) return;
  wrap.classList.remove('hidden');

  const stats = document.getElementById('pipeline-stats');
  stats.innerHTML = `
    <div class="stat-pill">
      <div class="stat-value">${results.perfect_match_count}</div>
      <div class="stat-label">Perfect Matches</div>
    </div>
    <div class="stat-pill">
      <div class="stat-value">${results.mismatch_count}</div>
      <div class="stat-label">Mismatched</div>
    </div>`;

  const rows = results.commission_summary || [];
  const head = document.getElementById('pipeline-head');
  const body = document.getElementById('pipeline-body');

  if (!rows.length) {
    head.innerHTML = '';
    body.innerHTML = '<tr><td class="empty-cell">No summary data returned.</td></tr>';
    return;
  }
  // hide any Commission % column — commission rates are per-doctor and sourced separately
  const allCols = Object.keys(rows[0]);
  const cols = allCols.filter((c) => c !== 'Commission %');
  head.innerHTML = cols.map((c) => `<th>${c}</th>`).join('');
  body.innerHTML = rows
    .map((row) => `<tr>${cols.map((c) => `<td>${row[c] ?? '—'}</td>`).join('')}</tr>`) 
    .join('');
}

async function pollPipelineStatus(runId) {
  try {
    const res = await fetch(`${API_BASE}/pipeline/status/${runId}`);
    const payload = await res.json();
    appendPipelineLog(payload.log);
    setPipelineBadge(payload.status);

    if (payload.status === 'error') {
      showAlert('pipeline-alert', `Pipeline failed: ${payload.error}`, 'error');
      if (state.pipelinePollTimer) clearInterval(state.pipelinePollTimer);
      return;
    }

    if (payload.status === 'done') {
      if (state.pipelinePollTimer) clearInterval(state.pipelinePollTimer);
      const resRes = await fetch(`${API_BASE}/pipeline/results/${runId}`);
      const results = await resRes.json();
      const abrText = results.abr_dir ? `Abronal: ${results.abr_dir}` : '';
      const sotText = results.sot_dir ? `SoT: ${results.sot_dir}` : '';
      const analyzedText = results.analyzed_dir ? `Analyzed: ${results.analyzed_dir}` : '';
      const pathText = [abrText, sotText, analyzedText].filter(Boolean).join(' | ');
      showAlert('pipeline-alert', `Done — ${results.perfect_match_count} matched, ${results.mismatch_count} mismatched. DB: ${results.db_path}`, 'success');
      const pathsEl = document.getElementById('pipeline-paths-code');
      if (pathsEl) pathsEl.textContent = pathText || '—';
      renderPipelineResults(results);
    }
  } catch (err) {
    console.error(err);
  }
}

async function handlePipelineSubmit(event) {
  event.preventDefault();
  const btn = document.getElementById('pipeline-btn');

  const abr_dir    = document.getElementById('abrDir').value.trim();
  const sot_dir    = document.getElementById('sotDir').value.trim();
  const date_label = document.getElementById('dateLabel').value.trim();
  const commission_rate      = parseFloat(document.getElementById('commissionRate').value) || 0.10;
  const name_match_confidence = parseFloat(document.getElementById('nameConfidence').value) || 0.70;
  const date_window_days     = parseInt(document.getElementById('dateWindow').value, 10) ?? 1;

  btn.disabled = true;
  btn.innerHTML = loadingHtml('Running…');
  hideAlert('pipeline-alert');
  setPipelineBadge('queued');
  document.getElementById('pipeline-log').textContent = 'Waiting for pipeline to start…';
  const pathsEl = document.getElementById('pipeline-paths-code');
  if (pathsEl) pathsEl.textContent = '—';
  const wrap = document.getElementById('pipeline-results');
  if (wrap) wrap.classList.add('hidden');

  try {
    // First perform a dry-run check for overlapping records
    const checkRes = await fetch(`${API_BASE}/pipeline/check`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ abr_dir, sot_dir, date_label, commission_rate, name_match_confidence, date_window_days }),
    });
    if (checkRes.status === 409) {
      const info = await checkRes.json();
      const overlaps = info.overlaps || [];
      const summary = overlaps.map(o => `${o.doctor}: ${o.existing_count} existing rows between ${o.existing_min_date} and ${o.existing_max_date}`).join('\n');
      const overwrite = confirm("Overlap detected with existing DB records:\n" + summary + "\n\nPress OK to overwrite existing records, Cancel to keep existing records (new rows will be ignored).");
      const on_conflict = overwrite ? 'overwrite' : 'ignore';
      const res = await fetch(`${API_BASE}/pipeline/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ abr_dir, sot_dir, date_label, commission_rate, name_match_confidence, date_window_days, on_conflict }),
      });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload.detail || 'Pipeline request failed');
      state.currentPipelineRunId = payload.run_id;
    } else {
      // no conflicts, start normally
      const res = await fetch(`${API_BASE}/pipeline/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ abr_dir, sot_dir, date_label, commission_rate, name_match_confidence, date_window_days }),
      });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload.detail || 'Pipeline request failed');
      state.currentPipelineRunId = payload.run_id;
    }
    setPipelineBadge('running');

    if (state.pipelinePollTimer) clearInterval(state.pipelinePollTimer);
    state.pipelinePollTimer = setInterval(() => pollPipelineStatus(payload.run_id), 2000);
  } catch (err) {
    showAlert('pipeline-alert', err.message, 'error');
    setPipelineBadge('error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = pipelineBtnHtml();
  }
}

// ── Button HTML helpers ────────────────────────────────────────────────────
function loadingHtml(label) {
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10" stroke-opacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" /></svg> ${label}`;
}
function pipelineBtnHtml() {
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Pipeline`;
}
function exportBtnHtml() {
  return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Start Export`;
}

// ── Folder Picker ──────────────────────────────────────────────────────────
const picker = {
  targetInputId: null,   // which field to fill when confirmed
  currentPath: '/',
  selectedPath: null,
};

function folderIcon(small = false) {
  const s = small ? 14 : 16;
  return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
}

async function pickerNavigate(path) {
  const body = document.getElementById('picker-body');
  const breadcrumb = document.getElementById('picker-breadcrumb');
  body.innerHTML = '<p class="picker-loading">Loading…</p>';

  try {
    const res = await fetch(`${API_BASE}/fs/browse?path=${encodeURIComponent(path)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      body.innerHTML = `<p class="picker-empty">Error: ${err.detail || res.statusText}</p>`;
      return;
    }
    const data = await res.json();
    picker.currentPath = data.current;
    picker.selectedPath = data.current; // auto-select current dir
    document.getElementById('picker-selected-path').textContent = data.current;
    breadcrumb.textContent = data.current;

    const items = [];

    // Up button
    if (data.parent) {
      items.push(
        `<button class="picker-item picker-up" data-path="${escHtml(data.parent)}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>
          .. (go up)
        </button>`
      );
    }

    if (!data.entries.length && !data.parent) {
      body.innerHTML = '<p class="picker-empty">No subdirectories found.</p>';
      return;
    }

    for (const entry of data.entries) {
      items.push(
        `<button class="picker-item" data-path="${escHtml(entry.path)}">
          ${folderIcon(true)}
          ${escHtml(entry.name)}
        </button>`
      );
    }

    body.innerHTML = items.join('') || '<p class="picker-empty">No subdirectories.</p>';

    // Delegate click
    body.querySelectorAll('.picker-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        const dest = btn.dataset.path;
        pickerNavigate(dest);
      });
    });
  } catch (err) {
    body.innerHTML = `<p class="picker-empty">Failed to browse: ${err.message}</p>`;
  }
}

function escHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function openPicker(targetInputId) {
  picker.targetInputId = targetInputId;
  // Start from the current value of the input if it looks like a path, else '/'
  const currentVal = document.getElementById(targetInputId)?.value?.trim() || '/';
  picker.selectedPath = null;
  document.getElementById('picker-selected-path').textContent = '—';
  document.getElementById('picker-backdrop').classList.remove('hidden');
  pickerNavigate(currentVal);
}

function closePicker() {
  document.getElementById('picker-backdrop').classList.add('hidden');
  picker.targetInputId = null;
}

function confirmPicker() {
  if (picker.selectedPath && picker.targetInputId) {
    const input = document.getElementById(picker.targetInputId);
    if (input) {
      input.value = picker.selectedPath;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  closePicker();
}

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  // Nav links
  document.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      showSection(link.dataset.section);
    });
  });

  // Forms
  document.getElementById('export-form').addEventListener('submit', handleExportSubmit);
  document.getElementById('pipeline-form').addEventListener('submit', handlePipelineSubmit);

  // Refresh buttons
  document.getElementById('refresh-log-btn')?.addEventListener('click', loadLog);
  document.getElementById('refresh-records-btn')?.addEventListener('click', loadRecords);
  document.getElementById('refresh-db-btn')?.addEventListener('click', loadDbTables);
  document.getElementById('db-refresh-btn')?.addEventListener('click', loadDbTables);
  document.getElementById('db-doctor-summary-btn')?.addEventListener('click', loadDoctorSummary);
  document.getElementById('db-doctor-export-btn')?.addEventListener('click', exportDoctor);

  // Upload buttons for client-side folder uploads
  document.getElementById('abr-upload-btn')?.addEventListener('click', () => document.getElementById('abr-upload').click());
  document.getElementById('sot-upload-btn')?.addEventListener('click', () => document.getElementById('sot-upload').click());
  document.getElementById('abr-upload')?.addEventListener('change', (e) => handleFolderUpload(e.target.files, 'abr'));
  document.getElementById('sot-upload')?.addEventListener('change', (e) => handleFolderUpload(e.target.files, 'sot'));

  // Save analyzed into abronal folder (client-side): zip fallback or File System Access API
  document.getElementById('save-analyzed-btn')?.addEventListener('click', async () => {
    const abrFiles = state.abronalFiles || null;
    const sotFiles = state.sotFiles || null;
    if (!abrFiles) return alert('Please upload the Abronal folder first.');
    const dateLabel = document.getElementById('dateLabel')?.value || '';
    try {
      await saveAnalyzedToFolder(abrFiles, sotFiles, dateLabel);
      alert('Analyzed package prepared for download/saved.');
    } catch (err) {
      console.error(err);
      alert('Failed to save analyzed: ' + err.message);
    }
  });

  // Browse buttons — event delegation on the whole document
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-browse');
    if (btn) openPicker(btn.dataset.target);
  });

  // Picker controls
  document.getElementById('picker-close').addEventListener('click', closePicker);
  document.getElementById('picker-cancel').addEventListener('click', closePicker);
  document.getElementById('picker-confirm').addEventListener('click', confirmPicker);
  document.getElementById('picker-backdrop').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closePicker(); // click-outside
  });

  // Bootstrap
  checkApiHealth();
  setInterval(checkApiHealth, 30000);
  startLogPolling();
  loadServerInfo();
  setInterval(loadServerInfo, 60000);

  // Restore last-uploaded dir name (cached client-side)
  const lastDir = localStorage.getItem('lastUploadDir');
  const lastType = localStorage.getItem('lastUploadType');
  if (lastDir) {
    if (lastType === 'sot') document.getElementById('sotDir').value = lastDir;
    else document.getElementById('abrDir').value = lastDir;
    const pathsEl = document.getElementById('pipeline-paths-code');
    const analyzedName = (document.getElementById('dateLabel')?.value || new Date().toISOString().slice(0,10)) + 'analyzed';
    if (pathsEl) pathsEl.textContent = `${lastDir}/analyzed/${analyzedName}`;
  }
});

function getRootFromFileList(files) {
  if (!files || !files.length) return null;
  // webkitRelativePath format: "rootdir/sub/file.ext"
  const fp = files[0].webkitRelativePath || files[0].name;
  const parts = fp.split('/');
  return parts[0] || parts[0];
}

function handleFolderUpload(files, kind) {
  if (!files || !files.length) return;
  const root = getRootFromFileList(files);
  if (kind === 'abr') {
    document.getElementById('abrDir').value = root;
    localStorage.setItem('lastUploadDir', root);
    localStorage.setItem('lastUploadType', 'abr');
    state.abronalFiles = files;
  } else {
    document.getElementById('sotDir').value = root;
    localStorage.setItem('lastUploadDir', root);
    localStorage.setItem('lastUploadType', 'sot');
    state.sotFiles = files;
  }
  // Suggest analyzed path next to abronal root
  const pathsEl = document.getElementById('pipeline-paths-code');
  const dateLabel = document.getElementById('dateLabel')?.value || '';
  const analyzedName = (dateLabel || new Date().toISOString().slice(0,10)) + 'analyzed';
  if (pathsEl) pathsEl.textContent = `${root}/analyzed/${analyzedName}`;
}

async function saveAnalyzedToFolder(abrFiles, sotFiles, dateLabel) {
  // Create zip with structure: <abrRoot>/analyzed/<dateLabel>analyzed/... (contains uploaded files and manifest)
  const root = getRootFromFileList(abrFiles);
  const analyzedName = (dateLabel || new Date().toISOString().slice(0,10)) + 'analyzed';
  const basePath = `${root}/analyzed/${analyzedName}/`;

  const zip = new JSZip();

  // copy abr files into zip under basePath/abronal/
  const abrFolder = zip.folder(basePath + 'abronal');
  for (const f of abrFiles) {
    const rel = f.webkitRelativePath ? f.webkitRelativePath.split('/').slice(1).join('/') : f.name;
    abrFolder.file(rel, f);
  }

  if (sotFiles) {
    const sotFolder = zip.folder(basePath + 'sot');
    for (const f of sotFiles) {
      const rel = f.webkitRelativePath ? f.webkitRelativePath.split('/').slice(1).join('/') : f.name;
      sotFolder.file(rel, f);
    }
  }

  // manifest
  const manifest = {
    created_at: new Date().toISOString(),
    abr_root: root,
    analyzed_folder: `${root}/analyzed/${analyzedName}`,
    files_count: abrFiles.length + (sotFiles ? sotFiles.length : 0),
  };
  zip.file(basePath + 'manifest.json', JSON.stringify(manifest, null, 2));

  // Try File System Access API if available
  if ('showDirectoryPicker' in window) {
    try {
      const handle = await window.showDirectoryPicker();
      // create or get the abronal root folder inside chosen handle
      const rootHandle = await handle.getDirectoryHandle(root, { create: true }).catch(() => null);
      const analyzedHandle = await handle.getDirectoryHandle(root, { create: true }).then(h => h).then(async (h) => await h.getDirectoryHandle('analyzed', { create: true })).then(async (h) => await h.getDirectoryHandle(analyzedName, { create: true }));
      // write files directly
      for (const f of abrFiles) {
        const rel = f.webkitRelativePath ? f.webkitRelativePath.split('/').slice(1).join('/') : f.name;
        const fileHandle = await analyzedHandle.getFileHandle('abronal/' + rel, { create: true }).catch(async () => {
          // ensure subdirs
          const parts = ('abronal/' + rel).split('/');
          let cur = analyzedHandle;
          for (let i = 0; i < parts.length - 1; i++) {
            cur = await cur.getDirectoryHandle(parts[i], { create: true });
          }
          return await cur.getFileHandle(parts[parts.length-1], { create: true });
        });
        const writable = await fileHandle.createWritable();
        await writable.write(f);
        await writable.close();
      }
      // write manifest
      const mf = await analyzedHandle.getFileHandle('manifest.json', { create: true });
      const mw = await mf.createWritable();
      await mw.write(JSON.stringify(manifest, null, 2));
      await mw.close();
      return;
    } catch (err) {
      console.warn('FS Access API write failed, falling back to zip download', err);
    }
  }

  // Fallback: generate zip and trigger download
  const content = await zip.generateAsync({ type: 'blob' });
  const url = URL.createObjectURL(content);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${root.replace(/\s+/g,'_') || 'analyzed'}-${analyzedName}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function loadServerInfo() {
  try {
    const res = await fetch(`${API_BASE}/info/`);
    if (!res.ok) throw new Error('failed');
    const payload = await res.json();
    const el = document.getElementById('external-access');
    if (!el) return;
    const urls = payload.urls || [];
    if (!urls.length) {
      el.textContent = 'No network address detected.';
      return;
    }
    el.innerHTML = urls.map(u => `<div><a href="${u}" target="_blank" rel="noopener">${u}</a></div>`).join('');
  } catch (err) {
    const el = document.getElementById('external-access');
    if (el) el.textContent = 'Failed to detect network address.';
  }
}
