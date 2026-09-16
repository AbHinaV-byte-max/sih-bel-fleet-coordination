/**
 * Autonomous Fleet Hub — Main Controller & WebSocket Client v5.0
 * SIH 26123 — Bharat Electronics Limited (BEL)
 *
 * Drives all 5 dashboard views:
 *   1. Fleet Overview   — live AMR cards
 *   2. Warehouse Map    — 2D tactical canvas
 *   3. Robot Detail     — deep telemetry inspector
 *   4. Coordination Log — §11.1 P2P decision audit trail
 *   5. Performance      — §18 metrics + S1–S10 scenarios
 */

// ── State ────────────────────────────────────────────────────────
let ws                   = null;
let canvas               = null;
let trendChart           = null;
let lastSnapshot         = null;
let isSimRunning         = true;
let selectedRobotId      = null;
let logPaused            = false;
let logFilterRobot       = 'all';
let logFilterType        = 'all';
let logBuffer            = [];           // rolling log entries
let scenarioResultVisible = false;

// §18.3 counters derived from log buffer
const logCounters = { YIELD: 0, WAIT: 0, REROUTE: 0, CONTINUE: 0 };

// Scenario definitions for the launcher UI
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

// ── Init ─────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  canvas     = new WarehouseCanvas('warehouseCanvas');
  trendChart = new TrendChart('trendChartCanvas');

  canvas.onRobotClick = (id) => selectRobot(id);
  canvas.onCellClick  = (gx, gy) => {
    // Toggle dynamic obstacle on Map view cell click
    if (currentView() === 'view-map') {
      document.getElementById('obsX').value = gx;
      document.getElementById('obsY').value = gy;
    }
  };

  setupViewNav();
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

// ── View Navigation ───────────────────────────────────────────────
function setupViewNav() {
  document.querySelectorAll('.view-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.dataset.view;
      document.querySelectorAll('.view-tab').forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected','false');
      });
      document.querySelectorAll('.view-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      btn.setAttribute('aria-selected','true');
      document.getElementById(target)?.classList.add('active');
    });
  });
}

function navigateTo(viewId) {
  document.querySelectorAll('.view-tab').forEach(t => {
    t.classList.remove('active');
    t.setAttribute('aria-selected','false');
    if (t.dataset.view === viewId) {
      t.classList.add('active');
      t.setAttribute('aria-selected','true');
    }
  });
  document.querySelectorAll('.view-pane').forEach(p => {
    p.classList.toggle('active', p.id === viewId);
  });
}

// ── Header Controls ───────────────────────────────────────────────
function setupHeaderControls() {
  const btnToggle    = document.getElementById('btnToggleSim');
  const btnStep      = document.getElementById('btnStep');
  const btnBenchmark = document.getElementById('btnBenchmark');
  const btnHelp      = document.getElementById('btnHelp');
  const btnNewTask   = document.getElementById('btnNewTask');

  btnToggle?.addEventListener('click', async () => {
    if (isSimRunning) {
      await fetch('/api/simulation/pause', { method:'POST' });
      isSimRunning = false;
      btnToggle.innerHTML = '<span class="btn-icon">▶</span> Resume';
      btnToggle.className = 'btn btn-success';
    } else {
      await fetch('/api/simulation/start', { method:'POST' });
      isSimRunning = true;
      btnToggle.innerHTML = '<span class="btn-icon">⏸</span> Pause';
      btnToggle.className = 'btn btn-warning';
    }
  });

  btnStep?.addEventListener('click', async () => {
    await fetch('/api/simulation/step', { method:'POST' });
  });

  btnBenchmark?.addEventListener('click', async () => {
    const res  = await fetch('/api/simulation/benchmark', { method:'POST' });
    const data = await res.json();
    applyBenchmarkResult(data);
    navigateTo('view-perf');
  });

  btnHelp?.addEventListener('click', () => {
    document.getElementById('helpModal').style.display = 'flex';
  });

  btnNewTask?.addEventListener('click', () => {
    document.getElementById('taskModal').style.display = 'flex';
  });
}

// ── WebSocket ─────────────────────────────────────────────────────
function initWebSocket() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/fleet-stream`);

  ws.onopen    = () => setConnected(true);
  ws.onclose   = () => {
    setConnected(false);
    setTimeout(initWebSocket, 3000);
  };
  ws.onerror   = () => setConnected(false);
  ws.onmessage = (evt) => {
    try {
      const data = JSON.parse(evt.data);
      lastSnapshot = data;
      updateDashboard(data);
    } catch(e) { console.warn('WS parse error', e); }
  };
}

function setConnected(ok) {
  const pill = document.getElementById('connectionPill');
  const dot  = document.getElementById('connDot');
  const text = document.getElementById('connStatus');
  if (ok) {
    pill.className = 'connection-indicator';
    dot.className  = 'indicator-dot';
    text.textContent = 'P2P Mesh Live';
  } else {
    pill.className = 'connection-indicator disconnected';
    dot.className  = 'indicator-dot red';
    text.textContent = 'Reconnecting…';
  }
}

async function fetchInitialState() {
  try {
    const res = await fetch('/api/fleet/status');
    if (res.ok) updateDashboard(await res.json());
  } catch(e) { /* WS will stream */ }
}

// ── Master Update ─────────────────────────────────────────────────
function updateDashboard(data) {
  if (!data) return;

  // Canvas
  canvas.updateSnapshot(data);
  if (data.congestion_heatmap) canvas.updateHeatmap(data.congestion_heatmap);

  // KPI strip
  updateKPIStrip(data);

  // View 1: Fleet Overview
  updateFleetView(data);

  // View 2: Map conflict stats
  updateMapStats(data);

  // View 3: Robot Detail (if one is selected)
  if (selectedRobotId && data.robots && data.robots[selectedRobotId]) {
    updateRobotDetail(data.robots[selectedRobotId]);
  }

  // View 4: Coordination Log
  appendToLog(data.recent_decision_logs || []);
  updateLogStats(data.metrics || {});

  // View 5: Performance
  updatePerformanceView(data);

  // Trend chart
  if (data.metrics && data.metrics.trend_history) {
    trendChart.update(data.metrics.trend_history);
  }
}

// ── KPI Strip ─────────────────────────────────────────────────────
function updateKPIStrip(data) {
  const m = data.metrics || {};

  // Collisions
  el('valCollisions').textContent   = m.total_collisions ?? 0;
  const safe = m.total_collisions === 0;
  el('tagSafety').textContent       = safe ? 'STRICT 0 ✓' : 'COLLISION!';
  el('tagSafety').className         = `kpi-tag ${safe ? 'tag-emerald' : 'tag-rose'}`;

  // Efficiency
  const pct = m.efficiency_improvement_pct;
  el('valImprovement').textContent = pct != null ? `+${pct.toFixed(1)}%` : '—';

  // Robots
  const robots = data.robots ? Object.values(data.robots) : [];
  const active = robots.filter(r => r.state !== 'IDLE' && r.state !== 'FAILED').length;
  el('valActiveRobots').textContent = `${active} / ${robots.length}`;
  el('badgeFleetCount').textContent = robots.length;

  // Tasks
  const tasksDone = m.tasks_completed ?? 0;
  el('valTasksDone').textContent = tasksDone;

  // Health KPI tag
  const hasFault = robots.some(r => r.state === 'FAILED' || r.state === 'DEGRADED');
  el('tagHealthKpi').textContent = hasFault ? 'FAULT DETECTED' : '100% OPERATIONAL';
  el('tagHealthKpi').className   = `kpi-tag ${hasFault ? 'tag-rose' : 'tag-amber'}`;
}

// ── View 1: Fleet Overview ────────────────────────────────────────
function updateFleetView(data) {
  const robots = data.robots ? Object.values(data.robots) : [];
  const grid   = el('fleetGrid');
  if (!grid) return;

  // Build or update AMR cards
  for (const robot of robots) {
    let card = document.getElementById(`amr-card-${robot.id}`);
    if (!card) {
      card = document.createElement('div');
      card.id        = `amr-card-${robot.id}`;
      card.className = 'amr-card';
      card.addEventListener('click', () => {
        selectRobot(robot.id);
        navigateTo('view-detail');
      });
      grid.appendChild(card);
    }
    card.classList.toggle('selected', robot.id === selectedRobotId);

    const battPct  = robot.battery_pct ?? 100;
    const battCls  = battPct > 50 ? 'high' : battPct > 25 ? 'medium' : 'low';
    const stateClr = stateColorVar(robot.state);

    card.style.setProperty('--state-color', stateClr);
    card.innerHTML = `
      <div class="amr-top">
        <span class="amr-id">${robot.id}</span>
        <div style="display:flex;gap:6px;align-items:center">
          <span class="comm-badge ${robot.comm_status || 'HEALTHY'}">${robot.comm_status || 'HEALTHY'}</span>
          <span class="amr-state-tag ${robot.state}">${robot.state}</span>
        </div>
      </div>
      <div class="amr-type-badge">${robot.type || '—'}</div>
      <div class="amr-metrics">
        <div class="amr-metric">
          <span class="amr-metric-label">Battery</span>
          <span class="amr-metric-val">${battPct}%</span>
        </div>
        <div class="amr-metric">
          <span class="amr-metric-label">Velocity</span>
          <span class="amr-metric-val">${(robot.velocity_mps ?? 0).toFixed(1)} m/s</span>
        </div>
        <div class="amr-metric">
          <span class="amr-metric-label">Odometer</span>
          <span class="amr-metric-val">${(robot.odometer_meters ?? 0).toFixed(0)}m</span>
        </div>
      </div>
      <div class="battery-bar-wrap">
        <div class="battery-bar-bg">
          <div class="battery-bar-fill ${battCls}" style="width:${battPct}%"></div>
        </div>
      </div>
      <div class="amr-task-line">
        ${robot.current_task_id
          ? `📦 <strong>${robot.current_task_id}</strong> — ${robot.task_phase || 'NONE'}`
          : '<span style="color:var(--text-muted)">Idle — awaiting task</span>'}
      </div>
      <div class="amr-reason">${robot.state_reason || '—'}</div>
    `;
  }

  // Task table
  updateTaskTable(data.tasks || []);

  // Populate robot selector in detail view
  updateRobotSelector(robots);
}

function updateTaskTable(tasks) {
  const tbody = el('taskTableBody');
  if (!tbody) return;
  if (!tasks.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-state">No tasks yet</td></tr>`;
    return;
  }
  tbody.innerHTML = tasks.map(t => {
    const prioClass = `p${t.priority || 1}`;
    return `
      <tr>
        <td class="task-id">${t.id}</td>
        <td>(${t.pickup_pos?.join(',') ?? '—'})</td>
        <td>(${t.dropoff_pos?.join(',') ?? '—'})</td>
        <td>${t.payload_weight_kg ?? '—'} kg</td>
        <td><span class="prio-chip ${prioClass}">${t.priority ?? '—'}</span></td>
        <td>${t.assigned_robot_id ?? '<span style="color:var(--text-muted)">Unassigned</span>'}</td>
        <td><span class="status-chip ${t.status}">${t.status ?? '—'}</span></td>
      </tr>
    `;
  }).join('');
  el('tabTaskCount') && (el('tabTaskCount').textContent = tasks.length);
}

function updateRobotSelector(robots) {
  const sel = el('robotSelector');
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = '<option value="">— Select AMR —</option>' +
    robots.map(r => `<option value="${r.id}" ${r.id===selectedRobotId?'selected':''}>${r.id} (${r.state})</option>`).join('');
  if (prev) sel.value = prev;
  sel.onchange = () => selectRobot(sel.value);
}

// ── View 2: Map ───────────────────────────────────────────────────
function updateMapStats(data) {
  const m = data.metrics || {};
  setEl('statConflictsDetected', m.conflicts_detected ?? 0);
  setEl('statConflictsResolved', m.conflicts_resolved ?? 0);
  setEl('statReroutes',          m.reroute_count ?? 0);
  setEl('statDeadlocks',         m.deadlock_count ?? 0);
}

function setupMapControls() {
  el('btnZoomIn')?.addEventListener('click',    () => canvas.zoomIn());
  el('btnZoomOut')?.addEventListener('click',   () => canvas.zoomOut());
  el('btnResetView')?.addEventListener('click', () => canvas.resetView());

  // Layer toggles
  document.querySelectorAll('.layer-toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const layer = btn.dataset.layer;
      btn.classList.toggle('active');
      canvas.setLayer(layer, btn.classList.contains('active'));
    });
  });

  // Dynamic obstacle API
  el('btnAddObstacle')?.addEventListener('click', async () => {
    const x = parseInt(el('obsX').value);
    const y = parseInt(el('obsY').value);
    await fetch('/api/obstacles/dynamic', {
      method: 'POST',
      headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({ x, y, action: 'add' }),
    });
  });
  el('btnRemoveObstacle')?.addEventListener('click', async () => {
    const x = parseInt(el('obsX').value);
    const y = parseInt(el('obsY').value);
    await fetch('/api/obstacles/dynamic', {
      method: 'POST',
      headers: { 'Content-Type':'application/json' },
      body: JSON.stringify({ x, y, action: 'remove' }),
    });
  });

  // Sync dynamic obstacle list from snapshots
  setInterval(() => {
    if (!lastSnapshot?.warehouse?.dynamic_obstacles) return;
    const list = lastSnapshot.warehouse.dynamic_obstacles;
    el('dynamicObstacleList').textContent = list.length
      ? list.map(o => `(${o[0]},${o[1]})`).join('  ')
      : 'No dynamic obstacles';
  }, 500);
}

// ── View 3: Robot Detail ──────────────────────────────────────────
function selectRobot(id) {
  selectedRobotId = id;
  canvas.setSelectedRobot(id);
  el('robotSelector') && (el('robotSelector').value = id);

  // Update all AMR cards selection state
  document.querySelectorAll('.amr-card').forEach(c => {
    c.classList.toggle('selected', c.id === `amr-card-${id}`);
  });

  if (!id) {
    el('detailNoSelection').style.display = 'block';
    el('detailPanels').style.display      = 'none';
    return;
  }
  el('detailNoSelection').style.display = 'none';
  el('detailPanels').style.display      = 'block';

  if (lastSnapshot?.robots?.[id]) {
    updateRobotDetail(lastSnapshot.robots[id]);
  }
}

function updateRobotDetail(r) {
  if (!r) return;

  el('detailRobotId').textContent = r.id || '—';

  const stTag = el('detailState');
  stTag.textContent = r.state || '—';
  stTag.className   = `amr-state-tag ${r.state}`;

  const commBadge = el('detailComm');
  commBadge.textContent = r.comm_status || 'HEALTHY';
  commBadge.className   = `comm-badge ${r.comm_status || 'HEALTHY'}`;

  el('detailReason').textContent    = r.state_reason || 'No state reason available.';
  el('detailType').textContent      = r.type          || '—';
  el('detailPos').textContent       = r.position ? `(${r.position.join(', ')})` : '—';
  el('detailVelocity').textContent  = `${(r.velocity_mps ?? 0).toFixed(2)} m/s`;

  // Heading in degrees
  const headingDeg = r.heading_rad != null
    ? `${(r.heading_rad * 180 / Math.PI).toFixed(1)}° (${r.heading_rad.toFixed(3)} rad)`
    : '—';
  el('detailHeading').textContent   = headingDeg;
  el('detailBattery').textContent   = `${r.battery_pct ?? 0}%`;
  el('detailOdometer').textContent  = `${(r.odometer_meters ?? 0).toFixed(1)} m`;
  el('detailPayload').textContent   = `${r.payload_capacity_kg ?? 0} kg`;
  el('detailCycles').textContent    = r.cycles_completed ?? 0;
  el('detailIdle').textContent      = r.total_idle_ticks ?? 0;
  el('detailWaiting').textContent   = r.total_waiting_ticks ?? 0;

  // Current task
  const taskPanel = el('detailTaskPanel');
  if (r.current_task) {
    const t = r.current_task;
    taskPanel.innerHTML = `
      <div class="detail-row"><span class="detail-key">Task ID</span><span class="detail-val">${t.id}</span></div>
      <div class="detail-row"><span class="detail-key">Phase</span><span class="detail-val">${r.task_phase}</span></div>
      <div class="detail-row"><span class="detail-key">Pickup</span><span class="detail-val">(${t.pickup_pos?.join(',')})</span></div>
      <div class="detail-row"><span class="detail-key">Dropoff</span><span class="detail-val">(${t.dropoff_pos?.join(',')})</span></div>
      <div class="detail-row"><span class="detail-key">Payload</span><span class="detail-val">${t.payload_weight_kg} kg</span></div>
      <div class="detail-row"><span class="detail-key">Priority</span><span class="detail-val">${t.priority}</span></div>
      <div class="detail-row"><span class="detail-key">Status</span><span class="detail-val">${t.status}</span></div>
    `;
  } else {
    taskPanel.innerHTML = '<div class="empty-state">No active task</div>';
  }

  // §11.2 Space-time reservations
  const resList = el('reservationList');
  const ress    = r.space_time_reservations || [];
  el('detailResCount').textContent = ress.length;
  if (ress.length) {
    resList.innerHTML = ress.map((res, i) =>
      `<div class="reservation-item">
         <span class="res-icon">◆</span>
         T+${i}: cell (${res.cell?.join(',')}) &nbsp;|&nbsp; tick [${res.tick_from}→${res.tick_to}]
       </div>`
    ).join('');
  } else {
    resList.innerHTML = '<div class="empty-state">No active reservations</div>';
  }

  // Maintenance
  const maintPanel = el('detailMaintPanel');
  const maint      = r.maintenance || {};
  if (Object.keys(maint).length) {
    maintPanel.innerHTML = `
      <div class="detail-row"><span class="detail-key">Needs Attention</span><span class="detail-val" style="color:${maint.needs_attention ? 'var(--hazard)' : 'var(--emerald)'}">${maint.needs_attention ? '⚠ YES' : '✓ No'}</span></div>
      <div class="detail-row"><span class="detail-key">Anomaly Score</span><span class="detail-val">${maint.anomaly_score != null ? maint.anomaly_score.toFixed(4) : '—'}</span></div>
      <div class="detail-row"><span class="detail-key">Predicted Failure</span><span class="detail-val">${maint.predicted_failure_type || 'normal'}</span></div>
      <div class="detail-row"><span class="detail-key">Days to Failure</span><span class="detail-val">${maint.estimated_days_to_failure != null ? maint.estimated_days_to_failure : '—'}</span></div>
    `;
  } else {
    maintPanel.innerHTML = '<div class="empty-state">Collecting telemetry…</div>';
  }

  // Last decision
  const decPanel = el('detailLastDecision');
  const ld       = r.last_decision;
  if (ld) {
    decPanel.innerHTML = `
      <div class="detail-row"><span class="detail-key">Type</span><span class="detail-val log-type ${ld.decision_type}">${ld.decision_type}</span></div>
      <div class="detail-row"><span class="detail-key">Reason Code</span><span class="detail-val mono" style="font-size:10.5px">${ld.reason_code}</span></div>
      <div class="detail-row"><span class="detail-key">Conflicting Peer</span><span class="detail-val">${ld.conflicting_peer_id || 'None'}</span></div>
      <div class="detail-row"><span class="detail-key">Conflict Cell</span><span class="detail-val">${ld.conflict_pos ? `(${ld.conflict_pos.join(',')})` : 'None'}</span></div>
      <div style="margin-top:8px;font-size:11.5px;color:var(--text-secondary);font-style:italic;line-height:1.5">${ld.explanation || ''}</div>
      ${ld.hybrid_note ? `<div style="margin-top:6px;font-size:10.5px;color:var(--purple);font-style:italic">🤖 AI Advisory: ${ld.hybrid_note}</div>` : ''}
    `;
  } else {
    decPanel.innerHTML = '<div class="empty-state">No decision recorded</div>';
  }
}

// ── View 4: Coordination Log ──────────────────────────────────────
function setupLogControls() {
  el('logFilterRobot')?.addEventListener('change', e => { logFilterRobot = e.target.value; renderLog(); });
  el('logFilterType')?.addEventListener('change',  e => { logFilterType  = e.target.value; renderLog(); });
  el('btnClearLog')?.addEventListener('click',     ()  => { logBuffer = []; renderLog(); });
  el('btnPauseLog')?.addEventListener('click',     function() {
    logPaused = !logPaused;
    this.innerHTML = logPaused ? '▶ Resume' : '⏸ Pause';
    this.className = logPaused ? 'btn btn-sm btn-success' : 'btn btn-sm btn-secondary';
  });
}

function appendToLog(entries) {
  if (logPaused || !entries?.length) return;
  for (const entry of entries) {
    // Avoid duplicates by tick+robot
    const key = `${entry.tick}-${entry.robot_id}-${entry.decision_type}`;
    if (!logBuffer.find(e => `${e.tick}-${e.robot_id}-${e.decision_type}` === key)) {
      logBuffer.unshift(entry);
      logCounters[entry.decision_type] = (logCounters[entry.decision_type] || 0) + 1;
    }
  }
  if (logBuffer.length > 200) logBuffer = logBuffer.slice(0, 200);

  // Update robot filter options
  const sel    = el('logFilterRobot');
  const robots = [...new Set(logBuffer.map(e => e.robot_id))];
  const prev   = sel?.value;
  if (sel) {
    sel.innerHTML = '<option value="all">All Robots</option>' +
      robots.map(r => `<option value="${r}">${r}</option>`).join('');
    if (prev) sel.value = prev;
  }

  renderLog();
}

function renderLog() {
  const stream  = el('logStream');
  if (!stream)  return;
  const entries = logBuffer.filter(e => {
    if (logFilterRobot !== 'all' && e.robot_id !== logFilterRobot) return false;
    if (logFilterType  !== 'all' && e.decision_type !== logFilterType) return false;
    return true;
  });

  stream.innerHTML = entries.slice(0,60).map(e => `
    <div class="log-entry ${e.decision_type}" role="listitem">
      <span class="log-tick">T${e.tick}</span>
      <span class="log-robot">${e.robot_id}</span>
      <span class="log-type ${e.decision_type}">${e.decision_type}</span>
      <div class="log-text">
        <div>${e.explanation || '—'}</div>
        ${e.hybrid_note ? `<div class="log-hybrid">🤖 ${e.hybrid_note}</div>` : ''}
        <div style="font-size:9.5px;color:var(--text-muted);margin-top:2px;font-family:var(--font-mono)">${e.reason_code || ''}</div>
      </div>
    </div>
  `).join('');

  el('badgeLogCount').textContent = logBuffer.length;
}

function updateLogStats(metrics) {
  setEl('statTotalConflicts',  metrics.conflicts_detected  ?? 0);
  setEl('statYields',          logCounters.YIELD           ?? 0);
  setEl('statWaits',           logCounters.WAIT            ?? 0);
  setEl('statReroutesStat',    metrics.reroute_count       ?? 0);
  setEl('statAiDecisions',     metrics.ai_decisions        ?? 0);
  setEl('statMessages',        metrics.messages_sent       ?? 0);

  // Reason code breakdown (from log buffer)
  const codes = {};
  for (const e of logBuffer) {
    if (e.reason_code) codes[e.reason_code] = (codes[e.reason_code]||0)+1;
  }
  const container = el('reasonCodeStats');
  if (container) {
    const top = Object.entries(codes).sort((a,b)=>b[1]-a[1]).slice(0,8);
    container.innerHTML = top.length
      ? top.map(([code, count]) => `
          <div class="log-stat">
            <span class="log-stat-label" style="font-size:10px">${code.replace('RC_','')}</span>
            <span class="log-stat-val">${count}</span>
          </div>
        `).join('')
      : '<div class="empty-state">No data yet</div>';
  }
}

// ── View 5: Performance ───────────────────────────────────────────
function setupPerformanceView() {
  el('btnRunBenchmark')?.addEventListener('click', async () => {
    el('bigImprovement').textContent = '…';
    const res  = await fetch('/api/simulation/benchmark', { method:'POST' });
    const data = await res.json();
    applyBenchmarkResult(data);
  });
}

function applyBenchmarkResult(data) {
  const pct = data.improvement_pct;
  el('bigImprovement').textContent   = pct != null ? `+${pct.toFixed(1)}%` : '—';
  el('bigImprovement').style.color   = (pct >= 20) ? 'var(--emerald)' : 'var(--hazard)';
  el('benchBaseline').textContent    = data.baseline_ticks ?? '—';
  el('benchDSS').textContent         = data.decentralized_ticks ?? '—';
  el('benchCollisions').textContent  = (data.total_collisions===0) ? '0 ✓' : `⚠ ${data.total_collisions}`;
  el('benchCollisions').style.color  = (data.total_collisions===0) ? 'var(--emerald)' : 'var(--hazard)';
  el('benchImprove').textContent     = pct != null ? `+${pct.toFixed(1)}%` : '—';
  el('benchCriteria').textContent    = data.success_criteria_met ? '✓ PASSED' : '✗ Not met';
  el('benchCriteria').style.color    = data.success_criteria_met ? 'var(--emerald)' : 'var(--hazard)';
}

function updatePerformanceView(data) {
  const m = data.metrics || {};

  // Safety KPIs
  renderPerfGrid('perfSafetyGrid', [
    { label:'Collisions',      val: m.total_collisions ?? 0,         desc:'Must be 0',           color:'var(--emerald)' },
    { label:'Near-Collisions', val: m.near_collision_count ?? 0,     desc:'Close proximity events' },
    { label:'Deadlocks',       val: m.deadlock_count ?? 0,           desc:'Mutual blocking events' },
  ]);

  // Efficiency KPIs
  renderPerfGrid('perfEffGrid', [
    { label:'Improvement',       val: m.efficiency_improvement_pct != null ? `+${m.efficiency_improvement_pct.toFixed(1)}%` : '—', desc:'vs. Naive baseline', color:'var(--emerald)' },
    { label:'Makespan',          val: m.makespan_ticks ?? 0,          desc:'Total ticks since start' },
    { label:'Avg Task Time',     val: m.average_task_completion_time ? `${m.average_task_completion_time.toFixed(1)} ticks` : '—', desc:'Mean task duration' },
    { label:'Total Distance',    val: m.total_distance_meters ? `${m.total_distance_meters.toFixed(0)}m` : '—', desc:'Fleet odometer sum' },
    { label:'Idle Ticks',        val: m.total_idle_ticks ?? 0,        desc:'Fleet-wide idle sum' },
    { label:'Waiting Ticks',     val: m.total_waiting_ticks ?? 0,     desc:'Fleet-wide waiting sum' },
    { label:'Tasks Completed',   val: m.tasks_completed ?? 0,         desc:'Successful deliveries' },
  ]);

  // Coordination KPIs
  renderPerfGrid('perfCoordGrid', [
    { label:'Conflicts Detected',  val: m.conflicts_detected ?? 0,  desc:'Intent path conflicts' },
    { label:'Conflicts Resolved',  val: m.conflicts_resolved ?? 0,  desc:'Successfully cleared' },
    { label:'Reroutes',            val: m.reroute_count ?? 0,        desc:'Dynamic A* reroutes' },
    { label:'P2P Messages',        val: m.messages_sent ?? 0,        desc:'Fleet broadcasts' },
  ]);

  // AI KPIs
  renderPerfGrid('perfAiGrid', [
    { label:'AI Decisions',   val: m.ai_decisions ?? 0,  desc:'Hybrid priority boosts' },
    { label:'AI Agreements',  val: m.ai_agreements ?? 0, desc:'Boost matched final decision' },
  ]);

  // Big improvement number
  if (m.efficiency_improvement_pct != null) {
    el('bigImprovement').textContent = `+${m.efficiency_improvement_pct.toFixed(1)}%`;
    el('bigImprovement').style.color = m.efficiency_improvement_pct >= 20
      ? 'var(--emerald)' : 'var(--hazard)';
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

// ── Scenario Grid ─────────────────────────────────────────────────
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
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ scenario_id: sid, seed }),
      });
      const data = await res.json();
      btn.classList.remove('running');
      showScenarioResult(data);
    });
  });

  el('btnClearScenario')?.addEventListener('click', async () => {
    // Reset to S1 (normal traffic)
    await fetch('/api/scenarios/run', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ scenario_id: 'S1', seed: 42 }),
    });
    el('scenarioResult').style.display = 'none';
  });
}

function showScenarioResult(data) {
  const box = el('scenarioResult');
  el('scenResultId').textContent   = data.scenario || '—';
  el('scenResultDesc').textContent = data.description || data.error || '';
  box.style.display = 'block';
}

// ── Task Modal ────────────────────────────────────────────────────
function setupTaskModal() {
  el('btnCloseModal')?.addEventListener('click',  () => closeModal('taskModal'));
  el('btnCancelModal')?.addEventListener('click', () => closeModal('taskModal'));
  el('taskModal')?.addEventListener('click', e => { if (e.target === el('taskModal')) closeModal('taskModal'); });

  // Quick presets
  document.querySelectorAll('.btn-preset').forEach(btn => {
    btn.addEventListener('click', () => {
      el('pickupX').value   = btn.dataset.px;
      el('pickupY').value   = btn.dataset.py;
      el('dropoffX').value  = btn.dataset.dx;
      el('dropoffY').value  = btn.dataset.dy;
      el('payloadKg').value = btn.dataset.w;
      el('priorityLevel').value = btn.dataset.prio;
    });
  });

  el('taskForm')?.addEventListener('submit', async e => {
    e.preventDefault();
    await fetch('/api/tasks/submit', {
      method:  'POST',
      headers: {'Content-Type':'application/json'},
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

// ── Help Modal ────────────────────────────────────────────────────
function setupHelpModal() {
  el('btnCloseHelp')?.addEventListener('click', () => closeModal('helpModal'));
  el('btnGotIt')?.addEventListener('click',     () => closeModal('helpModal'));
  el('helpModal')?.addEventListener('click', e => { if (e.target === el('helpModal')) closeModal('helpModal'); });
}

function closeModal(id) {
  el(id).style.display = 'none';
}

// ── Utilities ─────────────────────────────────────────────────────
function el(id)           { return document.getElementById(id); }
function setEl(id, val)   { const e = el(id); if (e) e.textContent = val; }

function stateColorVar(state) {
  const map = {
    IDLE:      'rgba(100,116,139,0.9)',
    ASSIGNED:  'rgba(168,85,247,0.9)',
    PLANNING:  'rgba(168,85,247,0.9)',
    MOVING:    'rgba(56,189,248,0.9)',
    WAITING:   'rgba(245,158,11,0.9)',
    YIELDING:  'rgba(249,115,22,0.9)',
    REROUTING: 'rgba(244,63,94,0.9)',
    CHARGING:  'rgba(16,185,129,0.9)',
    DEGRADED:  'rgba(244,63,94,0.75)',
    FAILED:    'rgba(239,68,68,0.9)',
    COMPLETED: 'rgba(16,185,129,0.9)',
  };
  return map[state] || 'rgba(148,163,184,0.9)';
}
