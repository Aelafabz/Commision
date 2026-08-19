/* ── Commission Evaluation — Evaluation Page JS ───────────────────── */

// ── State ────────────────────────────────────────────────────────────
const state = {
  tables: [],
  currentTable: '',
  columns: [],
  page: 1,
  pageSize: 100,
  totalPages: 1,
  total: 0,
  columnFilters: {}, // { columnName: value }
  columnValues: {},  // { columnName: [distinct values] }
};

// ── DOM References ───────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const tableSelect = $('table-select');
const dateStart = $('date-start');
const dateEnd = $('date-end');
const pageSizeSelect = $('page-size');
const applyFiltersBtn = $('apply-filters-btn');
const resetFiltersBtn = $('reset-filters-btn');
const exportTableBtn = $('export-table-btn');
const exportAllBtn = $('export-all-btn');
const columnFilters = $('column-filters');
const tableHead = $('table-head');
const tableBody = $('table-body');
const tableInfo = $('table-info');
const prevPageBtn = $('prev-page-btn');
const nextPageBtn = $('next-page-btn');
const pageInfo = $('page-info');
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

// ── Init: load tables & summary ──────────────────────────────────────
async function init() {
  await loadTables();
  await loadSummary();
}

async function loadTables() {
  try {
    const res = await fetch('/api/evaluation/tables');
    const data = await res.json();
    state.tables = data.tables || [];

    tableSelect.innerHTML = '<option value="">Select a table…</option>';
    state.tables.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t.replace(/_/g, ' ');
      tableSelect.appendChild(opt);
    });
  } catch (err) {
    showToast(`Failed to load tables: ${err.message}`, 'error');
  }
}

async function loadSummary() {
  const summaryMap = {
    'matched_records': 'sum-matched',
    'unmatched_records': 'sum-unmatched',
    'physicians': 'sum-physicians',
    'commission_per_physicians': 'sum-commission',
  };

  try {
    // Fetch first page of each table to get total counts
    for (const [table, elId] of Object.entries(summaryMap)) {
      const res = await fetch(`/api/evaluation/data/${table}?page=1&page_size=1`);
      const data = await res.json();
      $(elId).textContent = data.total.toLocaleString();
    }
  } catch {
    // Leave as "—" if tables don't exist yet
  }
}

// ── Table selection ──────────────────────────────────────────────────
async function onTableChange() {
  state.currentTable = tableSelect.value;
  if (!state.currentTable) {
    clearTable();
    return;
  }

  state.page = 1;
  state.columnFilters = {};
  state.columnValues = {};

  await loadColumnValues();
  renderColumnFilters();
  await loadData();
}

function clearTable() {
  tableHead.innerHTML = '';
  tableBody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--gray-500); padding: 2rem;">Select a table to view data</td></tr>';
  tableInfo.textContent = '';
  pageInfo.textContent = 'Page 1 of 1';
  prevPageBtn.disabled = true;
  nextPageBtn.disabled = true;
  columnFilters.innerHTML = '';
}

// ── Column values for filter dropdowns ───────────────────────────────
async function loadColumnValues() {
  try {
    const res = await fetch(`/api/evaluation/columns/${state.currentTable}`);
    const data = await res.json();
    state.columnValues = data.columns || {};
  } catch (err) {
    showToast(`Failed to load column values: ${err.message}`, 'error');
    state.columnValues = {};
  }
}

function renderColumnFilters() {
  columnFilters.innerHTML = '';
  const cols = Object.keys(state.columnValues);

  cols.forEach(col => {
    const values = state.columnValues[col] || [];
    if (!values.length) return;

    const group = document.createElement('div');
    group.className = 'filter-group';

    const label = document.createElement('label');
    label.textContent = col.replace(/_/g, ' ');
    group.appendChild(label);

    const select = document.createElement('select');
    select.dataset.col = col;

    const optAll = document.createElement('option');
    optAll.value = '';
    optAll.textContent = 'All';
    select.appendChild(optAll);

    values.forEach(v => {
      const opt = document.createElement('option');
      opt.value = String(v);
      opt.textContent = String(v).length > 30 ? String(v).substring(0, 30) + '…' : String(v);
      select.appendChild(opt);
    });

    select.addEventListener('change', () => {
      state.columnFilters[col] = select.value;
    });

    group.appendChild(select);
    columnFilters.appendChild(group);
  });
}

// ── Data loading ─────────────────────────────────────────────────────
async function loadData() {
  if (!state.currentTable) return;

  const params = new URLSearchParams({
    page: state.page,
    page_size: state.pageSize,
  });

  if (dateStart.value) params.set('date_start', dateStart.value);
  if (dateEnd.value) params.set('date_end', dateEnd.value);

  // Build filters JSON
  const activeFilters = {};
  Object.entries(state.columnFilters).forEach(([k, v]) => {
    if (v) activeFilters[k] = v;
  });
  if (Object.keys(activeFilters).length) {
    params.set('filters', JSON.stringify(activeFilters));
  }

  try {
    const res = await fetch(`/api/evaluation/data/${state.currentTable}?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to load data');

    state.columns = data.columns || [];
    state.total = data.total || 0;
    state.totalPages = data.total_pages || 1;

    renderTable(data.data);
    updatePagination();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderTable(rows) {
  // Header
  tableHead.innerHTML = '';
  const headRow = document.createElement('tr');
  state.columns.forEach(col => {
    const th = document.createElement('th');
    th.textContent = col.replace(/_/g, ' ');
    th.title = col;
    headRow.appendChild(th);
  });
  tableHead.appendChild(headRow);

  // Body
  tableBody.innerHTML = '';
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = Math.max(state.columns.length, 1);
    td.style.textAlign = 'center';
    td.style.color = 'var(--gray-500)';
    td.style.padding = '2rem';
    td.textContent = 'No data found';
    tr.appendChild(td);
    tableBody.appendChild(tr);
    return;
  }

  rows.forEach(row => {
    const tr = document.createElement('tr');
    state.columns.forEach(col => {
      const td = document.createElement('td');
      let val = row[col];
      if (val === null || val === undefined) {
        td.textContent = '—';
      } else if (typeof val === 'number') {
        td.textContent = Number.isInteger(val) ? val.toLocaleString() : val.toFixed(2);
        td.style.textAlign = 'right';
      } else {
        td.textContent = String(val);
      }
      td.title = String(val ?? '');
      tr.appendChild(td);
    });
    tableBody.appendChild(tr);
  });

  tableInfo.textContent = `— ${state.total.toLocaleString()} rows`;
}

// ── Pagination ───────────────────────────────────────────────────────
function updatePagination() {
  pageInfo.textContent = `Page ${state.page} of ${state.totalPages}`;
  prevPageBtn.disabled = state.page <= 1;
  nextPageBtn.disabled = state.page >= state.totalPages;
}

// ── Export ───────────────────────────────────────────────────────────
function buildExportParams() {
  const params = new URLSearchParams();
  if (dateStart.value) params.set('date_start', dateStart.value);
  if (dateEnd.value) params.set('date_end', dateEnd.value);

  const activeFilters = {};
  Object.entries(state.columnFilters).forEach(([k, v]) => {
    if (v) activeFilters[k] = v;
  });
  if (Object.keys(activeFilters).length) {
    params.set('filters', JSON.stringify(activeFilters));
  }
  return params;
}

function exportTable() {
  if (!state.currentTable) {
    showToast('Select a table first', 'error');
    return;
  }
  const params = buildExportParams();
  const url = `/api/evaluation/export/${state.currentTable}?${params.toString()}`;
  window.open(url, '_blank');
}

function exportAll() {
  const params = new URLSearchParams();
  if (dateStart.value) params.set('date_start', dateStart.value);
  if (dateEnd.value) params.set('date_end', dateEnd.value);
  const url = `/api/evaluation/export-all?${params.toString()}`;
  window.open(url, '_blank');
}

// ── Event listeners ──────────────────────────────────────────────────
tableSelect.addEventListener('change', onTableChange);
pageSizeSelect.addEventListener('change', () => {
  state.pageSize = parseInt(pageSizeSelect.value, 10);
  state.page = 1;
  loadData();
});

applyFiltersBtn.addEventListener('click', () => {
  state.page = 1;
  loadData();
});

resetFiltersBtn.addEventListener('click', () => {
  dateStart.value = '';
  dateEnd.value = '';
  state.columnFilters = {};
  state.page = 1;
  // Reset all column filter selects
  document.querySelectorAll('#column-filters select').forEach(sel => {
    sel.value = '';
  });
  loadData();
});

prevPageBtn.addEventListener('click', () => {
  if (state.page > 1) {
    state.page--;
    loadData();
  }
});

nextPageBtn.addEventListener('click', () => {
  if (state.page < state.totalPages) {
    state.page++;
    loadData();
  }
});

exportTableBtn.addEventListener('click', exportTable);
exportAllBtn.addEventListener('click', exportAll);

// ── Init ─────────────────────────────────────────────────────────────
init();