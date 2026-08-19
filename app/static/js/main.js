/* ── Commission Reconciliation — Main Page JS ─────────────────────── */

// ── State ────────────────────────────────────────────────────────────
const state = {
  sotFiles: [],
  abronalFiles: [],
  currentJobId: null,
  activeStep: null, // 'primary' | 'secondary' | 'merger'
  pipelineRunning: false,
};

// ── DOM References ───────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const sotZone = $('sot-zone');
const sotInput = $('sot-input');
const sotFileList = $('sot-file-list');
const sotUploadBtn = $('sot-upload-btn');

const abronalZone = $('abronal-zone');
const abronalInput = $('abronal-input');
const abronalFileList = $('abronal-file-list');
const abronalUploadBtn = $('abronal-upload-btn');

const runPrimaryBtn = $('run-primary-btn');
const runSecondaryBtn = $('run-secondary-btn');
const runMergerBtn = $('run-merger-btn');

const progressBar = $('progress-bar');
const progressLabel = $('progress-label');
const statusBadges = $('status-badges');
const logWindow = $('log-window');
const toast = $('toast');

// ── Toast ────────────────────────────────────────────────────────────
let toastTimer = null;
function showToast(message, type = 'info') {
  toast.textContent = message;
  toast.className = `show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.className = '';
  }, 3500);
}

// ── Log helpers ──────────────────────────────────────────────────────
function addLog(message, type = 'info') {
  const p = document.createElement('p');
  p.className = `log-line ${type}`;
  p.textContent = message;
  logWindow.appendChild(p);
  logWindow.scrollTop = logWindow.scrollHeight;
}

function clearLog() {
  logWindow.innerHTML = '';
}

// ── File selection & drag-drop ───────────────────────────────────────
function setupUploadZone(zone, input, fileListEl, uploadBtn, kind) {
  // Click zone → trigger input
  zone.addEventListener('click', (e) => {
    if (e.target !== input) input.click();
  });

  // Drag & drop
  zone.addEventListener('dragover', (e) => {
    e.preventDefault();
    zone.classList.add('dragover');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('dragover');
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.xlsx'));
    if (files.length) {
      if (kind === 'sot') state.sotFiles = files;
      else state.abronalFiles = files;
      renderFileList(fileListEl, files);
      uploadBtn.disabled = false;
    } else {
      showToast('Only .xlsx files are accepted', 'error');
    }
  });

  // Input change
  input.addEventListener('change', () => {
    const files = Array.from(input.files).filter(f => f.name.endsWith('.xlsx'));
    if (files.length) {
      if (kind === 'sot') state.sotFiles = files;
      else state.abronalFiles = files;
      renderFileList(fileListEl, files);
      uploadBtn.disabled = false;
    } else {
      showToast('Only .xlsx files are accepted', 'error');
    }
  });
}

function renderFileList(container, files) {
  container.innerHTML = '';
  files.forEach(f => {
    const tag = document.createElement('span');
    tag.className = 'file-tag';
    tag.textContent = f.name;
    container.appendChild(tag);
  });
}

// ── Upload ───────────────────────────────────────────────────────────
async function uploadFiles(kind) {
  const files = kind === 'sot' ? state.sotFiles : state.abronalFiles;
  if (!files.length) {
    showToast('No files selected', 'error');
    return;
  }

  const formData = new FormData();
  files.forEach(f => formData.append('files', f));

  const endpoint = kind === 'sot' ? '/api/reconciliation/upload/sot' : '/api/reconciliation/upload/abronal';
  const btn = kind === 'sot' ? sotUploadBtn : abronalUploadBtn;

  btn.disabled = true;
  btn.textContent = 'Uploading…';

  try {
    const res = await fetch(endpoint, { method: 'POST', body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Upload failed');

    showToast(`Uploaded ${data.count} file(s)`, 'success');
    addLog(`Uploaded ${data.count} ${kind.toUpperCase()} file(s): ${data.uploaded.join(', ')}`, 'done');

    // Enable pipeline buttons once both have files
    checkPipelineReady();
  } catch (err) {
    showToast(err.message, 'error');
    addLog(`Upload failed: ${err.message}`, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = kind === 'sot' ? 'Upload SOT Files' : 'Upload Abronal Files';
  }
}

// ── Pipeline readiness ───────────────────────────────────────────────
async function checkPipelineReady() {
  try {
    const res = await fetch('/api/reconciliation/uploads');
    const data = await res.json();
    const hasSot = data.sot.length > 0;
    const hasAbr = data.abronal.length > 0;
    runPrimaryBtn.disabled = !(hasSot && hasAbr) || state.pipelineRunning;
  } catch {
    runPrimaryBtn.disabled = true;
  }
}

// ── Pipeline run ─────────────────────────────────────────────────────
async function runPipeline(step) {
  if (state.pipelineRunning) {
    showToast('A pipeline step is already running', 'error');
    return;
  }

  let endpoint = '';
  let body = null;

  if (step === 'primary') {
    endpoint = '/api/reconciliation/run/primary';
  } else if (step === 'secondary') {
    endpoint = '/api/reconciliation/run/secondary';
    const params = new URLSearchParams({
      confidence: $('confidence-input').value || '0.70',
      amount_tolerance: $('amount-tol-input').value || '1.0',
      date_tolerance_days: $('date-tol-input').value || '1',
    });
    endpoint += `?${params.toString()}`;
  } else if (step === 'merger') {
    endpoint = '/api/reconciliation/run/category-merge';
  }

  try {
    const res = await fetch(endpoint, { method: 'POST', body });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to start pipeline');

    state.currentJobId = data.job_id;
    state.pipelineRunning = true;
    state.activeStep = step;

    // Disable all run buttons
    setRunButtonsDisabled(true);
    setStepActive(step);
    addLog(`Started ${step} pipeline (job: ${data.job_id})`, 'info');

    // Start SSE stream
    startSSE(data.job_id);
  } catch (err) {
    showToast(err.message, 'error');
    addLog(`Failed to start ${step}: ${err.message}`, 'error');
  }
}

function setRunButtonsDisabled(disabled) {
  runPrimaryBtn.disabled = disabled;
  runSecondaryBtn.disabled = disabled;
  runMergerBtn.disabled = disabled;
}

// ── SSE progress stream ──────────────────────────────────────────────
function startSSE(jobId) {
  const evtSource = new EventSource(`/api/reconciliation/status/${jobId}`);

  evtSource.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.error) {
      addLog(`Error: ${data.error}`, 'error');
      evtSource.close();
      state.pipelineRunning = false;
      setRunButtonsDisabled(false);
      return;
    }

    // Update progress bar
    const pct = data.progress || 0;
    progressBar.style.width = `${pct}%`;
    progressLabel.textContent = `${pct}%`;

    // Append new logs
    if (data.logs && data.logs.length) {
      data.logs.forEach(log => {
        const type = log.includes('[ERROR]') ? 'error'
          : log.includes('[DONE]') || log.includes('completed') ? 'done'
          : log.includes('[WARN]') ? 'warn' : 'info';
        addLog(log, type);
      });
    }

    // Handle status
    if (data.status === 'done') {
      setStepDone(state.activeStep);
      addLog(`✅ ${state.activeStep} pipeline completed successfully`, 'done');
      showToast(`${state.activeStep} completed`, 'success');
      addStatusBadge(state.activeStep, 'success', data.result);
      evtSource.close();
      state.pipelineRunning = false;
      setRunButtonsDisabled(false);
      checkPipelineReady();
    } else if (data.status === 'error') {
      setStepError(state.activeStep);
      addLog(`❌ ${state.activeStep} pipeline failed`, 'error');
      showToast(`${state.activeStep} failed`, 'error');
      addStatusBadge(state.activeStep, 'error');
      evtSource.close();
      state.pipelineRunning = false;
      setRunButtonsDisabled(false);
    }
  };

  evtSource.onerror = () => {
    // Fallback to polling if SSE fails
    evtSource.close();
    pollStatus(jobId);
  };
}

// ── Polling fallback ─────────────────────────────────────────────────
async function pollStatus(jobId) {
  const poll = async () => {
    try {
      const res = await fetch(`/api/reconciliation/status-poll/${jobId}`);
      const data = await res.json();

      const pct = data.progress || 0;
      progressBar.style.width = `${pct}%`;
      progressLabel.textContent = `${pct}%`;

      if (data.logs && data.logs.length) {
        data.logs.forEach(log => {
          const type = log.includes('[ERROR]') ? 'error'
            : log.includes('[DONE]') || log.includes('completed') ? 'done'
            : log.includes('[WARN]') ? 'warn' : 'info';
          addLog(log, type);
        });
      }

      if (data.status === 'done') {
        setStepDone(state.activeStep);
        addLog(`✅ ${state.activeStep} pipeline completed successfully`, 'done');
        showToast(`${state.activeStep} completed`, 'success');
        addStatusBadge(state.activeStep, 'success', data.result);
        state.pipelineRunning = false;
        setRunButtonsDisabled(false);
        checkPipelineReady();
        return;
      }
      if (data.status === 'error') {
        setStepError(state.activeStep);
        addLog(`❌ ${state.activeStep} pipeline failed`, 'error');
        showToast(`${state.activeStep} failed`, 'error');
        addStatusBadge(state.activeStep, 'error');
        state.pipelineRunning = false;
        setRunButtonsDisabled(false);
        return;
      }

      setTimeout(poll, 1000);
    } catch (err) {
      addLog(`Polling error: ${err.message}`, 'error');
      state.pipelineRunning = false;
      setRunButtonsDisabled(false);
    }
  };
  poll();
}

// ── Step indicators ──────────────────────────────────────────────────
function setStepActive(step) {
  document.querySelectorAll('.step').forEach(el => {
    el.classList.remove('active', 'done', 'error');
    if (el.dataset.step === step) el.classList.add('active');
  });
}

function setStepDone(step) {
  const el = document.querySelector(`.step[data-step="${step}"]`);
  if (el) {
    el.classList.remove('active', 'error');
    el.classList.add('done');
  }
}

function setStepError(step) {
  const el = document.querySelector(`.step[data-step="${step}"]`);
  if (el) {
    el.classList.remove('active', 'done');
    el.classList.add('error');
  }
}

// ── Status badges ────────────────────────────────────────────────────
function addStatusBadge(step, status, result) {
  const badge = document.createElement('span');
  badge.className = `badge ${status === 'success' ? 'badge-success' : 'badge-error'}`;
  badge.textContent = `${step}: ${status === 'success' ? '✓ Success' : '✗ Failed'}`;
  statusBadges.appendChild(badge);

  // If result has counts, show them
  if (result && typeof result === 'object') {
    const info = document.createElement('span');
    info.className = 'badge badge-info';
    const counts = Object.entries(result)
      .filter(([k, v]) => typeof v === 'number')
      .map(([k, v]) => `${k}: ${v}`)
      .join(' · ');
    if (counts) {
      info.textContent = counts;
      statusBadges.appendChild(info);
    }
  }
}

// ── Event listeners ──────────────────────────────────────────────────
sotUploadBtn.addEventListener('click', () => uploadFiles('sot'));
abronalUploadBtn.addEventListener('click', () => uploadFiles('abronal'));

runPrimaryBtn.addEventListener('click', () => runPipeline('primary'));
runSecondaryBtn.addEventListener('click', () => runPipeline('secondary'));
runMergerBtn.addEventListener('click', () => runPipeline('merger'));

// ── Init ─────────────────────────────────────────────────────────────
setupUploadZone(sotZone, sotInput, sotFileList, sotUploadBtn, 'sot');
setupUploadZone(abronalZone, abronalInput, abronalFileList, abronalUploadBtn, 'abronal');

// Check for existing uploads on load
checkPipelineReady();