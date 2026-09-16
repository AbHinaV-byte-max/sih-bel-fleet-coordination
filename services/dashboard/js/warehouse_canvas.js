/**
 * Warehouse Tactical Canvas Renderer v5.0
 * SIH 26123 — Bharat Electronics Limited (BEL)
 *
 * Clean 2D tactical grid renderer. NO pseudo-physics simulation.
 * Renders: static racks, dynamic obstacles, AMRs with heading arrows,
 * forward intent path ribbons, §11.2 space-time reservations,
 * live conflict markers, human safety zones, congestion heatmap.
 */

class WarehouseCanvas {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx    = this.canvas ? this.canvas.getContext('2d') : null;

    // Grid config (match warehouse config: 24×18)
    this.gridW  = 24;
    this.gridH  = 18;
    this.cellSz = 32; // px per cell at zoom=1

    // Viewport state
    this.zoom     = 1.0;
    this.offsetX  = 0;
    this.offsetY  = 0;
    this.dragging = false;
    this.lastMX   = 0;
    this.lastMY   = 0;

    // Layer toggles
    this.layers = {
      paths:        true,
      heatmap:      true,
      human:        true,
      reservations: true,
      labels:       true,
    };

    // Data from WebSocket
    this.snapshot = null;
    this.heatmap  = {};

    // Interaction
    this.hoveredRobot    = null;
    this.selectedRobotId = null;
    this.onRobotClick    = null; // callback(robotId)
    this.onCellClick     = null; // callback(x, y)

    if (this.canvas) {
      this._resize();
      this._bindEvents();
      this._centerView();
      this._scheduleRender();
    }
  }

  // ── Public API ───────────────────────────────────────────────
  updateSnapshot(snapshot) {
    if (!snapshot) return;
    this.snapshot = snapshot;
    if (snapshot.warehouse) {
      this.gridW = snapshot.warehouse.width || 24;
      this.gridH = snapshot.warehouse.height || 18;
    }
  }

  updateHeatmap(heatmap) {
    this.heatmap = heatmap || {};
  }

  setLayer(layer, enabled) {
    this.layers[layer] = enabled;
  }

  setSelectedRobot(id) {
    this.selectedRobot = id;
  }

  zoomIn()    { this.zoom = Math.min(this.zoom * 1.25, 5); }
  zoomOut()   { this.zoom = Math.max(this.zoom * 0.8, 0.3); }
  resetView() { this._centerView(); this.zoom = 1.0; }

  // ── Internal rendering ────────────────────────────────────────
  _scheduleRender() {
    const render = () => {
      this._resize();
      if (this.ctx) this._draw();
      requestAnimationFrame(render);
    };
    requestAnimationFrame(render);
  }

  _resize() {
    const vp = this.canvas.parentElement;
    if (!vp) return;
    const w = vp.clientWidth  || 800;
    const h = vp.clientHeight || 480;
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width  = w;
      this.canvas.height = h;
    }
  }

  _centerView() {
    if (!this.canvas) return;
    const totalW = this.gridW * this.cellSz * this.zoom;
    const totalH = this.gridH * this.cellSz * this.zoom;
    this.offsetX = (this.canvas.width  - totalW) / 2;
    this.offsetY = (this.canvas.height - totalH) / 2;
  }

  _toScreen(gx, gy) {
    return {
      x: this.offsetX + gx * this.cellSz * this.zoom,
      y: this.offsetY + gy * this.cellSz * this.zoom,
    };
  }

  _toGrid(sx, sy) {
    return {
      gx: Math.floor((sx - this.offsetX) / (this.cellSz * this.zoom)),
      gy: Math.floor((sy - this.offsetY) / (this.cellSz * this.zoom)),
    };
  }

  _draw() {
    const ctx = this.ctx;
    const W   = this.canvas.width;
    const H   = this.canvas.height;
    const cs  = this.cellSz * this.zoom;

    ctx.clearRect(0, 0, W, H);

    // Background
    ctx.fillStyle = '#0f1013';
    ctx.fillRect(0, 0, W, H);

    if (!this.snapshot) {
      // Waiting for data
      ctx.fillStyle = 'rgba(148,163,184,0.25)';
      ctx.font = '14px Inter, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Connecting to fleet coordination backend…', W/2, H/2);
      return;
    }

    const wh = this.snapshot.warehouse || {};

    // ── 1. Heatmap layer ───────────────────────────────────────
    if (this.layers.heatmap && this.heatmap && Object.keys(this.heatmap).length > 0) {
      const maxCount = Math.max(1, ...Object.values(this.heatmap).map(v => v.count || 0));
      for (const [key, val] of Object.entries(this.heatmap)) {
        const [hx, hy] = key.split(',').map(Number);
        const intensity = (val.count || 0) / maxCount;
        if (intensity < 0.05) continue;
        const s = this._toScreen(hx, hy);
        ctx.fillStyle = `rgba(239,68,68,${intensity * 0.35})`;
        ctx.fillRect(s.x, s.y, cs, cs);
      }
    }

    // ── 2. Grid lines ───────────────────────────────────────────
    ctx.strokeStyle = 'rgba(255,255,255,0.045)';
    ctx.lineWidth   = 0.5;
    for (let gx = 0; gx <= this.gridW; gx++) {
      const sx = this.offsetX + gx * cs;
      ctx.beginPath(); ctx.moveTo(sx, this.offsetY); ctx.lineTo(sx, this.offsetY + this.gridH * cs); ctx.stroke();
    }
    for (let gy = 0; gy <= this.gridH; gy++) {
      const sy = this.offsetY + gy * cs;
      ctx.beginPath(); ctx.moveTo(this.offsetX, sy); ctx.lineTo(this.offsetX + this.gridW * cs, sy); ctx.stroke();
    }

    // ── 3. Human zones ──────────────────────────────────────────
    if (this.layers.human && wh.human_zones) {
      for (const hz of wh.human_zones) {
        if (!hz.active) continue;
        const [x1, y1, x2, y2] = hz.bounds || [];
        if (x1 == null) continue;
        const s = this._toScreen(x1, y1);
        const sw = (x2 - x1) * cs;
        const sh = (y2 - y1) * cs;
        ctx.fillStyle   = 'rgba(245,158,11,0.07)';
        ctx.strokeStyle = 'rgba(245,158,11,0.4)';
        ctx.lineWidth   = 1;
        ctx.setLineDash([4,4]);
        ctx.fillRect(s.x, s.y, sw, sh);
        ctx.strokeRect(s.x, s.y, sw, sh);
        ctx.setLineDash([]);
        if (this.layers.labels && cs > 20) {
          ctx.fillStyle = 'rgba(245,158,11,0.6)';
          ctx.font = `${Math.max(8, cs * 0.25)}px Inter, sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText('⚠ Human Zone', s.x + sw/2, s.y + sh/2);
        }
      }
    }

    // ── 4. Static obstacles (storage racks) ─────────────────────
    if (wh.obstacles) {
      for (const [ox, oy] of wh.obstacles) {
        const s = this._toScreen(ox, oy);
        // Draw rack
        ctx.fillStyle = '#1c1e24';
        ctx.fillRect(s.x + 1, s.y + 1, cs - 2, cs - 2);
        ctx.strokeStyle = '#2b2e37';
        ctx.lineWidth   = 1;
        ctx.strokeRect(s.x + 1, s.y + 1, cs - 2, cs - 2);
        // Rack shelf lines
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
        ctx.lineWidth   = 0.5;
        for (let shelf = 1; shelf < 3; shelf++) {
          const sy = s.y + (cs/3)*shelf;
          ctx.beginPath(); ctx.moveTo(s.x+2, sy); ctx.lineTo(s.x+cs-2, sy); ctx.stroke();
        }
      }
    }

    // ── 5. Dynamic obstacles ─────────────────────────────────────
    if (wh.dynamic_obstacles) {
      for (const [dx, dy] of wh.dynamic_obstacles) {
        const s = this._toScreen(dx, dy);
        ctx.fillStyle   = 'rgba(124,52,52,0.75)';
        ctx.strokeStyle = 'rgba(239,68,68,0.8)';
        ctx.lineWidth   = 1.5;
        ctx.fillRect(s.x+2, s.y+2, cs-4, cs-4);
        ctx.strokeRect(s.x+2, s.y+2, cs-4, cs-4);
        // X mark
        ctx.strokeStyle = 'rgba(239,68,68,0.9)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(s.x+6, s.y+6); ctx.lineTo(s.x+cs-6, s.y+cs-6);
        ctx.moveTo(s.x+cs-6, s.y+6); ctx.lineTo(s.x+6, s.y+cs-6);
        ctx.stroke();
      }
    }

    // ── 6. Pickup & dropoff stations ─────────────────────────────
    if (wh.pickup_stations) {
      for (const st of wh.pickup_stations) {
        const loc = st.location;
        if (!loc) continue;
        const s = this._toScreen(loc[0], loc[1]);
        ctx.fillStyle   = 'rgba(16,185,129,0.22)';
        ctx.strokeStyle = 'rgba(16,185,129,0.7)';
        ctx.lineWidth   = 1.5;
        ctx.fillRect(s.x+2, s.y+2, cs-4, cs-4);
        ctx.strokeRect(s.x+2, s.y+2, cs-4, cs-4);
        if (cs > 22) {
          ctx.fillStyle = 'rgba(16,185,129,0.85)';
          ctx.font = `${Math.max(8, cs*0.3)}px Inter, sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText('▲', s.x+cs/2, s.y+cs/2+4);
        }
      }
    }
    if (wh.dropoff_stations) {
      for (const st of wh.dropoff_stations) {
        const loc = st.location;
        if (!loc) continue;
        const s = this._toScreen(loc[0], loc[1]);
        ctx.fillStyle   = 'rgba(56,189,248,0.22)';
        ctx.strokeStyle = 'rgba(56,189,248,0.7)';
        ctx.lineWidth   = 1.5;
        ctx.fillRect(s.x+2, s.y+2, cs-4, cs-4);
        ctx.strokeRect(s.x+2, s.y+2, cs-4, cs-4);
        if (cs > 22) {
          ctx.fillStyle = 'rgba(56,189,248,0.85)';
          ctx.font = `${Math.max(8, cs*0.3)}px Inter, sans-serif`;
          ctx.textAlign = 'center';
          ctx.fillText('▼', s.x+cs/2, s.y+cs/2+4);
        }
      }
    }

    // ── 7. §11.2 Space-time reservations ──────────────────────────
    if (this.layers.reservations && this.snapshot.robots) {
      for (const robot of Object.values(this.snapshot.robots)) {
        if (!robot.space_time_reservations) continue;
        for (let i = 0; i < robot.space_time_reservations.length; i++) {
          const res = robot.space_time_reservations[i];
          const [rx, ry] = res.cell || [];
          if (rx == null) continue;
          const s  = this._toScreen(rx, ry);
          const alpha = 0.12 - i * 0.012;
          if (alpha < 0.02) continue;
          ctx.fillStyle = `rgba(168,85,247,${Math.max(0.02, alpha)})`;
          ctx.fillRect(s.x+1, s.y+1, cs-2, cs-2);
        }
      }
    }

    // ── 8. Intent path ribbons ─────────────────────────────────────
    if (this.layers.paths && this.snapshot.robots) {
      for (const robot of Object.values(this.snapshot.robots)) {
        if (!robot.intent || robot.intent.length < 2) continue;
        const color = this._stateColor(robot.state);
        ctx.strokeStyle = color.replace(/[\d.]+\)$/, '0.35)');
        ctx.lineWidth   = Math.max(2, cs * 0.12);
        ctx.lineJoin    = 'round';
        ctx.lineCap     = 'round';
        ctx.setLineDash([cs*0.3, cs*0.15]);
        ctx.beginPath();
        const pos0 = this._toScreen(robot.position[0], robot.position[1]);
        ctx.moveTo(pos0.x + cs/2, pos0.y + cs/2);
        for (const [px, py] of robot.intent) {
          const s = this._toScreen(px, py);
          ctx.lineTo(s.x + cs/2, s.y + cs/2);
        }
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }

    // ── 9. Robots ──────────────────────────────────────────────────
    if (this.snapshot.robots) {
      for (const robot of Object.values(this.snapshot.robots)) {
        this._drawRobot(robot, cs);
      }
    }

    // ── 10. Conflict markers ───────────────────────────────────────
    if (this.snapshot.recent_decision_logs) {
      const conflicts = this.snapshot.recent_decision_logs.filter(
        l => l.decision_type === 'YIELD' || l.decision_type === 'REROUTE'
      );
      // Deduplicate by location
      const seen = new Set();
      for (const log of conflicts) {
        if (!log.location) continue;
        const key = log.location.join(',');
        if (seen.has(key)) continue;
        seen.add(key);
        const [cx, cy] = log.location;
        const s = this._toScreen(cx, cy);
        ctx.strokeStyle = log.decision_type === 'REROUTE'
          ? 'rgba(244,63,94,0.8)'
          : 'rgba(245,158,11,0.75)';
        ctx.lineWidth = 2;
        const r = cs * 0.38;
        ctx.beginPath();
        ctx.arc(s.x + cs/2, s.y + cs/2, r, 0, Math.PI*2);
        ctx.stroke();
        // Pulse ring
        ctx.strokeStyle = log.decision_type === 'REROUTE'
          ? 'rgba(244,63,94,0.25)'
          : 'rgba(245,158,11,0.2)';
        ctx.lineWidth = 3;
        const pulseR = r + (Date.now() % 1000) / 1000 * r * 0.4;
        ctx.beginPath();
        ctx.arc(s.x + cs/2, s.y + cs/2, pulseR, 0, Math.PI*2);
        ctx.stroke();
      }
    }
  }

  _drawRobot(robot, cs) {
    const ctx   = this.ctx;
    const [gx, gy] = robot.position;
    const s     = this._toScreen(gx, gy);
    const cx    = s.x + cs/2;
    const cy    = s.y + cs/2;
    const r     = Math.max(7, cs * 0.34);
    const color = this._stateColor(robot.state);
    const isHovered  = this.hoveredRobot === robot.id;
    const isSelected = this.selectedRobot === robot.id;

    // Glow / selection ring
    if (isSelected) {
      ctx.shadowColor = '#38bdf8';
      ctx.shadowBlur  = 12;
    }
    if (isHovered) {
      ctx.shadowColor = color;
      ctx.shadowBlur  = 8;
    }

    // Body circle
    ctx.fillStyle   = color.replace(/[\d.]+\)$/, '0.22)');
    ctx.strokeStyle = color;
    ctx.lineWidth   = isSelected ? 2.5 : 1.8;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI*2);
    ctx.fill();
    ctx.stroke();

    ctx.shadowBlur = 0;

    // Heading arrow
    const heading = robot.heading_rad || 0;
    if (robot.state === 'MOVING') {
      const arrowLen = r * 0.9;
      const ex = cx + Math.cos(heading) * arrowLen;
      const ey = cy + Math.sin(heading) * arrowLen;
      ctx.strokeStyle = color;
      ctx.lineWidth   = 2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(ex, ey);
      ctx.stroke();
      // arrowhead
      const hx1 = ex + Math.cos(heading + 2.5) * 4;
      const hy1 = ey + Math.sin(heading + 2.5) * 4;
      const hx2 = ex + Math.cos(heading - 2.5) * 4;
      const hy2 = ey + Math.sin(heading - 2.5) * 4;
      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(hx1, hy1);
      ctx.lineTo(hx2, hy2);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
    }

    // State indicator dot (top-right)
    ctx.fillStyle = this._stateColor(robot.state);
    ctx.beginPath();
    ctx.arc(cx + r*0.65, cy - r*0.65, Math.max(3, cs*0.1), 0, Math.PI*2);
    ctx.fill();

    // Label
    if (this.layers.labels && cs > 22) {
      const shortId = robot.id.replace('AMR-', '');
      ctx.fillStyle  = '#f0f4fc';
      ctx.font       = `bold ${Math.max(8, Math.min(11, cs*0.3))}px JetBrains Mono, monospace`;
      ctx.textAlign  = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(shortId, cx, cy);
      ctx.textBaseline = 'alphabetic';
    }

    // Battery arc below robot (tiny indicator)
    if (cs > 28) {
      const battPct = (robot.battery_pct || 0) / 100;
      const arcR    = r + 4;
      ctx.strokeStyle = 'rgba(255,255,255,0.12)';
      ctx.lineWidth   = 2.5;
      ctx.beginPath();
      ctx.arc(cx, cy, arcR, Math.PI*0.6, Math.PI*2.4);
      ctx.stroke();

      const battColor = battPct > 0.5 ? '#10b981' : battPct > 0.25 ? '#f59e0b' : '#ef4444';
      const endAngle  = Math.PI*0.6 + battPct * (Math.PI*1.8);
      ctx.strokeStyle = battColor;
      ctx.lineWidth   = 2.5;
      ctx.beginPath();
      ctx.arc(cx, cy, arcR, Math.PI*0.6, endAngle);
      ctx.stroke();
    }
  }

  _stateColor(state) {
    const map = {
      IDLE:      'rgba(148,163,184,0.85)',
      ASSIGNED:  'rgba(129,140,248,0.9)',
      PLANNING:  'rgba(56,189,248,0.9)',
      MOVING:    'rgba(16,185,129,0.9)',
      WAITING:   'rgba(245,158,11,0.9)',
      YIELDING:  'rgba(251,191,36,0.9)',
      REROUTING: 'rgba(244,63,94,0.9)',
      CHARGING:  'rgba(245,158,11,0.9)',
      DEGRADED:  'rgba(244,63,94,0.75)',
      FAILED:    'rgba(239,68,68,0.9)',
      COMPLETED: 'rgba(16,185,129,0.9)',
    };
    return map[state] || 'rgba(148,163,184,0.9)';
  }

  // ── Events ────────────────────────────────────────────────────
  _bindEvents() {
    const c = this.canvas;
    // Scroll to zoom
    c.addEventListener('wheel', e => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 0.9;
      this.zoom = Math.max(0.3, Math.min(5, this.zoom * factor));
    }, { passive: false });

    // Drag to pan
    c.addEventListener('mousedown', e => {
      this.dragging = true;
      this.lastMX   = e.clientX;
      this.lastMY   = e.clientY;
    });
    window.addEventListener('mouseup', () => { this.dragging = false; });
    window.addEventListener('mousemove', e => {
      if (this.dragging) {
        this.offsetX += e.clientX - this.lastMX;
        this.offsetY += e.clientY - this.lastMY;
        this.lastMX   = e.clientX;
        this.lastMY   = e.clientY;
      }
    });

    // Hover to show tooltip
    c.addEventListener('mousemove', e => {
      const rect = c.getBoundingClientRect();
      const mx   = e.clientX - rect.left;
      const my   = e.clientY - rect.top;
      const g    = this._toGrid(mx, my);
      const tooltip = document.getElementById('robotTooltip');
      let found  = false;

      if (this.snapshot && this.snapshot.robots) {
        for (const r of Object.values(this.snapshot.robots)) {
          if (r.position[0] === g.gx && r.position[1] === g.gy) {
            this.hoveredRobot = r.id;
            if (tooltip) {
              document.getElementById('ttHeader').textContent = r.id;
              document.getElementById('ttState').textContent  = r.state;
              document.getElementById('ttBatt').textContent   = `${r.battery_pct}%`;
              document.getElementById('ttVel').textContent    = `${r.velocity_mps} m/s`;
              document.getElementById('ttTask').textContent   = r.current_task_id || 'None';
              tooltip.style.display = 'block';
              tooltip.style.left    = `${mx + 16}px`;
              tooltip.style.top     = `${my - 10}px`;
            }
            found = true;
            break;
          }
        }
      }
      if (!found) {
        this.hoveredRobot = null;
        if (tooltip) tooltip.style.display = 'none';
      }
    });

    c.addEventListener('mouseleave', () => {
      this.hoveredRobot = null;
      const tooltip = document.getElementById('robotTooltip');
      if (tooltip) tooltip.style.display = 'none';
    });

    // Click: select robot or toggle cell obstacle
    c.addEventListener('click', e => {
      if (this.dragging) return;
      const rect = c.getBoundingClientRect();
      const mx   = e.clientX - rect.left;
      const my   = e.clientY - rect.top;
      const g    = this._toGrid(mx, my);

      let clickedRobot = false;
      if (this.snapshot && this.snapshot.robots) {
        for (const r of Object.values(this.snapshot.robots)) {
          if (r.position[0] === g.gx && r.position[1] === g.gy) {
            this.selectedRobot = r.id;
            if (this.onRobotClick) this.onRobotClick(r.id);
            clickedRobot = true;
            break;
          }
        }
      }
      if (!clickedRobot && this.onCellClick) {
        this.onCellClick(g.gx, g.gy);
      }
    });

    // Touch to zoom/pan (basic)
    let lastDist = 0;
    c.addEventListener('touchstart', e => {
      if (e.touches.length === 2) {
        lastDist = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
      }
    });
    c.addEventListener('touchmove', e => {
      if (e.touches.length === 2) {
        const d = Math.hypot(
          e.touches[0].clientX - e.touches[1].clientX,
          e.touches[0].clientY - e.touches[1].clientY
        );
        this.zoom = Math.max(0.3, Math.min(5, this.zoom * (d / lastDist)));
        lastDist = d;
        e.preventDefault();
      }
    }, { passive: false });
  }
}
