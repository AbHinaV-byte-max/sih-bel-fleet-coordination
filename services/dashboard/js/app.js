/**
 * SIH26123 — AMR Fleet Coordination Dashboard Controller v6.0
 * Bharat Electronics Limited (BEL)
 *
 * 5-View Dashboard — LEFT SIDEBAR NAV:
 *   1. Fleet Overview   — AMR table with state reason + conflict peer
 *   2. Warehouse Map    — 2D tactical canvas
 *   3. Robot Detail     — WHY block, §11.2 reservations, AI/Arbiter split, history
 *   4. Coordination Log — Engineering event stream, deadlock alert, export
 *   5. Performance      — §18.3 metrics + benchmark + S1–S10 scenarios
 *
 * Architecture: Dashboard OBSERVES telemetry only.
 * AMR agents coordinate peer-to-peer — not via this UI.
 */

// ── Global State ──────────────────────────────────────────────────
let ws                = null;
let canvas            = null;
let trendChart        = null;
let lastSnapshot      = null;
let isSimRunning      = true;
let selectedRobotId   = null;
let logPaused         = false;
let logFilterRobot    = 'all';
let logFilterType     = 'all';
let logBuffer         = [];       // rolling log entries (max 300)

// Per-type counters derived from log buffer
const logCounters = { YIELD: 0, WAIT: 0, REROUTE: 0, CONTINUE: 0 };

// §14 Scenario definitions
const SCENARIOS = [
  { id:'S1',  name:'Normal Traffic',           desc:'Steady-state, no disruptions' },
  { id:'S2',  name:'Crossing Conflict',        desc:'Two robots at same intersection' },
  { id:'S3',  name:'Narrow Aisle Conflict',    desc:'Single-cell corridor contention' },
  { id:'S4',  name:'Potential Deadlock',       desc:'Mutual blocking (A→B, B→A)' },
  { id:'S5',  name:'Blocked Aisle',            desc:'Dynamic obstacle drops mid-route' },
  { id:'S6',  name:'Robot Failure',            desc:'AMR stops responding mid-task' },
  { id:'S7',  name:'Comms Degradation',        desc:'P2P heartbeat timeout (§12)' },
  { id:'S8',  name:'Emergency Task',           desc:'Critical priority injected' },
  { id:'S9',  name:'Battery Constraint',       desc:'Low-battery forced charging' },
  { id:'S10', name:'Congestion Concentration', desc:'4 tasks through one corridor' },
];

// ── Init ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  canvas     = new WarehouseCanvas('warehouseCanvas');
  trendChart = new TrendChart('trendChartCanvas');

  canvas.onRobotClick = (id) => {
    selectRobot(id);
    navigateTo('view-detail');
  };
  canvas.onCellClick = (gx, gy) => {
    if (currentView() === 'view-map') {
      el('obsX').value = gx;
      el('obsY').value = gy;
    }
  };

  setupSidebarNav();
  setupHeaderControls();
  setupTaskModal();
  setupHelpModal();
  setupMapControls();
  setupLogControls();
  setupPerformanceView();
  buildScenarioGrid();

  fetchInitialState();
  initWebSocket();
});

function currentView() {
  const pane = document.querySelector('.view-pane.active');
  return pane ? pane.id : null;
}

// ── Sidebar Navigation ─────────────────────────────────────────────
function setupSidebarNav() {
  document.querySelectorAll('.nav-btn[data-view]').forEach(btn => {
    btn.addEventListener('click', () => {
      navigateTo(btn.dataset.view);
    });
  });
}

function navigateTo(viewId) {
  document.querySelectorAll('.nav-btn[data-view]').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.view === viewId);
    btn.setAttribute('aria-selected', btn.dataset.view === viewId ? 'true' : 'false');
  });
  document.querySelectorAll('.view-pane').forEach(p => {
    p.classList.toggle('active', p.id === viewId);
  });
}

// ── Header Controls ────────────────────────────────────────────────
function setupHeaderControls() {
  el('btnToggleSim')?.addEventListener('click', async () => {
    if (isSimRunning) {
      await fetch('/api/simulation/pause', { method: 'POST' });
      isSimRunning = false;
      el('btnToggleSim').innerHTML = '▶ Resume';
      el('btnToggleSim').className = 'btn btn-success';
    } else {
      await fetch('/api/simulation/start', { method: 'POST' });
      isSimRunning = true;
      el('btnToggleSim').innerHTML = '⏸ Pause';
      el('btnToggleSim').className = 'btn btn-warning';
    }
  });

  el('btnStep')?.addEventListener('click', async () => {
    await fetch('/api/simulation/step', { method: 'POST' });
  });

  el('btnBenchmark')?.addEventListener('click', async () => {
    const res  = await fetch('/api/simulation/benchmark', { method: 'POST' });
    const data = await res.json();
    applyBenchmarkResult(data);
    navigateTo('view-perf');
  });

  el('btnHelp')?.addEventListener('click', ()         => openModal('helpModal'));
  el('btnHelpSidebar')?.addEventListener('click', ()  => openModal('helpModal'));
  el('btnNewTask')?.addEventListener('click', ()      => openModal('taskModal'));
}

// ── WebSocket ──────────────────────────────────────────────────────
function initWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/fleet-stream`);

  ws.onopen    = () => setConnected(true);
  ws.onclose   = () => { setConnected(false); setTimeout(initWebSocket, 3000); };
  ws.onerror   = () => setConnected(false);
  ws.onmessage = (evt) => {
    try {
      lastSnapshot = JSON.parse(evt.data);
      updateDashboard(lastSnapshot);
    } catch(e) { console.warn('WS parse error', e); }
  };
}

function setConnected(ok) {
  const dot       = el('connDot');
  const status    = el('connStatus');
  const sub       = el('connSubStatus');
  const indicator = el('connectionPill');

  if (ok) {
    dot.style.background   = 'var(--green-light)';
    status.textContent     = 'System Online';
    sub.textContent        = 'P2P mesh streaming';
    indicator.style.color  = 'var(--green-light)';
  } else {
    dot.style.background   = 'var(--red-light)';
    dot.style.animation    = 'none';
    status.textContent     = 'Reconnecting…';
    sub.textContent        = 'Awaiting WebSocket';
    indicator.style.color  = 'var(--red-light)';
  }
}

async function fetchInitialState() {
  try {
    const res = await fetch('/api/fleet/status');
    if (res.ok) updateDashboard(await res.json());
  } catch { /* WS will stream */ }
}

// ── Master Update ──────────────────────────────────────────────────
function updateDashboard(data) {
  if (!data) return;

  canvas.updateSnapshot(data);
  if (data.congestion_heatmap) canvas.updateHeatmap(data.congestion_heatmap);

  updateKPIStrip(data);
  updateFleetView(data);
  updateMapStats(data);

  if (selectedRobotId && data.robots?.[selectedRobotId]) {
    updateRobotDetail(data.robots[selectedRobotId]);
  }

  appendToLog(data.recent_decision_logs || []);
  updateLogStats(data.metrics || {});
  updateDeadlockAlert(data.metrics || {});
  updatePerformanceView(data);

  if (data.metrics?.trend_history) {
    trendChart.update(data.metrics.trend_history);
  }
}

// ── KPI Strip ─────────────────────────────────────────────────────
function updateKPIStrip(data) {
  const m = data.metrics || {};
  const robots = data.robots ? Object.values(data.robots) : [];

  // Collisions
  const col = m.total_collisions ?? 0;
  el('valCollisions').textContent = col;
  el('tagSafety').textContent     = col === 0 ? 'ZERO ✓' : `⚠ ${col}`;
  el('tagSafety').className       = `kpi-tag ${col === 0 ? 'tag-green' : 'tag-red'}`;
  el('valCollisions').className   = `kpi-val ${col === 0 ? 'kpi-green' : 'kpi-red'}`;

  // Efficiency
  const pct = m.efficiency_improvement_pct;
  el('valImprovement').textContent = pct != null ? `+${pct.toFixed(1)}%` : '—';

  // Active robots
  const active = robots.filter(r => r.state !== 'IDLE' && r.state !== 'FAILED').length;
  el('valActiveRobots').textContent = `${active} / ${robots.length}`;
  el('badgeFleetCount').textContent = robots.length;

  // Tasks
  el('valTasksDone').textContent = m.tasks_completed ?? 0;

  // Health tag
  const hasFault = robots.some(r => r.state === 'FAILED' || r.state === 'DEGRADED');
  el('tagHealthKpi').textContent = hasFault ? 'FAULT' : 'OPERATIONAL';
  el('tagHealthKpi').className   = `kpi-tag ${hasFault ? 'tag-red' : 'tag-amber'}`;
}

// ── VIEW 1: Fleet Overview ─────────────────────────────────────────
function updateFleetView(data) {
  const robots = data.robots ? Object.values(data.robots) : [];
  updateFleetTable(robots);
  updateTaskTable(data.tasks || []);
  updateRobotSelector(robots);
}

function updateFleetTable(robots) {
  const tbody = el('fleetTableBody');
  if (!tbody) return;

  if (!robots.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No robots found — check backend connection</td></tr>`;
    return;
  }

  tbody.innerHTML = robots.map(r => {
    const battPct = r.battery_pct ?? 100;
    const battCls = battPct > 50 ? 'batt-high' : battPct > 25 ? 'batt-medium' : 'batt-low';

    // Build the "reason + conflict peer + degraded age" cell
    let reasonHtml = `<span>${escHtml(r.state_reason || '—')}</span>`;

    // Show conflict peer on yielding/waiting states
    const conflictPeer = r.last_decision?.conflicting_peer_id;
    if (conflictPeer && (r.state === 'YIELDING' || r.state === 'WAITING')) {
      reasonHtml += `<div class="conflict-peer">↔ Yielding to: ${escHtml(conflictPeer)}</div>`;
    }

    // Show "last seen" for degraded/failed communication
    if (r.comm_status === 'DEGRADED' || r.comm_status === 'SAFE_MODE') {
      const age = r.last_seen_ms ? `${(r.last_seen_ms / 1000).toFixed(1)}s` : 'unknown';
      reasonHtml += `<div class="degraded-age">⚠ Last heartbeat: ${escHtml(age)} ago — ${escHtml(r.comm_status)}</div>`;
    }

    return `
      <tr id="amr-row-${r.id}" class="${r.id === selectedRobotId ? 'selected' : ''}"
          onclick="selectRobotRow('${escHtml(r.id)}')"
          title="Click to inspect ${escHtml(r.id)} in Robot Detail">
        <td class="td-main">${escHtml(r.id)}</td>
        <td>${escHtml(r.type || '—')}</td>
        <td><span class="state-tag state-${escHtml(r.state)}">${escHtml(r.state)}</span></td>
        <td><span class="comm-badge comm-${escHtml(r.comm_status || 'HEALTHY')}">${escHtml(r.comm_status || 'HEALTHY')}</span></td>
        <td>
          <div class="batt-wrap">
            <div class="batt-bar-bg"><div class="batt-bar-fill ${battCls}" style="width:${battPct}%"></div></div>
            <span class="batt-val">${battPct}%</span>
          </div>
        </td>
        <td>${(r.velocity_mps ?? 0).toFixed(1)} m/s</td>
        <td>${(r.odometer_meters ?? 0).toFixed(0)} m</td>
        <td>${r.current_task_id ? escHtml(r.current_task_id) : '<span style="color:var(--text-muted)">—</span>'}</td>
        <td class="td-reason">${reasonHtml}</td>
      </tr>
    `;
  }).join('');
}

function selectRobotRow(id) {
  selectRobot(id);
  navigateTo('view-detail');
}

function updateTaskTable(tasks) {
  const tbody = el('taskTableBody');
  if (!tbody) return;
  if (!tasks.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No tasks dispatched yet</td></tr>`;
    return;
  }
  tbody.innerHTML = tasks.map(t => {
    const pc = `p${t.priority || 1}`;
    return `
      <tr>
        <td class="mono" style="color:var(--text-main);font-weight:600">${escHtml(t.id)}</td>
        <td class="mono">(${t.pickup_pos?.join(',') ?? '—'})</td>
        <td class="mono">(${t.dropoff_pos?.join(',') ?? '—'})</td>
        <td class="mono">${t.payload_weight_kg ?? '—'} kg</td>
        <td><span class="prio-chip ${pc}">${t.priority ?? '—'}</span></td>
        <td style="color:var(--blue-light);font-weight:600">${t.assigned_robot_id ?? '<span style="color:var(--text-muted)">Unassigned</span>'}</td>
        <td><span class="status-chip ${t.status}">${t.status ?? '—'}</span></td>
      </tr>
    `;
  }).join('');
}

function updateRobotSelector(robots) {
  const sel = el('robotSelector');
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = '<option value="">— Select AMR —</option>' +
    robots.map(r => `<option value="${r.id}"${r.id === selectedRobotId ? ' selected' : ''}>${r.id} (${r.state})</option>`).join('');
  if (prev) sel.value = prev;
  sel.onchange = () => selectRobot(sel.value);
}

// ── VIEW 2: Map ────────────────────────────────────────────────────
function updateMapStats(data) {
  const m = data.metrics || {};
  setEl('statConflictsDetected', m.conflicts_detected  ?? 0);
  setEl('statConflictsResolved', m.conflicts_resolved  ?? 0);
  setEl('statReroutes',          m.reroute_count       ?? 0);
  setEl('statDeadlocks',         m.deadlock_count      ?? 0);
}

function setupMapControls() {
  el('btnZoomIn')?.addEventListener('click',    () => canvas.zoomIn());
  el('btnZoomOut')?.addEventListener('click',   () => canvas.zoomOut());
  el('btnResetView')?.addEventListener('click', () => canvas.resetView());

  document.querySelectorAll('.layer-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      btn.classList.toggle('active');
      canvas.setLayer(btn.dataset.layer, btn.classList.contains('active'));
    });
  });

  el('btnAddObstacle')?.addEventListener('click', async () => {
    const x = parseInt(el('obsX').value);
    const y = parseInt(el('obsY').value);
    await fetch('/api/obstacles/dynamic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x, y, action: 'add' }),
    });
  });
  el('btnRemoveObstacle')?.addEventListener('click', async () => {
    const x = parseInt(el('obsX').value);
    const y = parseInt(el('obsY').value);
    await fetch('/api/obstacles/dynamic', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ x, y, action: 'remove' }),
    });
  });

  // Sync obstacle list display
  setInterval(() => {
    if (!lastSnapshot?.warehouse?.dynamic_obstacles) return;
    const list = lastSnapshot.warehouse.dynamic_obstacles;
    el('dynamicObstacleList').textContent = list.length
      ? list.map(o => `(${o[0]},${o[1]})`).join('  ')
      : 'No dynamic obstacles';
  }, 500);
}

// ── VIEW 3: Robot Detail ───────────────────────────────────────────
function selectRobot(id) {
  selectedRobotId = id;
  canvas.setSelectedRobot(id);

  // Update table row selection
  document.querySelectorAll('.amr-table tbody tr').forEach(row => {
    row.classList.toggle('selected', row.id === `amr-row-${id}`);
  });

  // Update selector
  const sel = el('robotSelector');
  if (sel && id) sel.value = id;

  if (!id) {
    el('detailNoSelection').style.display = 'block';
    el('detailPanels').style.display = 'none';
    return;
  }
  el('detailNoSelection').style.display = 'none';
  el('detailPanels').style.display = 'block';

  if (lastSnapshot?.robots?.[id]) {
    updateRobotDetail(lastSnapshot.robots[id]);
  }
}

function updateRobotDetail(r) {
  if (!r) return;

  // Header
  el('detailRobotId').textContent = r.id || '—';

  const stTag = el('detailState');
  stTag.textContent = r.state || '—';
  stTag.className   = `state-tag state-${r.state}`;

  const commB = el('detailComm');
  commB.textContent = r.comm_status || 'HEALTHY';
  commB.className   = `comm-badge comm-${r.comm_status || 'HEALTHY'}`;

  // WHY block — most prominent element
  const reasonBlock = el('detailReasonBlock');
  const reason      = r.state_reason || 'No state reason available.';
  // Color the left border based on state
  const borderMap = {
    MOVING: 'var(--blue)',  YIELDING: 'var(--amber)', WAITING: 'var(--amber)',
    REROUTING: 'var(--red-light)', FAILED: 'var(--red-light)', DEGRADED: 'var(--red-light)',
    CHARGING: 'var(--green)', COMPLETED: 'var(--green)',
  };
  reasonBlock.style.borderLeftColor = borderMap[r.state] || 'var(--blue)';
  el('detailReason').textContent = reason;

  // Telemetry rows
  el('detailType').textContent     = r.type || '—';
  el('detailPos').textContent      = r.position ? `(${r.position.join(', ')})` : '—';
  el('detailVelocity').textContent = `${(r.velocity_mps ?? 0).toFixed(2)} m/s`;

  const hdeg = r.heading_rad != null ? `${(r.heading_rad * 180 / Math.PI).toFixed(1)}°` : '—';
  el('detailHeading').textContent  = hdeg;
  el('detailBattery').textContent  = `${r.battery_pct ?? 0}%`;
  el('detailOdometer').textContent = `${(r.odometer_meters ?? 0).toFixed(1)} m`;
  el('detailPayload').textContent  = `${r.payload_capacity_kg ?? 0} kg`;
  el('detailCycles').textContent   = r.cycles_completed ?? 0;
  el('detailIdle').textContent     = r.total_idle_ticks ?? 0;
  el('detailWaiting').textContent  = r.total_waiting_ticks ?? 0;

  // Current task
  const taskPanel = el('detailTaskPanel');
  if (r.current_task) {
    const t = r.current_task;
    taskPanel.innerHTML = `
      <div class="detail-row"><span class="detail-key">Task ID</span><span class="detail-val">${escHtml(t.id)}</span></div>
      <div class="detail-row"><span class="detail-key">Phase</span><span class="detail-val">${escHtml(r.task_phase || '—')}</span></div>
      <div class="detail-row"><span class="detail-key">Pickup</span><span class="detail-val">(${t.pickup_pos?.join(',') ?? '—'})</span></div>
      <div class="detail-row"><span class="detail-key">Dropoff</span><span class="detail-val">(${t.dropoff_pos?.join(',') ?? '—'})</span></div>
      <div class="detail-row"><span class="detail-key">Payload</span><span class="detail-val">${t.payload_weight_kg ?? '—'} kg</span></div>
      <div class="detail-row"><span class="detail-key">Priority</span><span class="detail-val">${t.priority ?? '—'}</span></div>
      <div class="detail-row"><span class="detail-key">Status</span><span class="detail-val">${escHtml(t.status ?? '—')}</span></div>
    `;
  } else {
    taskPanel.innerHTML = '<div class="empty-state">No active task</div>';
  }

  // §11.2 Space-time reservations
  const resList = el('reservationList');
  const ress = r.space_time_reservations || [];
  el('detailResCount').textContent = ress.length;
  resList.innerHTML = ress.length
    ? ress.map((res, i) => `
        <div class="reservation-item">
          <span class="res-tick">T+${i}</span>
          Cell (${res.cell?.join(',') ?? '?'})&nbsp;·&nbsp;ticks&nbsp;[${res.tick_from}→${res.tick_to}]
        </div>
      `).join('')
    : '<div class="empty-state">No active reservations</div>';

  // Maintenance
  const maintPanel = el('detailMaintPanel');
  const maint = r.maintenance || {};
  if (Object.keys(maint).length) {
    maintPanel.innerHTML = `
      <div class="detail-row"><span class="detail-key">Needs Attention</span>
        <span class="detail-val" style="color:${maint.needs_attention ? 'var(--red-light)' : 'var(--green-light)'}">
          ${maint.needs_attention ? '⚠ YES' : '✓ No'}</span></div>
      <div class="detail-row"><span class="detail-key">Anomaly Score</span>
        <span class="detail-val">${maint.anomaly_score != null ? maint.anomaly_score.toFixed(4) : '—'}</span></div>
      <div class="detail-row"><span class="detail-key">Predicted Failure</span>
        <span class="detail-val">${escHtml(maint.predicted_failure_type || 'normal')}</span></div>
      <div class="detail-row"><span class="detail-key">Est. Days to Failure</span>
        <span class="detail-val">${maint.estimated_days_to_failure ?? '—'}</span></div>
    `;
  } else {
    maintPanel.innerHTML = '<div class="empty-state">Collecting telemetry…</div>';
  }

  // Last decision — split into Edge AI Advisory + Safety Arbiter
  const decPanel = el('detailLastDecision');
  const ld = r.last_decision;
  if (ld) {
    decPanel.innerHTML = `
      ${ld.hybrid_note ? `
      <div class="arbiter-block">
        <div class="arbiter-header ai">
          <span>Edge AI — Advisory Only</span>
          <span style="margin-left:auto;font-weight:400;opacity:.8">Does not make final decisions</span>
        </div>
        <div class="arbiter-body">${escHtml(ld.hybrid_note)}</div>
      </div>` : ''}
      <div class="arbiter-block">
        <div class="arbiter-header safe">
          <span>Safety Arbiter — Final Authority</span>
          <span class="state-tag state-${ld.decision_type}" style="margin-left:auto">${ld.decision_type}</span>
        </div>
        <div class="arbiter-body">
          <div class="detail-row" style="padding:3px 0"><span class="detail-key">Reason Code</span>
            <span class="detail-val mono" style="font-size:10px">${escHtml(ld.reason_code || '—')}</span></div>
          <div class="detail-row" style="padding:3px 0"><span class="detail-key">Conflicting Peer</span>
            <span class="detail-val">${escHtml(ld.conflicting_peer_id || 'None')}</span></div>
          <div class="detail-row" style="padding:3px 0;border-bottom:none"><span class="detail-key">Conflict Cell</span>
            <span class="detail-val">${ld.conflict_pos ? `(${ld.conflict_pos.join(',')})` : 'None'}</span></div>
          <div style="margin-top:6px;font-size:11px;color:var(--text-secondary);line-height:1.5">${escHtml(ld.explanation || '')}</div>
        </div>
      </div>
    `;
  } else {
    decPanel.innerHTML = '<div class="empty-state">No decision recorded yet</div>';
  }

  // Coordination history for this robot (last 5 log entries)
  const histPanel = el('detailHistory');
  const robotLogs = logBuffer.filter(e => e.robot_id === r.id).slice(0, 5);
  histPanel.innerHTML = robotLogs.length
    ? robotLogs.map(e => `
        <div class="log-entry is-${(e.decision_type||'').toLowerCase()}" style="margin-bottom:3px">
          <span class="log-tick">T${e.tick}</span>
          <span class="log-etype ${e.decision_type}">${e.decision_type}</span>
          <div class="log-body">
            <div class="log-text">${escHtml(e.explanation || '—')}</div>
            <div class="log-code">${escHtml(e.reason_code || '')}</div>
          </div>
        </div>
      `).join('')
    : '<div class="empty-state">No coordination events for this robot yet</div>';
}

// ── VIEW 4: Coordination Log ───────────────────────────────────────
function setupLogControls() {
  el('logFilterRobot')?.addEventListener('change', e => { logFilterRobot = e.target.value; renderLog(); });
  el('logFilterType')?.addEventListener('change',  e => { logFilterType  = e.target.value; renderLog(); });
  el('btnClearLog')?.addEventListener('click', () => { logBuffer = []; renderLog(); });

  el('btnPauseLog')?.addEventListener('click', function() {
    logPaused = !logPaused;
    this.innerHTML = logPaused ? '▶ Resume' : '⏸ Pause';
    this.className = logPaused ? 'btn btn-sm btn-success' : 'btn btn-sm btn-secondary';
  });

  // Export log as JSON
  el('btnExportLog')?.addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(logBuffer, null, 2)], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `coordination-log-${new Date().toISOString().slice(0,19)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  });
}

function appendToLog(entries) {
  if (logPaused || !entries?.length) return;

  for (const entry of entries) {
    const key = `${entry.tick}-${entry.robot_id}-${entry.decision_type}`;
    if (!logBuffer.find(e => `${e.tick}-${e.robot_id}-${e.decision_type}` === key)) {
      logBuffer.unshift(entry);
      if (entry.decision_type) {
        logCounters[entry.decision_type] = (logCounters[entry.decision_type] || 0) + 1;
      }
    }
  }
  if (logBuffer.length > 300) logBuffer = logBuffer.slice(0, 300);

  // Update robot filter
  const sel    = el('logFilterRobot');
  const robots = [...new Set(logBuffer.map(e => e.robot_id))].sort();
  const prev   = sel?.value;
  if (sel) {
    sel.innerHTML = '<option value="all">All Robots</option>' +
      robots.map(r => `<option value="${r}">${r}</option>`).join('');
    if (prev) sel.value = prev;
  }

  renderLog();
  el('badgeLogCount').textContent = logBuffer.length;
}

function renderLog() {
  const stream = el('logStream');
  if (!stream) return;

  const entries = logBuffer.filter(e => {
    if (logFilterRobot !== 'all' && e.robot_id !== logFilterRobot) return false;
    if (logFilterType  !== 'all' && e.decision_type !== logFilterType) return false;
    return true;
  }).slice(0, 80);

  stream.innerHTML = entries.map(e => `
    <div class="log-entry is-${(e.decision_type||'').toLowerCase()}" role="listitem">
      <span class="log-tick">T${e.tick ?? '?'}</span>
      <span class="log-robot">${escHtml(e.robot_id || '—')}</span>
      <span class="log-etype ${e.decision_type}">${e.decision_type || '?'}</span>
      <div class="log-body">
        <div class="log-text">${escHtml(e.explanation || '—')}</div>
        ${e.hybrid_note ? `<div class="log-ai-note">AI: ${escHtml(e.hybrid_note)}</div>` : ''}
        <div class="log-code">${escHtml(e.reason_code || '')}</div>
      </div>
    </div>
  `).join('');
}

function updateDeadlockAlert(metrics) {
  const alert = el('deadlockAlert');
  if (!alert) return;
  const count = metrics.deadlock_count ?? 0;
  if (count > 0) {
    alert.style.display = 'block';
    el('deadlockDetail').textContent = `${count} deadlock event(s) detected — safety arbiter replanning affected robots.`;
  } else {
    alert.style.display = 'none';
  }
}

function updateLogStats(metrics) {
  setEl('statTotalConflicts', metrics.conflicts_detected  ?? 0);
  setEl('statYields',         logCounters.YIELD           ?? 0);
  setEl('statWaits',          logCounters.WAIT            ?? 0);
  setEl('statReroutesStat',   metrics.reroute_count       ?? 0);
  setEl('statAiDecisions',    metrics.ai_decisions        ?? 0);
  setEl('statMessages',       metrics.messages_sent       ?? 0);

  // Reason code breakdown
  const codes = {};
  for (const e of logBuffer) {
    if (e.reason_code) codes[e.reason_code] = (codes[e.reason_code] || 0) + 1;
  }
  const container = el('reasonCodeStats');
  if (container) {
    const top = Object.entries(codes).sort((a,b) => b[1]-a[1]).slice(0, 10);
    container.innerHTML = top.length
      ? top.map(([code, count]) => `
          <div class="log-stat">
            <span class="log-stat-label" style="font-size:10px">${escHtml(code.replace('RC_',''))}</span>
            <span class="log-stat-val">${count}</span>
          </div>
        `).join('')
      : '<div style="padding:12px;font-size:11px;color:var(--text-muted)">No events yet</div>';
  }
}

// ── VIEW 5: Performance ────────────────────────────────────────────
function setupPerformanceView() {
  el('btnRunBenchmark')?.addEventListener('click', async () => {
    el('bigImprovement').textContent = '…';
    const res  = await fetch('/api/simulation/benchmark', { method: 'POST' });
    const data = await res.json();
    applyBenchmarkResult(data);
  });
}

function applyBenchmarkResult(data) {
  const pct = data.improvement_pct;
  el('bigImprovement').textContent  = pct != null ? `+${pct.toFixed(1)}%` : '—';
  el('bigImprovement').style.color  = (pct != null && pct >= 20) ? 'var(--green-light)' : 'var(--amber-light)';
  el('benchBaseline').textContent   = data.baseline_ticks ?? '—';
  el('benchDSS').textContent        = data.decentralized_ticks ?? '—';
  el('benchCollisions').textContent = (data.total_collisions === 0) ? '0 ✓' : `⚠ ${data.total_collisions}`;
  el('benchCollisions').style.color = (data.total_collisions === 0) ? 'var(--green-light)' : 'var(--red-light)';
  el('benchImprove').textContent    = pct != null ? `+${pct.toFixed(1)}%` : '—';
  el('benchCriteria').textContent   = data.success_criteria_met ? '✓ PASSED' : '✗ Not met';
  el('benchCriteria').style.color   = data.success_criteria_met ? 'var(--green-light)' : 'var(--red-light)';
}

function updatePerformanceView(data) {
  const m = data.metrics || {};

  renderPerfGrid('perfSafetyGrid', [
    { label:'Collisions',      val: m.total_collisions ?? 0,         desc:'Must be 0 — ISO 3691-4',        color: (m.total_collisions===0) ? 'var(--green-light)' : 'var(--red-light)' },
    { label:'Near-Collisions', val: m.near_collision_count ?? 0,     desc:'Close proximity events' },
    { label:'Deadlocks',       val: m.deadlock_count ?? 0,           desc:'Mutual blocking events' },
  ]);

  renderPerfGrid('perfEffGrid', [
    { label:'Improvement',     val: m.efficiency_improvement_pct != null ? `+${m.efficiency_improvement_pct.toFixed(1)}%` : '—', desc:'vs. Naive baseline', color:'var(--green-light)' },
    { label:'Makespan',        val: m.makespan_ticks ?? 0,           desc:'Ticks since simulation start' },
    { label:'Avg Task Time',   val: m.average_task_completion_time  ? `${m.average_task_completion_time.toFixed(1)} ticks` : '—', desc:'Mean task duration' },
    { label:'Total Distance',  val: m.total_distance_meters         ? `${m.total_distance_meters.toFixed(0)} m` : '—',           desc:'Fleet odometer total' },
    { label:'Idle Ticks',      val: m.total_idle_ticks ?? 0,        desc:'Fleet-wide idle accumulation' },
    { label:'Waiting Ticks',   val: m.total_waiting_ticks ?? 0,     desc:'Fleet-wide waiting accumulation' },
    { label:'Tasks Completed', val: m.tasks_completed ?? 0,         desc:'Successful deliveries' },
  ]);

  renderPerfGrid('perfCoordGrid', [
    { label:'Conflicts Detected', val: m.conflicts_detected ?? 0,   desc:'Intent path conflicts found' },
    { label:'Conflicts Resolved', val: m.conflicts_resolved ?? 0,   desc:'Cleared by arbiter' },
    { label:'Reroutes',           val: m.reroute_count ?? 0,        desc:'Dynamic A* reroutes' },
    { label:'P2P Messages',       val: m.messages_sent ?? 0,        desc:'State/intent broadcasts' },
  ]);

  renderPerfGrid('perfAiGrid', [
    { label:'AI Decisions',   val: m.ai_decisions ?? 0,  desc:'Priority weight adjustments' },
    { label:'AI Agreements',  val: m.ai_agreements ?? 0, desc:'Matched arbiter final decision' },
  ]);

  // Update big improvement
  if (m.efficiency_improvement_pct != null) {
    el('bigImprovement').textContent = `+${m.efficiency_improvement_pct.toFixed(1)}%`;
    el('bigImprovement').style.color = m.efficiency_improvement_pct >= 20
      ? 'var(--green-light)' : 'var(--amber-light)';
  }
}

function renderPerfGrid(gridId, items) {
  const grid = el(gridId);
  if (!grid) return;
  grid.innerHTML = items.map(item => `
    <div class="perf-kpi">
      <div class="perf-kpi-label">${item.label}</div>
      <div class="perf-kpi-val" style="${item.color ? `color:${item.color}` : ''}">${item.val}</div>
      <div class="perf-kpi-desc">${item.desc}</div>
    </div>
  `).join('');
}

// ── Scenario Grid ──────────────────────────────────────────────────
function buildScenarioGrid() {
  const grid = el('scenarioGrid');
  if (!grid) return;
  grid.innerHTML = SCENARIOS.map(s => `
    <button class="scenario-btn" id="scen-${s.id}" data-scenario="${s.id}">
      <span class="scenario-id">${s.id}</span>
      <span class="scenario-name">${s.name}</span>
      <span class="scenario-desc">${s.desc}</span>
    </button>
  `).join('');

  grid.querySelectorAll('.scenario-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const sid  = btn.dataset.scenario;
      const seed = parseInt(el('scenarioSeed')?.value) || 42;
      btn.classList.add('running');
      const res  = await fetch('/api/scenarios/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario_id: sid, seed }),
      });
      const data = await res.json();
      btn.classList.remove('running');
      showScenarioResult(data);
    });
  });

  el('btnClearScenario')?.addEventListener('click', async () => {
    await fetch('/api/scenarios/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario_id: 'S1', seed: 42 }),
    });
    el('scenarioResult').style.display = 'none';
  });
}

function showScenarioResult(data) {
  el('scenResultId').textContent   = data.scenario || '—';
  el('scenResultDesc').textContent = data.description || data.error || '';
  el('scenarioResult').style.display = 'block';
}

// ── Modals ─────────────────────────────────────────────────────────
function setupTaskModal() {
  el('btnCloseModal')?.addEventListener('click',  () => closeModal('taskModal'));
  el('btnCancelModal')?.addEventListener('click', () => closeModal('taskModal'));
  el('taskModal')?.addEventListener('click', e => { if(e.target === el('taskModal')) closeModal('taskModal'); });

  document.querySelectorAll('.btn-preset').forEach(btn => {
    btn.addEventListener('click', () => {
      el('pickupX').value        = btn.dataset.px;
      el('pickupY').value        = btn.dataset.py;
      el('dropoffX').value       = btn.dataset.dx;
      el('dropoffY').value       = btn.dataset.dy;
      el('payloadKg').value      = btn.dataset.w;
      el('priorityLevel').value  = btn.dataset.prio;
    });
  });

  el('taskForm')?.addEventListener('submit', async e => {
    e.preventDefault();
    await fetch('/api/tasks/submit', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pickup_x:          parseInt(el('pickupX').value),
        pickup_y:          parseInt(el('pickupY').value),
        dropoff_x:         parseInt(el('dropoffX').value),
        dropoff_y:         parseInt(el('dropoffY').value),
        payload_weight_kg: parseFloat(el('payloadKg').value),
        priority:          parseInt(el('priorityLevel').value),
      }),
    });
    closeModal('taskModal');
  });
}

function setupHelpModal() {
  el('btnCloseHelp')?.addEventListener('click', () => closeModal('helpModal'));
  el('btnGotIt')?.addEventListener('click',     () => closeModal('helpModal'));
  el('helpModal')?.addEventListener('click', e => { if(e.target === el('helpModal')) closeModal('helpModal'); });
}

function openModal(id)  { const m = el(id); if(m) m.style.display = 'flex'; }
function closeModal(id) { const m = el(id); if(m) m.style.display = 'none'; }

// ── Utilities ──────────────────────────────────────────────────────
function el(id)         { return document.getElementById(id); }
function setEl(id, val) { const e = el(id); if(e) e.textContent = val; }

/** Escape HTML special characters to prevent XSS */
function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}
