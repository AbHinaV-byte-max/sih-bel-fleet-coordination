# 🚚 Decentralized Autonomous Mobile Robot (AMR) Fleet Coordination System

> **Sponsored by Bharat Electronics Limited (BEL)** &bull; **Smart India Hackathon (SIH) Problem Statement 26123**

An enterprise-grade, decentralized multi-robot coordination and collision-avoidance framework for high-throughput warehouse and defense depot environments. Built entirely on open, auditable algorithms (deterministic space-time right-of-way protocol and Hungarian minimum-cost task assignment) with **strictly zero inter-robot collisions** and **+85.5% efficiency improvement** over baseline navigation.

---

## 🌟 Key Features

- **🛡️ 100% Collision-Free Guarantee**: Decentralized peer-to-peer (P2P) Decision-Support System (DSS) executing locally on edge AMR processes. Zero black-box ML — 100% deterministic, auditable right-of-way arbitration.
- **⚡ +85.5% Efficiency Boost**: Demonstrates an 85.5% reduction in mission completion time vs. naive stop-and-wait proximity schemes across complex 4-way intersection choke points.
- **🧊 Dual-Mode 2D & 3D Isometric Digital Twin**:
  - **3D Isometric View**: High-level perspective with extruded multi-tier warehouse shelving, realistic cargo pallets, 3D AMR pod chassis with wheels, floor drop shadows, and volumetric docking beacons.
  - **2D Top-Down HD View**: Crisp tactical corridor navigation with forward intent path ribbons and directional heading indicators.
- **🏎️ Visible Motion Physics**: Real-time chassis acceleration/braking inertia tilt, angular steering momentum, suspension micro-rumble, dynamic cargo settling bounce, and ambient atmospheric dust motes.
- **📋 Hungarian Minimum-Cost Task Allocation**: Automatically matches logistics delivery orders to the optimal AMR based on payload capacity, Euclidean proximity, and battery state using `scipy.optimize.linear_sum_assignment`.
- **🔒 Defense-Grade Communications Security**: Message authentication via HMAC-SHA256 tamper detection and replay protection over a pub/sub event fabric.
- **📊 Traceable Audit Trail**: Every routing, yielding, and rerouting decision is logged with human-readable explanations for defense compliance.

---

## 🏗️ System Architecture

```text
├── config/                  # Warehouse grid, robot types, and depot YAML configuration
├── services/
│   ├── comms_broker/        # P2P Pub/Sub broker with HMAC-SHA256 message security
│   ├── robot_agent/         # Edge AMR agent, A* pathfinding, and conflict arbiter
│   ├── task_allocation/     # Hungarian matching allocator (SciPy)
│   ├── metrics/             # Live KPI tracker, congestion heatmap & baseline runner
│   ├── api_gateway/         # FastAPI REST & WebSocket streaming server
│   └── dashboard/           # Modern web dashboard (HTML5, Vanilla CSS, 2D/3D Canvas)
└── tests/
    ├── unit/                # Unit tests for arbiter, broker, allocator, gateway
    └── integration/         # Full 4-way intersection benchmark scenario
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.10+
- Install dependencies:
  ```bash
  pip install fastapi uvicorn pydantic scipy pyyaml anyio pytest httpx
  ```

### 2. Launch the Application
```bash
python -m uvicorn services.api_gateway.app:app --port 8000
```
Open your browser at **`http://localhost:8000`** to access the interactive 2D/3D fleet dashboard.

### 3. Run Automated Benchmark Tests
```bash
pytest -s
```

---

## 📜 SIH 26123 Success Benchmark Results

```text
=======================================================
SIH 26123 SUCCESS CRITERIA BENCHMARK RESULTS:
- Total Collisions:            0 (TARGET: STRICTLY 0) -> PASSED
- Decentralized DSS Duration:  29 ticks
- Naive Baseline Duration:     200 ticks
- Baseline Wait Stalls:        772 stalls
- Efficiency Improvement:      85.5% (TARGET: >= 20.0%) -> PASSED
=======================================================
```

---

## 👥 Authors & Acknowledgments
- **Problem Statement**: SIH 26123
- **Organization**: Bharat Electronics Limited (BEL) — Ministry of Defence, Govt. of India
