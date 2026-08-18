const API_BASE = '/api';

const state = {
  records: [],
  logContent: '',
  refreshTimer: null,
};

function setStatus(message, isError = false) {
  const statusEl = document.getElementById('status');
  statusEl.textContent = message;
  statusEl.classList.toggle('error', isError);
}

async function loadRecords() {
  try {
    const response = await fetch(`${API_BASE}/records`);
    const data = await response.json();
    state.records = Array.isArray(data) ? data : [];
    renderRecords();
  } catch (error) {
    console.error(error);
    setStatus('Unable to load records.', true);
  }
}

async function loadLog() {
  try {
    const response = await fetch(`${API_BASE}/export/log`);
    const payload = await response.json();
    state.logContent = payload.content || 'No log output yet.';
    document.getElementById('log-box').textContent = state.logContent;
  } catch (error) {
    console.error(error);
  }
}

function renderRecords() {
  const tbody = document.getElementById('records-body');
  if (!tbody) return;

  if (!state.records.length) {
    tbody.innerHTML = '<tr><td colspan="4">No records yet.</td></tr>';
    return;
  }

  tbody.innerHTML = state.records
    .map((record) => `
      <tr>
        <td>${record.doctor_name || '—'}</td>
        <td>${record.service || '—'}</td>
        <td>${record.amount ?? '—'}</td>
        <td>${record.category || '—'}</td>
      </tr>
    `)
    .join('');
}

async function handleSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  const button = document.getElementById('submit-btn');
  const fromDate = document.getElementById('fromDate').value;
  const toDate = document.getElementById('toDate').value;
  const physicians = document.getElementById('physicians').value;

  button.disabled = true;
  button.textContent = 'Starting export...';
  setStatus('');

  try {
    const response = await fetch(`${API_BASE}/export/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        from_date: fromDate,
        to_date: toDate,
        physicians: physicians.split(',').map((name) => name.trim()).filter(Boolean),
      }),
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || 'Export request failed');
    }

    setStatus(`Export queued. ${payload.status || 'Request accepted.'}`);
    await loadLog();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = 'Start export';
  }
}

function startPolling() {
  if (state.refreshTimer) {
    window.clearInterval(state.refreshTimer);
  }
  state.refreshTimer = window.setInterval(loadLog, 3000);
}

function setPipelineStatus(message, isError = false) {
  const el = document.getElementById('pipeline-status');
  el.textContent = message;
  el.classList.toggle('error', isError);
}

function renderPipelineSummary(rows) {
  const head = document.getElementById('pipeline-head');
  const body = document.getElementById('pipeline-body');
  if (!rows || !rows.length) {
    head.innerHTML = '';
    body.innerHTML = '<tr><td>No rows returned.</td></tr>';
    return;
  }
  const columns = Object.keys(rows[0]);
  head.innerHTML = columns.map((c) => `<th>${c}</th>`).join('');
  body.innerHTML = rows
    .map((row) => `<tr>${columns.map((c) => `<td>${row[c] ?? '—'}</td>`).join('')}</tr>`)
    .join('');
}

async function pollPipeline(runId) {
  const response = await fetch(`${API_BASE}/pipeline/status/${runId}`);
  const payload = await response.json();

  if (payload.status === 'error') {
    setPipelineStatus(`Pipeline failed: ${payload.error}`, true);
    return;
  }
  if (payload.status !== 'done') {
    setPipelineStatus(`Pipeline ${payload.status}...`);
    window.setTimeout(() => pollPipeline(runId), 2000);
    return;
  }

  const resultsResponse = await fetch(`${API_BASE}/pipeline/results/${runId}`);
  const results = await resultsResponse.json();
  setPipelineStatus(
    `Done. ${results.perfect_match_count} matched, ${results.mismatch_count} mismatched. Saved to ${results.db_path}`
  );
  renderPipelineSummary(results.commission_summary);
}

async function handlePipelineSubmit(event) {
  event.preventDefault();
  const button = document.getElementById('pipeline-btn');
  const abr_dir = document.getElementById('abrDir').value;
  const sot_dir = document.getElementById('sotDir').value;
  const date_label = document.getElementById('dateLabel').value;

  button.disabled = true;
  button.textContent = 'Running...';
  setPipelineStatus('');

  try {
    const response = await fetch(`${API_BASE}/pipeline/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ abr_dir, sot_dir, date_label }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || 'Pipeline request failed');
    }
    setPipelineStatus('Pipeline queued...');
    pollPipeline(payload.run_id);
  } catch (error) {
    setPipelineStatus(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = 'Run Pipeline';
  }
}

window.addEventListener('DOMContentLoaded', () => {
  document.getElementById('export-form').addEventListener('submit', handleSubmit);
    document.getElementById('pipeline-form').addEventListener('submit', handlePipelineSubmit);
  loadRecords();
  loadLog();
  startPolling();
});
