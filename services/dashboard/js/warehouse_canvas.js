/**
 * Warehouse Canvas Engine - Dual 2D & 3D Isometric with Visible Motion Physics
 * SIH 26123 - Bharat Electronics Limited (BEL)
 */

class WarehouseCanvas {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext('2d');
    
    // View state
    this.viewMode = '3d'; // '3d' (isometric) or '2d' (top-down)
    this.enablePhysics = true;
    this.showHeatmap = true;
    this.showHumanZones = true;
    this.showIntentPaths = true;
    
    // Grid metrics
    this.gridWidth = 24;
    this.gridHeight = 18;
    this.cellPx = 32;

    // Isometric projection metrics
    this.isoTileW = 44;
    this.isoTileH = 22;
    this.isoOriginX = 0;
    this.isoOriginY = 0;

    // Snapshot buffer
    this.latestSnapshot = null;

    // Physics state cache for each AMR (keyed by robot_id)
    this.robotPhysics = {};

    // Ambient dust motes particles (warehouse atmosphere)
    this.particles = [];
    this.initParticles(35);

    // Mouse hover tracking
    this.mouse = { x: -1, y: -1, hoveredRobot: null };
    this.tooltipEl = document.getElementById('robotTooltip');
    this.ttHeaderEl = document.getElementById('ttHeader');
    this.ttBodyEl = document.getElementById('ttBody');

    // Setup viewport & events
    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.setupInteraction();

    // Start 60 FPS continuous physics & render loop
    this.lastTimestamp = performance.now();
    this.animate = this.animate.bind(this);
    requestAnimationFrame(this.animate);
  }

  initParticles(count) {
    this.particles = [];
    for (let i = 0; i < count; i++) {
      this.particles.push({
        x: Math.random() * (this.canvas.width || 800),
        y: Math.random() * (this.canvas.height || 600),
        vx: (Math.random() - 0.5) * 0.3,
        vy: -0.15 - Math.random() * 0.25, // Gentle upward atmospheric drift
        radius: 1 + Math.random() * 1.8,
        alpha: 0.15 + Math.random() * 0.25,
      });
    }
  }

  resize() {
    const rect = this.canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.ctx.scale(dpr, dpr);
    this.displayWidth = rect.width;
    this.displayHeight = rect.height;

    // Recompute 2D cell metrics
    this.cellPx = Math.min(
      (this.displayWidth - 40) / this.gridWidth,
      (this.displayHeight - 40) / this.gridHeight
    );

    // Recompute 3D isometric metrics
    // In isometric: total W ~ (gw + gh) * tileW / 2
    const desiredIsoW = (this.gridWidth + this.gridHeight) * 0.5;
    this.isoTileW = Math.min(52, Math.max(30, (this.displayWidth - 80) / desiredIsoW));
    this.isoTileH = this.isoTileW * 0.5;

    this.isoOriginX = this.displayWidth / 2;
    this.isoOriginY = Math.max(70, (this.displayHeight - (this.gridWidth + this.gridHeight) * (this.isoTileH * 0.5)) / 2 + 10);
  }

  setupInteraction() {
    this.canvas.addEventListener('mousemove', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      this.mouse.x = e.clientX - rect.left;
      this.mouse.y = e.clientY - rect.top;
      this.updateHover();
    });

    this.canvas.addEventListener('mouseleave', () => {
      this.mouse.x = -1;
      this.mouse.y = -1;
      this.mouse.hoveredRobot = null;
      if (this.tooltipEl) this.tooltipEl.style.display = 'none';
    });
  }

  updateHover() {
    if (!this.latestSnapshot || !this.latestSnapshot.robots) return;

    let closest = null;
    let minDist = 28; // Pixel hover threshold

    Object.values(this.latestSnapshot.robots).forEach(r => {
      const p = this.robotPhysics[r.id];
      if (!p) return;

      let sx, sy;
      if (this.viewMode === '3d') {
        const pt = this.toIso(p.x, p.y);
        sx = pt.x;
        sy = pt.y - p.z;
      } else {
        sx = (p.x + 0.5) * this.cellPx;
        sy = (p.y + 0.5) * this.cellPx;
      }

      const d = Math.hypot(this.mouse.x - sx, this.mouse.y - sy);
      if (d < minDist) {
        minDist = d;
        closest = { robot: r, screenX: sx, screenY: sy };
      }
    });

    this.mouse.hoveredRobot = closest ? closest.robot : null;

    if (closest && this.tooltipEl) {
      const r = closest.robot;
      this.tooltipEl.style.display = 'block';
      this.tooltipEl.style.left = `${Math.min(this.displayWidth - 200, Math.max(10, closest.screenX + 15))}px`;
      this.tooltipEl.style.top = `${Math.min(this.displayHeight - 110, Math.max(10, closest.screenY - 30))}px`;

      this.ttHeaderEl.innerText = `${r.id} (${r.type || 'AMR Hauler'})`;
      this.ttBodyEl.innerHTML = `
        <div>State: <strong>${r.state}</strong></div>
        <div>Battery: <strong>${r.battery_pct || 98}%</strong> &bull; Speed: <strong>${r.speed || 1.0} m/s</strong></div>
        <div>Odometer: <strong>${r.odometer_meters || 0} m</strong> &bull; Priority: <strong>${r.priority_weight || 1}</strong></div>
        ${r.current_task_id ? `<div style="color:var(--accent-cyan-light);margin-top:2px;">Order: ${r.current_task_id}</div>` : ''}
      `;
    } else if (this.tooltipEl) {
      this.tooltipEl.style.display = 'none';
    }
  }

  // Coordinate transforms
  toIso(gx, gy) {
    return {
      x: this.isoOriginX + (gx - gy) * (this.isoTileW * 0.5),
      y: this.isoOriginY + (gx + gy) * (this.isoTileH * 0.5),
    };
  }

  // Invoked externally whenever a new server WebSocket snapshot arrives
  render(snapshot) {
    if (!snapshot) return;
    this.latestSnapshot = snapshot;

    if (snapshot.warehouse) {
      this.gridWidth = snapshot.warehouse.width || 24;
      this.gridHeight = snapshot.warehouse.height || 18;
    }

    // Sync targets into physics cache
    if (snapshot.robots) {
      Object.values(snapshot.robots).forEach(r => {
        const [tx, ty] = r.position;
        if (!this.robotPhysics[r.id]) {
          this.robotPhysics[r.id] = {
            x: tx,
            y: ty,
            targetX: tx,
            targetY: ty,
            vx: 0,
            vy: 0,
            speed: 0,
            angle: 0,
            pitch: 0, // forward/backward inertia tilt
            roll: 0,  // turning banking
            suspension: 0, // vertical bounce
            cargoSettle: 0,
            lidarAngle: Math.random() * Math.PI * 2,
            z: 0,
          };
        } else {
          this.robotPhysics[r.id].targetX = tx;
          this.robotPhysics[r.id].targetY = ty;
        }
      });
    }
  }

  // Main 60 FPS Physics & Render Tick
  animate(now) {
    const dt = Math.min(0.1, (now - this.lastTimestamp) / 1000.0);
    this.lastTimestamp = now;

    // 1. Advance physics simulation
    this.updatePhysics(dt, now * 0.001);

    // 2. Draw frame
    this.drawFrame(now * 0.001);

    requestAnimationFrame(this.animate);
  }

  updatePhysics(dt, timeSec) {
    // A. Update AMR motion & suspension dynamics
    const springRate = this.enablePhysics ? 5.5 : 12.0;

    Object.keys(this.robotPhysics).forEach(rId => {
      const p = this.robotPhysics[rId];
      const dx = p.targetX - p.x;
      const dy = p.targetY - p.y;
      const dist = Math.hypot(dx, dy);

      // Spring-damper position interpolation
      const prevX = p.x;
      const prevY = p.y;

      p.x += dx * Math.min(1.0, springRate * dt);
      p.y += dy * Math.min(1.0, springRate * dt);

      p.vx = (p.x - prevX) / Math.max(0.001, dt);
      p.vy = (p.y - prevY) / Math.max(0.001, dt);
      const currentSpeed = Math.hypot(p.vx, p.vy);
      p.speed = currentSpeed;

      // Angular physics (heading turn with inertia)
      if (dist > 0.04) {
        const targetAngle = Math.atan2(dy, dx);
        let angleDiff = (targetAngle - p.angle + Math.PI * 3) % (Math.PI * 2) - Math.PI;
        p.angle += angleDiff * Math.min(1.0, 9.0 * dt);

        // Banking roll when turning
        if (this.enablePhysics) {
          p.roll = Math.max(-0.12, Math.min(0.12, angleDiff * 0.4));
        }
      } else {
        p.roll *= 0.85;
      }

      // Inertia pitch tilt under acceleration / braking
      if (this.enablePhysics) {
        const accel = (currentSpeed - (p.lastSpeed || 0)) / Math.max(0.001, dt);
        p.pitch = Math.max(-0.14, Math.min(0.14, accel * 0.03));
        p.lastSpeed = currentSpeed;

        // Suspension micro-bobbing while in motion
        if (currentSpeed > 0.1) {
          p.suspension = Math.sin(timeSec * 22) * Math.min(1.5, currentSpeed * 1.2);
          p.cargoSettle = Math.sin(timeSec * 16) * 1.8 * Math.min(1.0, currentSpeed);
        } else {
          p.suspension *= 0.8;
          p.cargoSettle *= 0.8;
        }

        // LiDAR spin
        p.lidarAngle = (p.lidarAngle + dt * 5.0) % (Math.PI * 2);
      } else {
        p.pitch = 0;
        p.roll = 0;
        p.suspension = 0;
        p.cargoSettle = 0;
      }
    });

    // B. Atmospheric dust motes particles
    if (this.enablePhysics) {
      this.particles.forEach(pt => {
        pt.x += pt.vx;
        pt.y += pt.vy;
        if (pt.y < 0) {
          pt.y = this.displayHeight || 600;
          pt.x = Math.random() * (this.displayWidth || 800);
        }
        if (pt.x < 0) pt.x = this.displayWidth || 800;
        if (pt.x > (this.displayWidth || 800)) pt.x = 0;
      });
    }
  }

  drawFrame(timeSec) {
    const ctx = this.ctx;
    const w = this.displayWidth || 800;
    const h = this.displayHeight || 600;

    ctx.clearRect(0, 0, w, h);

    if (!this.latestSnapshot || !this.latestSnapshot.warehouse) {
      this.drawPlaceholder(ctx, w, h);
      return;
    }

    if (this.viewMode === '3d') {
      this.render3D(ctx, timeSec);
    } else {
      this.render2D(ctx, timeSec);
    }

    // Atmospheric particles overlay
    if (this.enablePhysics) {
      this.drawAtmosphere(ctx);
    }
  }

  drawPlaceholder(ctx, w, h) {
    ctx.fillStyle = '#64748b';
    ctx.font = '500 13px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Awaiting live warehouse digital twin connection...', w / 2, h / 2);
  }

  // =========================================================================
  // 3D ISOMETRIC ENGINE
  // =========================================================================
  render3D(ctx, timeSec) {
    const snap = this.latestSnapshot;
    const gw = this.gridWidth;
    const gh = this.gridHeight;
    const tw = this.isoTileW;
    const th = this.isoTileH;

    // 1. Isometric Floor Tiles
    for (let gy = 0; gy < gh; gy++) {
      for (let gx = 0; gx < gw; gx++) {
        const pt = this.toIso(gx, gy);
        this.drawIsoTile(ctx, pt.x, pt.y, tw, th, (gx + gy) % 2 === 0 ? '#0f172a' : '#111c35', '#1a2744');
      }
    }

    // 2. Human Safety Zones (Translucent 3D volumetric caution areas)
    if (this.showHumanZones && snap.warehouse.human_zones) {
      snap.warehouse.human_zones.forEach(hz => {
        if (!hz.active) return;
        this.drawIsoSafetyZone(ctx, hz.bounds, timeSec);
      });
    }

    // 3. Stations (Pickup & Dropoff 3D Bases)
    if (snap.warehouse.pickup_stations) {
      snap.warehouse.pickup_stations.forEach(s => this.drawIsoStation(ctx, s.location, 'IN', '#10b981', timeSec));
    }
    if (snap.warehouse.dropoff_stations) {
      snap.warehouse.dropoff_stations.forEach(s => this.drawIsoStation(ctx, s.location, 'OUT', '#06b6d4', timeSec));
    }

    // 4. Congestion Heatmap Overlay (3D Glow Domes)
    if (this.showHeatmap && snap.congestion_heatmap && snap.congestion_heatmap.cells) {
      snap.congestion_heatmap.cells.forEach(c => this.drawIsoHeatmapCell(ctx, c.x, c.y, c.intensity));
    }

    // 5. Forward Intent Paths (Luminous floor guides)
    if (this.showIntentPaths && snap.robots) {
      Object.values(snap.robots).forEach(r => this.drawIsoIntentPath(ctx, r));
    }

    // 6. Depth-Sorted Rendering for Entities (Racks and AMRs)
    // To ensure correct occlusion in isometric projection, sort by (gx + gy)
    const renderList = [];

    // Add static obstacles (Storage Shelving Racks)
    if (snap.warehouse.obstacles) {
      snap.warehouse.obstacles.forEach(([ox, oy]) => {
        renderList.push({
          type: 'rack',
          sortKey: ox + oy,
          gx: ox,
          gy: oy,
        });
      });
    }

    // Add AMRs (using smoothed physics coordinates)
    if (snap.robots) {
      Object.values(snap.robots).forEach(r => {
        const p = this.robotPhysics[r.id];
        const gx = p ? p.x : r.position[0];
        const gy = p ? p.y : r.position[1];
        renderList.push({
          type: 'amr',
          sortKey: gx + gy,
          robot: r,
          physics: p,
        });
      });
    }

    // Sort back-to-front
    renderList.sort((a, b) => a.sortKey - b.sortKey);

    // Draw sorted entities
    renderList.forEach(item => {
      if (item.type === 'rack') {
        this.drawIsoStorageRack(ctx, item.gx, item.gy);
      } else if (item.type === 'amr') {
        this.drawIsoAMR(ctx, item.robot, item.physics, timeSec);
      }
    });
  }

  drawIsoTile(ctx, sx, sy, tw, th, fillColor, strokeColor) {
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(sx + tw * 0.5, sy + th * 0.5);
    ctx.lineTo(sx, sy + th);
    ctx.lineTo(sx - tw * 0.5, sy + th * 0.5);
    ctx.closePath();

    ctx.fillStyle = fillColor;
    ctx.fill();
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  drawIsoStorageRack(ctx, gx, gy) {
    const tw = this.isoTileW;
    const th = this.isoTileH;
    const pt = this.toIso(gx, gy);
    const sx = pt.x;
    const sy = pt.y;
    const height = 36; // Extruded rack height in pixels

    // Base floor shadow
    ctx.beginPath();
    ctx.ellipse(sx, sy + th * 0.5, tw * 0.45, th * 0.4, 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.45)';
    ctx.fill();

    // 3D Extruded Box Faces:
    // 1. Left Face (Dark shadow)
    ctx.beginPath();
    ctx.moveTo(sx - tw * 0.5, sy + th * 0.5);
    ctx.lineTo(sx, sy + th);
    ctx.lineTo(sx, sy + th - height);
    ctx.lineTo(sx - tw * 0.5, sy + th * 0.5 - height);
    ctx.closePath();
    ctx.fillStyle = '#16223b';
    ctx.fill();
    ctx.strokeStyle = '#23355a';
    ctx.stroke();

    // 2. Right Face (Mid-tone)
    ctx.beginPath();
    ctx.moveTo(sx, sy + th);
    ctx.lineTo(sx + tw * 0.5, sy + th * 0.5);
    ctx.lineTo(sx + tw * 0.5, sy + th * 0.5 - height);
    ctx.lineTo(sx, sy + th - height);
    ctx.closePath();
    ctx.fillStyle = '#1a2948';
    ctx.fill();
    ctx.strokeStyle = '#283d66';
    ctx.stroke();

    // 3. Top Face (Lit surface)
    ctx.beginPath();
    ctx.moveTo(sx, sy - height);
    ctx.lineTo(sx + tw * 0.5, sy + th * 0.5 - height);
    ctx.lineTo(sx, sy + th - height);
    ctx.lineTo(sx - tw * 0.5, sy + th * 0.5 - height);
    ctx.closePath();
    ctx.fillStyle = '#22345b';
    ctx.fill();
    ctx.strokeStyle = '#3b5284';
    ctx.stroke();

    // Shelf tier horizontal bar
    const midH = height * 0.52;
    ctx.beginPath();
    ctx.moveTo(sx - tw * 0.5, sy + th * 0.5 - midH);
    ctx.lineTo(sx, sy + th - midH);
    ctx.lineTo(sx + tw * 0.5, sy + th * 0.5 - midH);
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.2;
    ctx.stroke();

    // Colorful warehouse pallet crates on top of shelf
    const crateSeed = (gx * 17 + gy * 31) % 4;
    const crateColors = ['#f59e0b', '#06b6d4', '#10b981', '#a855f7'];
    const crateColor = crateColors[crateSeed];

    const cx = sx;
    const cy = sy - height + th * 0.25;
    ctx.beginPath();
    ctx.rect(cx - 7, cy - 8, 14, 8);
    ctx.fillStyle = crateColor;
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 0.5;
    ctx.stroke();
  }

  drawIsoAMR(ctx, r, p, timeSec) {
    const tw = this.isoTileW;
    const th = this.isoTileH;
    const gx = p ? p.x : r.position[0];
    const gy = p ? p.y : r.position[1];
    const pt = this.toIso(gx, gy);

    // Apply suspension vertical bobbing
    const suspY = p ? p.suspension : 0;
    const sx = pt.x;
    const sy = pt.y + th * 0.5 + suspY;

    const isHovered = this.mouse.hoveredRobot && this.mouse.hoveredRobot.id === r.id;

    // 1. Dynamic Contact Shadow on Floor
    ctx.beginPath();
    const shadowStretch = p ? 1.0 + Math.min(0.4, p.speed * 0.2) : 1.0;
    ctx.ellipse(sx, sy, tw * 0.38 * shadowStretch, th * 0.32, p ? p.angle : 0, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.55)';
    ctx.fill();

    // 2. Conflict Aura (If yielding or waiting)
    if (r.state === 'YIELDING' || r.state === 'WAITING') {
      const auraColor = r.state === 'YIELDING' ? 'rgba(245, 158, 11, 0.3)' : 'rgba(244, 63, 94, 0.35)';
      const auraStroke = r.state === 'YIELDING' ? '#f59e0b' : '#f43f5e';
      const pulseRadius = (tw * 0.45) + Math.sin(timeSec * 8) * 3;

      ctx.beginPath();
      ctx.ellipse(sx, sy, pulseRadius, pulseRadius * 0.5, 0, 0, Math.PI * 2);
      ctx.fillStyle = auraColor;
      ctx.fill();
      ctx.strokeStyle = auraStroke;
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // 3. AMR Chassis (Extruded Rounded Pod with Physics Pitch & Roll)
    const amrHeight = 16;
    const chW = tw * 0.55;
    const chH = th * 0.55;

    // Pitch tilt offset
    const pitchDy = p ? p.pitch * 14 : 0;
    const baseCy = sy - 4 + pitchDy;

    // Color theme per state
    let themeColor = '#06b6d4'; // Cyan default
    let darkTheme = '#0284c7';
    if (r.state === 'YIELDING') { themeColor = '#f59e0b'; darkTheme = '#d97706'; }
    else if (r.state === 'WAITING') { themeColor = '#f43f5e'; darkTheme = '#e11d48'; }
    else if (r.state === 'REROUTING') { themeColor = '#a855f7'; darkTheme = '#7e22ce'; }
    else if (r.state === 'IDLE') { themeColor = '#64748b'; darkTheme = '#475569'; }

    // Body bottom
    ctx.beginPath();
    ctx.ellipse(sx, baseCy, chW * 0.5, chH * 0.5, 0, 0, Math.PI * 2);
    ctx.fillStyle = '#0f172a';
    ctx.fill();

    // Body sides (extrusion)
    ctx.beginPath();
    ctx.ellipse(sx, baseCy - amrHeight, chW * 0.5, chH * 0.5, 0, 0, Math.PI * 2);
    ctx.fillStyle = darkTheme;
    ctx.fill();

    // Side wrap
    ctx.beginPath();
    ctx.rect(sx - chW * 0.5, baseCy - amrHeight, chW, amrHeight);
    ctx.fillStyle = darkTheme;
    ctx.fill();

    // Body top deck
    ctx.beginPath();
    ctx.ellipse(sx, baseCy - amrHeight, chW * 0.48, chH * 0.48, 0, 0, Math.PI * 2);
    ctx.fillStyle = themeColor;
    ctx.fill();
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = isHovered ? 2.5 : 1.2;
    ctx.stroke();

    // 4. Cargo Box on Top (If carrying payload)
    if (r.current_task_id) {
      const cargoH = 14;
      const cargoW = 16;
      const cargoY = baseCy - amrHeight - 3 + (p ? p.cargoSettle : 0);

      ctx.beginPath();
      ctx.rect(sx - cargoW * 0.5, cargoY - cargoH, cargoW, cargoH);
      ctx.fillStyle = '#eab308'; // Pallet box yellow
      ctx.fill();
      ctx.strokeStyle = '#713f12';
      ctx.lineWidth = 1;
      ctx.stroke();

      // Fragile strap line
      ctx.beginPath();
      ctx.moveTo(sx, cargoY - cargoH);
      ctx.lineTo(sx, cargoY);
      ctx.strokeStyle = '#000';
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // 5. Rotating LiDAR Laser Sweep Beam
    if (this.enablePhysics && p) {
      const sweepAngle = p.lidarAngle;
      const beamLen = tw * 0.7;
      const bx = sx + Math.cos(sweepAngle) * beamLen;
      const by = (baseCy - amrHeight) + Math.sin(sweepAngle) * (beamLen * 0.5);

      ctx.beginPath();
      ctx.moveTo(sx, baseCy - amrHeight);
      ctx.lineTo(bx, by);
      ctx.strokeStyle = 'rgba(6, 182, 212, 0.4)';
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }

    // 6. 3D Floating Robot Label & ID Tag
    const numId = r.id.replace('AMR-', '');
    const tagY = baseCy - amrHeight - (r.current_task_id ? 22 : 8);

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 10px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = 'rgba(0,0,0,0.8)';
    ctx.shadowBlur = 4;
    ctx.fillText(`AMR-${numId}`, sx, tagY);
    ctx.shadowBlur = 0;
  }

  drawIsoStation(ctx, loc, label, color, timeSec) {
    const tw = this.isoTileW;
    const th = this.isoTileH;
    const pt = this.toIso(loc[0], loc[1]);
    const sx = pt.x;
    const sy = pt.y;

    // Raised docking pad base
    this.drawIsoTile(ctx, sx, sy - 4, tw * 0.95, th * 0.95, 'rgba(15, 23, 42, 0.9)', color);

    // Hazard corner stripes
    ctx.beginPath();
    ctx.arc(sx, sy + th * 0.4, 4 + Math.sin(timeSec * 5) * 1.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 10;
    ctx.fill();
    ctx.shadowBlur = 0;

    // Holographic floating text
    ctx.fillStyle = color;
    ctx.font = 'bold 10px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(label, sx, sy - 8);
  }

  drawIsoSafetyZone(ctx, bounds, timeSec) {
    const [minX, minY, maxX, maxY] = bounds;
    const tw = this.isoTileW;
    const th = this.isoTileH;

    // 4 corners in iso
    const p1 = this.toIso(minX, minY);
    const p2 = this.toIso(maxX + 1, minY);
    const p3 = this.toIso(maxX + 1, maxY + 1);
    const p4 = this.toIso(minX, maxY + 1);

    ctx.beginPath();
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.lineTo(p3.x, p3.y);
    ctx.lineTo(p4.x, p4.y);
    ctx.closePath();

    // Breathing pulse
    const alpha = 0.08 + Math.sin(timeSec * 3) * 0.03;
    ctx.fillStyle = `rgba(245, 158, 11, ${alpha})`;
    ctx.fill();

    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 6]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  drawIsoHeatmapCell(ctx, gx, gy, intensity) {
    const pt = this.toIso(gx, gy);
    const tw = this.isoTileW;
    const th = this.isoTileH;
    const rad = tw * 0.7;

    const grad = ctx.createRadialGradient(pt.x, pt.y + th * 0.5, 2, pt.x, pt.y + th * 0.5, rad);
    const alpha = Math.min(0.65, intensity * 0.22);
    grad.addColorStop(0, `rgba(244, 63, 94, ${alpha})`);
    grad.addColorStop(0.5, `rgba(245, 158, 11, ${alpha * 0.5})`);
    grad.addColorStop(1, 'transparent');

    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.ellipse(pt.x, pt.y + th * 0.5, rad, rad * 0.5, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  drawIsoIntentPath(ctx, r) {
    if (!r.intent || r.intent.length === 0) return;
    const p = this.robotPhysics[r.id];
    const currPt = this.toIso(p ? p.x : r.position[0], p ? p.y : r.position[1]);
    const th = this.isoTileH;

    ctx.beginPath();
    ctx.moveTo(currPt.x, currPt.y + th * 0.5);

    r.intent.forEach(cell => {
      const pt = this.toIso(cell[0], cell[1]);
      ctx.lineTo(pt.x, pt.y + th * 0.5);
    });

    ctx.strokeStyle = r.state === 'YIELDING' ? 'rgba(245, 158, 11, 0.65)' :
                      r.state === 'WAITING' ? 'rgba(244, 63, 94, 0.65)' :
                      'rgba(6, 182, 212, 0.55)';
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 4]);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // =========================================================================
  // MODERN 2D HIGH-DEF TOP-DOWN ENGINE
  // =========================================================================
  render2D(ctx, timeSec) {
    const snap = this.latestSnapshot;
    const gw = this.gridWidth;
    const gh = this.gridHeight;
    const c = this.cellPx;

    // 1. Crisp grid background
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let x = 0; x <= gw; x++) {
      ctx.beginPath();
      ctx.moveTo(x * c, 0);
      ctx.lineTo(x * c, gh * c);
      ctx.stroke();
    }
    for (let y = 0; y <= gh; y++) {
      ctx.beginPath();
      ctx.moveTo(0, y * c);
      ctx.lineTo(gw * c, y * c);
      ctx.stroke();
    }

    // 2. Human Zones
    if (this.showHumanZones && snap.warehouse.human_zones) {
      snap.warehouse.human_zones.forEach(hz => {
        if (!hz.active) return;
        const [minX, minY, maxX, maxY] = hz.bounds;
        const rx = minX * c;
        const ry = minY * c;
        const rw = (maxX - minX + 1) * c;
        const rh = (maxY - minY + 1) * c;

        ctx.fillStyle = 'rgba(245, 158, 11, 0.08)';
        ctx.fillRect(rx, ry, rw, rh);
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(rx, ry, rw, rh);
        ctx.setLineDash([]);

        ctx.fillStyle = '#f59e0b';
        ctx.font = '10px Inter, sans-serif';
        ctx.fillText('⚠ SAFETY ZONE', rx + 6, ry + 14);
      });
    }

    // 3. Heatmap
    if (this.showHeatmap && snap.congestion_heatmap && snap.congestion_heatmap.cells) {
      snap.congestion_heatmap.cells.forEach(cell => {
        const cx = (cell.x + 0.5) * c;
        const cy = (cell.y + 0.5) * c;
        const rad = c * 1.3;
        const grad = ctx.createRadialGradient(cx, cy, 2, cx, cy, rad);
        grad.addColorStop(0, `rgba(244, 63, 94, ${Math.min(0.7, cell.intensity * 0.25)})`);
        grad.addColorStop(0.5, 'rgba(245, 158, 11, 0.2)');
        grad.addColorStop(1, 'transparent');
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.arc(cx, cy, rad, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    // 4. Storage Racks
    if (snap.warehouse.obstacles) {
      ctx.fillStyle = '#1e293b';
      ctx.strokeStyle = '#334155';
      ctx.lineWidth = 1.5;
      snap.warehouse.obstacles.forEach(([ox, oy]) => {
        ctx.beginPath();
        ctx.roundRect(ox * c + 2, oy * c + 2, c - 4, c - 4, 4);
        ctx.fill();
        ctx.stroke();
      });
    }

    // 5. Stations
    if (snap.warehouse.pickup_stations) {
      snap.warehouse.pickup_stations.forEach(s => {
        const [sx, sy] = s.location;
        ctx.fillStyle = 'rgba(16, 185, 129, 0.2)';
        ctx.strokeStyle = '#10b981';
        ctx.lineWidth = 2;
        ctx.strokeRect(sx * c + 2, sy * c + 2, c - 4, c - 4);
        ctx.fillStyle = '#10b981';
        ctx.font = 'bold 10px monospace';
        ctx.fillText('IN', sx * c + 6, sy * c + c * 0.5 + 4);
      });
    }

    if (snap.warehouse.dropoff_stations) {
      snap.warehouse.dropoff_stations.forEach(s => {
        const [sx, sy] = s.location;
        ctx.fillStyle = 'rgba(6, 182, 212, 0.2)';
        ctx.strokeStyle = '#06b6d4';
        ctx.lineWidth = 2;
        ctx.strokeRect(sx * c + 2, sy * c + 2, c - 4, c - 4);
        ctx.fillStyle = '#06b6d4';
        ctx.font = 'bold 10px monospace';
        ctx.fillText('OUT', sx * c + 4, sy * c + c * 0.5 + 4);
      });
    }

    // 6. Forward Intent Paths
    if (this.showIntentPaths && snap.robots) {
      Object.values(snap.robots).forEach(r => {
        if (!r.intent || r.intent.length === 0) return;
        const p = this.robotPhysics[r.id];
        ctx.beginPath();
        ctx.moveTo((p ? p.x + 0.5 : r.position[0] + 0.5) * c, (p ? p.y + 0.5 : r.position[1] + 0.5) * c);
        r.intent.forEach(pt => ctx.lineTo((pt[0] + 0.5) * c, (pt[1] + 0.5) * c));
        ctx.strokeStyle = r.state === 'YIELDING' ? 'rgba(245, 158, 11, 0.6)' :
                          r.state === 'WAITING' ? 'rgba(244, 63, 94, 0.6)' :
                          'rgba(6, 182, 212, 0.5)';
        ctx.lineWidth = 2;
        ctx.setLineDash([3, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
      });
    }

    // 7. AMRs in 2D with smooth physics interpolation
    if (snap.robots) {
      Object.values(snap.robots).forEach(r => {
        const p = this.robotPhysics[r.id];
        const rx = ((p ? p.x : r.position[0]) + 0.5) * c;
        const ry = ((p ? p.y : r.position[1]) + 0.5) * c;
        const radius = c * 0.38;

        // Shadow
        ctx.beginPath();
        ctx.arc(rx, ry + 2, radius, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(0,0,0,0.4)';
        ctx.fill();

        // Pod Body
        ctx.beginPath();
        ctx.arc(rx, ry, radius, 0, Math.PI * 2);

        let fillColor = '#06b6d4';
        if (r.state === 'YIELDING') fillColor = '#f59e0b';
        else if (r.state === 'WAITING') fillColor = '#f43f5e';
        else if (r.state === 'REROUTING') fillColor = '#a855f7';
        else if (r.state === 'IDLE') fillColor = '#64748b';

        ctx.fillStyle = fillColor;
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Heading indicator triangle
        if (p) {
          const arrowLen = radius * 0.8;
          ctx.beginPath();
          ctx.moveTo(rx + Math.cos(p.angle) * arrowLen, ry + Math.sin(p.angle) * arrowLen);
          ctx.lineTo(rx + Math.cos(p.angle + 2.4) * (radius * 0.5), ry + Math.sin(p.angle + 2.4) * (radius * 0.5));
          ctx.lineTo(rx + Math.cos(p.angle - 2.4) * (radius * 0.5), ry + Math.sin(p.angle - 2.4) * (radius * 0.5));
          ctx.closePath();
          ctx.fillStyle = '#ffffff';
          ctx.fill();
        }

        // AMR label
        ctx.fillStyle = '#0f172a';
        ctx.font = 'bold 9px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(r.id.replace('AMR-', ''), rx, ry);
      });
    }
  }

  // Atmospheric warehouse dust motes
  drawAtmosphere(ctx) {
    this.particles.forEach(pt => {
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, pt.radius, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255, 255, 255, ${pt.alpha})`;
      ctx.fill();
    });
  }
}
