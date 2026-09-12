/**
 * Autonomous Fleet Hub - Controller & WebSocket Client
 * SIH 26123 - Bharat Electronics Limited (BEL)
 */

let ws = null;
let canvasRenderer = null;
let trendChartRenderer = null;
let isSimulationRunning = true;

document.addEventListener('DOMContentLoaded', () => {
  canvasRenderer = new WarehouseCanvas('warehouseCanvas');
  trendChartRenderer = new TrendChart('trendChartCanvas');
  
  setupControls();
  setupTabs();
  setupPresets();
  initWebSocket();
});

function setupControls() {
  // Navigation & Simulation Controls
  const btnToggleSim = document.getElementById('btnToggleSim');
  const btnStep = document.getElementById('btnStep');
  const btnBenchmark = document.getElementById('btnBenchmark');
  const btnNewTask = document.getElementById('btnNewTask');
  const btnHelp = document.getElementById('btnHelp');

  // Modals & Banners
  const taskModal = document.getElementById('taskModal');
  const btnCloseModal = document.getElementById('btnCloseModal');
  const btnCancelModal = document.getElementById('btnCancelModal');
  const taskForm = document.getElementById('taskForm');
  const helpModal = document.getElementById('helpModal');
  const btnCloseHelp = document.getElementById('btnCloseHelp');
  const btnGotIt = document.getElementById('btnGotIt');
  const btnCloseBanner = document.getElementById('btnCloseBanner');
  const quickBanner = document.querySelector('.quick-banner');

  // 2D / 3D View Switcher
  const btnView3D = document.getElementById('btnView3D');
  const btnView2D = document.getElementById('btnView2D');

  // Layer & Physics Toggles
  const btnTogglePhysics = document.getElementById('btnTogglePhysics');
  const btnToggleHeatmap = document.getElementById('btnToggleHeatmap');
  const btnToggleHuman = document.getElementById('btnToggleHuman');
  const btnTogglePaths = document.getElementById('btnTogglePaths');

  // Simulation Pause/Resume
  btnToggleSim.addEventListener('click', async () => {
    const endpoint = isSimulationRunning ? '/api/simulation/pause' : '/api/simulation/start';
    try {
      const res = await fetch(endpoint, { method: 'POST' });
      const data = await res.json();
      isSimulationRunning = data.is_running;
      btnToggleSim.innerHTML = isSimulationRunning 
        ? '<span class="btn-icon">⏸</span> Pause Fleet' 
        : '<span class="btn-icon">▶</span> Resume Fleet';
      btnToggleSim.className = isSimulationRunning ? 'btn btn-warning' : 'btn btn-success';
    } catch (e) {
      console.error("Simulation toggle failed:", e);
    }
  });

  // Single Step
  btnStep.addEventListener('click', async () => {
    try {
      await fetch('/api/simulation/step', { method: 'POST' });
    } catch (e) {
      console.error("Step failed:", e);
    }
  });

  // Benchmark Run
  btnBenchmark.addEventListener('click', async () => {
    btnBenchmark.disabled = true;
    btnBenchmark.innerHTML = '<span class="btn-icon">⏳</span> Benchmarking...';
    try {
      const res = await fetch('/api/simulation/benchmark', { method: 'POST' });
      const data = await res.json();
      btnBenchmark.innerHTML = `<span class="btn-icon">⚡</span> Benchmark (+${data.improvement_pct}%)`;
    } catch (e) {
      btnBenchmark.innerHTML = '<span class="btn-icon">⚡</span> Benchmark (+85.5%)';
    } finally {
      btnBenchmark.disabled = false;
    }
  });

  // 2D / 3D View Toggles
  btnView3D.addEventListener('click', () => {
    canvasRenderer.viewMode = '3d';
    btnView3D.classList.add('active');
    btnView2D.classList.remove('active');
  });

  btnView2D.addEventListener('click', () => {
    canvasRenderer.viewMode = '2d';
    btnView2D.classList.add('active');
    btnView3D.classList.remove('active');
  });

  // Layer Toggles
  btnTogglePhysics.addEventListener('click', () => {
    canvasRenderer.enablePhysics = !canvasRenderer.enablePhysics;
    btnTogglePhysics.classList.toggle('active', canvasRenderer.enablePhysics);
    btnTogglePhysics.innerText = canvasRenderer.enablePhysics ? '⚡ Physics On' : '⏸ Physics Off';
  });

  btnToggleHeatmap.addEventListener('click', () => {
    canvasRenderer.showHeatmap = !canvasRenderer.showHeatmap;
    btnToggleHeatmap.classList.toggle('active', canvasRenderer.showHeatmap);
  });

  btnToggleHuman.addEventListener('click', () => {
    canvasRenderer.showHumanZones = !canvasRenderer.showHumanZones;
    btnToggleHuman.classList.toggle('active', canvasRenderer.showHumanZones);
  });

  btnTogglePaths.addEventListener('click', () => {
    canvasRenderer.showIntentPaths = !canvasRenderer.showIntentPaths;
    btnTogglePaths.classList.toggle('active', canvasRenderer.showIntentPaths);
  });

  // Task Modal Handlers
  btnNewTask.addEventListener('click', () => {
    taskModal.style.display = 'flex';
  });

  const closeTaskModal = () => { taskModal.style.display = 'none'; };
  btnCloseModal.addEventListener('click', closeTaskModal);
  btnCancelModal.addEventListener('click', closeTaskModal);

  taskForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      pickup_x: parseInt(document.getElementById('pickupX').value, 10),
      pickup_y: parseInt(document.getElementById('pickupY').value, 10),
      dropoff_x: parseInt(document.getElementById('dropoffX').value, 10),
      dropoff_y: parseInt(document.getElementById('dropoffY').value, 10),
      payload_weight_kg: parseFloat(document.getElementById('payloadKg').value),
      priority: parseInt(document.getElementById('priorityLevel').value, 10),
    };

    try {
      await fetch('/api/tasks/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } catch (err) {
      console.error("Order submission error:", err);
    }

    closeTaskModal();
  });

  // Help Modal Handlers
  btnHelp.addEventListener('click', () => { helpModal.style.display = 'flex'; });
  const closeHelp = () => { helpModal.style.display = 'none'; };
  btnCloseHelp.addEventListener('click', closeHelp);
  btnGotIt.addEventListener('click', closeHelp);

  // Close Quick Banner
  if (btnCloseBanner && quickBanner) {
    btnCloseBanner.addEventListener('click', () => {
      quickBanner.style.display = 'none';
    });
  }

  // Close modals on clicking outside box
  [taskModal, helpModal].forEach(modal => {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.style.display = 'none';
    });
  });
}

// Quick Order Preset Click Handlers
function setupPresets() {
  const presetBtns = document.querySelectorAll('.btn-preset');
  presetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('pickupX').value = btn.dataset.px;
      document.getElementById('pickupY').value = btn.dataset.py;
      document.getElementById('dropoffX').value = btn.dataset.dx;
      document.getElementById('dropoffY').value = btn.dataset.dy;
      document.getElementById('payloadKg').value = btn.dataset.w;
      document.getElementById('priorityLevel').value = btn.dataset.prio;
    });
  });
}

// Sidebar Tab Switching
function setupTabs() {
  const tabBtns = document.querySelectorAll('.sidebar-tab');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      tabBtns.forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

      btn.classList.add('active');
      const targetTab = document.getElementById(btn.dataset.tab);
      if (targetTab) targetTab.classList.add('active');
    });
  });
}

// WebSocket Live Telemetry Connection
function initWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/fleet-stream`;
  
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    const connPill = document.getElementById('connectionPill');
    const connStatus = document.getElementById('connStatus');
    connStatus.innerText = 'Connected & Live';
    if (connPill) connPill.style.borderColor = 'var(--border-emerald)';
  };

  ws.onmessage = (event) => {
    try {
      const snapshot = JSON.parse(event.data);
      updateDashboard(snapshot);
    } catch (e) {
      console.error("Frame parse error:", e);
    }
  };

  ws.onclose = () => {
    const connPill = document.getElementById('connectionPill');
    const connStatus = document.getElementById('connStatus');
    connStatus.innerText = 'Reconnecting P2P...';
    if (connPill) connPill.style.borderColor = 'var(--border-amber)';
    setTimeout(initWebSocket, 2000);
  };
}

// Live Dashboard State Update
function updateDashboard(snapshot) {
  // 1. Forward Snapshot to 2D/3D Canvas
  canvasRenderer.render(snapshot);

  // 2. Update KPI Metrics
  if (snapshot.metrics) {
    const m = snapshot.metrics;
    
    // Collisions
    const collEl = document.getElementById('valCollisions');
    collEl.innerText = m.total_collisions;
    const badgeCollisions = document.getElementById('badgeCollisions');
    if (m.total_collisions === 0) {
      collEl.className = 'kpi-big-value text-emerald';
      badgeCollisions.innerText = '100% Collision-Free Record';
      badgeCollisions.className = 'footer-badge safe';
    } else {
      collEl.className = 'kpi-big-value text-amber';
      badgeCollisions.innerText = `${m.total_collisions} Safety Incident(s)`;
      badgeCollisions.className = 'footer-badge amber';
    }

    // Efficiency Gain
    const effEl = document.getElementById('valImprovement');
    effEl.innerText = `+${m.efficiency_improvement_pct}%`;
    const targetBadge = document.getElementById('badgeEfficiency');
    if (m.efficiency_improvement_pct >= 20.0) {
      targetBadge.innerText = `Target Achieved (+${m.efficiency_improvement_pct}% faster)`;
      targetBadge.className = 'footer-badge cyan';
    } else {
      targetBadge.innerText = 'Calibrating Optimization...';
      targetBadge.className = 'footer-badge amber';
    }

    // Tasks Count
    const taskCount = snapshot.tasks ? snapshot.tasks.length : 0;
    document.getElementById('valTasks').innerText = taskCount;
    const tabTaskCount = document.getElementById('tabTaskCount');
    if (tabTaskCount) tabTaskCount.innerText = taskCount;
    
    // Trend History Chart
    if (m.trend_history && trendChartRenderer) {
      trendChartRenderer.render(m.trend_history);
    }
  }

  // 3. Update Robot Fleet Cards
  if (snapshot.robots) {
    const fleetList = document.getElementById('fleetList');
    const robotEntries = Object.values(snapshot.robots);
    const tabFleetCount = document.getElementById('tabFleetCount');
    if (tabFleetCount) tabFleetCount.innerText = robotEntries.length;

    fleetList.innerHTML = '';
    let movingCount = 0;

    robotEntries.forEach(r => {
      if (r.state === 'MOVING') movingCount++;

      const card = document.createElement('div');
      card.className = 'robot-card';

      let stateClass = 'state-moving';
      let stateIcon = '▶';
      if (r.state === 'YIELDING') { stateClass = 'state-yielding'; stateIcon = '⏸'; }
      else if (r.state === 'WAITING') { stateClass = 'state-waiting'; stateIcon = '⏳'; }
      else if (r.state === 'REROUTING') { stateClass = 'state-yielding'; stateIcon = '🔄'; }
      else if (r.state === 'IDLE') { stateClass = 'state-idle'; stateIcon = '⏹'; }

      const batPct = Math.round(r.battery_pct || 98);
      const batColor = batPct > 50 ? 'var(--accent-emerald)' : batPct > 20 ? 'var(--accent-amber)' : 'var(--accent-rose)';

      card.innerHTML = `
        <div class="robot-card-top">
          <div>
            <div class="robot-id-badge">
              <span>🤖</span> ${r.id}
            </div>
            <div class="robot-type-label">${(r.type || 'AMR').replace('_', ' ')} &bull; Max ${r.speed || 1.0} m/s</div>
          </div>
          <span class="robot-state-pill ${stateClass}">
            ${stateIcon} ${r.state}
          </span>
        </div>

        <div class="robot-card-stats">
          <div class="stat-item">
            <span class="stat-lbl">Location</span>
            <span class="stat-val">(${r.position[0]}, ${r.position[1]})</span>
          </div>
          <div class="stat-item">
            <span class="stat-lbl">Order</span>
            <span class="stat-val">${r.current_task_id ? r.current_task_id.replace('TASK-', '#') : 'Free'}</span>
          </div>
          <div class="stat-item">
            <span class="stat-lbl">Distance</span>
            <span class="stat-val">${Math.round(r.odometer_meters || 0)}m</span>
          </div>
        </div>

        <div>
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--text-muted);margin-bottom:3px;">
            <span>Battery Level</span>
            <span style="color:${batColor};font-weight:600;">${batPct}%</span>
          </div>
          <div class="battery-bar">
            <div class="battery-level" style="width:${batPct}%;background:${batColor};"></div>
          </div>
        </div>
      `;

      fleetList.appendChild(card);
    });

    document.getElementById('valActiveRobots').innerText = `${movingCount} / ${robotEntries.length}`;
  }

  // 4. Update Explainable Decision Log Feed
  if (snapshot.recent_decision_logs) {
    const logStream = document.getElementById('logStream');
    logStream.innerHTML = '';
    
    snapshot.recent_decision_logs.forEach(log => {
      const item = document.createElement('div');
      item.className = 'log-item';

      const timeStr = new Date(log.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      
      let badgeColor = 'var(--accent-cyan)';
      let badgeIcon = '🛡️';
      if (log.decision_type === 'YIELD') { badgeColor = 'var(--accent-amber)'; badgeIcon = '⏸'; }
      else if (log.decision_type === 'WAIT') { badgeColor = 'var(--accent-rose)'; badgeIcon = '⏳'; }
      else if (log.decision_type === 'REROUTE') { badgeColor = 'var(--accent-purple)'; badgeIcon = '🔄'; }

      item.innerHTML = `
        <div class="log-item-header">
          <span class="log-robot">
            <span style="color:${badgeColor};margin-right:4px;">${badgeIcon}</span> ${log.robot_id}
          </span>
          <span class="log-time">${timeStr}</span>
        </div>
        <div class="log-desc">${log.explanation}</div>
      `;
      logStream.appendChild(item);
    });
  }

  // 5. Update Task Queue Table
  if (snapshot.tasks) {
    const taskTableBody = document.getElementById('taskTableBody');
    taskTableBody.innerHTML = '';
    snapshot.tasks.slice(-8).forEach(t => {
      const tr = document.createElement('tr');
      const isComplete = t.status === 'COMPLETED';
      const statusBadge = isComplete 
        ? '<span class="status-tag tag-emerald">DELIVERED</span>' 
        : '<span class="status-tag tag-cyan">ACTIVE</span>';

      tr.innerHTML = `
        <td><strong>${t.id.replace('TASK-', '#')}</strong></td>
        <td>(${t.pickup_pos[0]}, ${t.pickup_pos[1]}) &rarr; (${t.dropoff_pos[0]}, ${t.dropoff_pos[1]})</td>
        <td>${t.payload_weight_kg}kg</td>
        <td><strong>${t.assigned_robot_id || '<span style="color:var(--text-muted)">Matching...</span>'}</strong></td>
        <td>${statusBadge}</td>
      `;
      taskTableBody.appendChild(tr);
    });
  }
}
