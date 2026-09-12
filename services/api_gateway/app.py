"""
FastAPI API Gateway and Simulation Bridge Service (SIH 26123 - Bharat Electronics Limited).
Exposes REST and WebSocket endpoints for fleet monitoring, metrics, traceable decision logs,
and external 3D simulator ingestion (NVIDIA Isaac Sim via ROS2 bridge).
"""

from typing import Dict, Any, List, Optional
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .simulation_bridge import FleetCoordinatorBridge
from services.task_allocation.task_models import TaskPriority

# Singleton simulation bridge
bridge = FleetCoordinatorBridge()

# Background simulation runner
sim_task: Optional[asyncio.Task] = None


class PositionUpdateRequest(BaseModel):
    x: int = Field(..., ge=0, description="Grid X coordinate")
    y: int = Field(..., ge=0, description="Grid Y coordinate")
    heading_deg: float = Field(0.0, description="Heading orientation in degrees")


class TaskSubmitRequest(BaseModel):
    pickup_x: int
    pickup_y: int
    dropoff_x: int
    dropoff_y: int
    payload_weight_kg: float = 50.0
    priority: int = 2  # 1=Low, 2=Normal, 3=High, 4=Critical


class WebSocketManager:
    """Maintains active WebSocket connections and broadcasts live fleet frames."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, data: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception:
                self.disconnect(connection)


ws_manager = WebSocketManager()


async def background_simulation_loop():
    """Continuous simulation tick loop broadcasting live state via WebSocket."""
    logger_msg = False
    while True:
        try:
            if bridge.is_running:
                snapshot = bridge.step()
                await ws_manager.broadcast(snapshot)
            await asyncio.sleep(0.4)  # ~2.5 Hz update frequency
        except asyncio.CancelledError:
            break
        except Exception as e:
            import logging
            logging.error(f"Simulation loop crashed: {e}", exc_info=True)
            await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global sim_task
    # Run initial baseline benchmark to populate comparative metrics
    bridge.run_baseline_benchmark()
    bridge.is_running = True
    sim_task = asyncio.create_task(background_simulation_loop())
    yield
    if sim_task:
        sim_task.cancel()


app = FastAPI(
    title="BEL Defense Depot Multi-Robot Fleet Coordination Gateway",
    description="""
    ## SIH Problem Statement 26123 — Sponsored by Bharat Electronics Limited (BEL)
    Decentralized, edge-AI coordination and collision-avoidance framework for multi-robot warehouse fleets.
    
    ### Key Architectural Capabilities:
    - **Network-Centric Coordination Architecture**: Peer-to-peer telemetry and intent exchange (`fleet/robot/{id}/state`).
    - **Zero Inter-Robot Collisions**: Deterministic local Decision-Support System (DSS) with auditable right-of-way arbitration.
    - **Optimal Task Scheduling**: Hungarian algorithm (`scipy.optimize.linear_sum_assignment`) with heterogeneous payload matching.
    - **Proactive Congestion Avoidance**: Amazon Robotics DeepFleet-style conflict-history penalty tracking.
    - **Defense-Grade Explainability**: Standardized reason codes for all routing and collision decisions.
    - **External Simulator Bridge**: Ingestion endpoints for NVIDIA Isaac Sim / ROS2 bridge.
    """,
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# REST Endpoints
# ==============================================================================

@app.get("/api/fleet/status", tags=["Fleet Status"])
async def get_fleet_status():
    """Returns the complete snapshot of all AMRs, battery, tasks, and layout."""
    return bridge.get_fleet_snapshot()


@app.post("/api/robots/{robot_id}/position", tags=["External Simulation Bridge (Isaac Sim)"])
async def ingest_robot_position(robot_id: str, update: PositionUpdateRequest):
    """
    Integration endpoint for NVIDIA Isaac Sim / ROS2 bridge.
    External 3D simulators push ground-truth coordinates to the coordination backend.
    """
    success = bridge.inject_external_position(
        robot_id=robot_id,
        x=update.x,
        y=update.y,
        heading=update.heading_deg,
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Robot '{robot_id}' not found in fleet.")
    return {"status": "success", "robot_id": robot_id, "position": [update.x, update.y]}


@app.get("/api/metrics/live", tags=["Metrics & Benchmarks"])
async def get_live_metrics():
    """
    Returns live collision counts (enforced ZERO), baseline comparison metrics,
    and the live %-improvement number.
    """
    return bridge.metrics_tracker.get_live_metrics()


@app.get("/api/metrics/congestion-heatmap", tags=["Metrics & Benchmarks"])
async def get_congestion_heatmap():
    """
    Returns rolling conflict-history heatmap data (Amazon Robotics DeepFleet-style).
    Per-cell conflict counts over the last 60 seconds.
    """
    return bridge.metrics_tracker.congestion_tracker.get_heatmap_data()


@app.get("/api/logs/decisions", tags=["Explainability & Audit"])
async def get_decision_logs(limit: int = Query(30, ge=1, le=100)):
    """
    Returns filterable chronological stream of explainable decision logs with reason codes.
    Critical for defense-grade explainability requirements (zero black-box ML).
    """
    return bridge.decision_logs[-limit:]


@app.post("/api/tasks/submit", tags=["Task Management"])
async def submit_warehouse_task(req: TaskSubmitRequest):
    """Submits a new pickup-and-delivery task to the Hungarian allocator queue."""
    priority_enum = TaskPriority(req.priority)
    task = bridge.submit_task(
        pickup_pos=(req.pickup_x, req.pickup_y),
        dropoff_pos=(req.dropoff_x, req.dropoff_y),
        payload_weight_kg=req.payload_weight_kg,
        priority=priority_enum,
    )
    return {"status": "submitted", "task": task.to_dict()}


@app.post("/api/simulation/benchmark", tags=["Simulation Controls"])
async def trigger_benchmark():
    """
    Executes a parallel benchmark comparing the Naive Stop-and-Wait Baseline
    against the Decentralized DSS, measuring the exact completion-time improvement.
    """
    result = bridge.run_baseline_benchmark()
    return result


@app.post("/api/simulation/start", tags=["Simulation Controls"])
async def start_simulation():
    """Resumes the active simulation tick loop."""
    bridge.is_running = True
    return {"is_running": True}


@app.post("/api/simulation/pause", tags=["Simulation Controls"])
async def pause_simulation():
    """Pauses the active simulation tick loop."""
    bridge.is_running = False
    return {"is_running": False}


@app.post("/api/simulation/step", tags=["Simulation Controls"])
async def step_simulation():
    """Advances the simulation by exactly 1 tick manually."""
    snapshot = bridge.step()
    await ws_manager.broadcast(snapshot)
    return snapshot


# ==============================================================================
# WebSocket Endpoint
# ==============================================================================

@app.websocket("/ws/fleet-stream")
async def fleet_stream(websocket: WebSocket):
    """
    High-frequency live WebSocket push stream broadcasting fleet positions,
    intent vectors, conflict alerts, and metrics to the dashboard.
    """
    await ws_manager.connect(websocket)
    try:
        # Send initial snapshot immediately upon connection
        await websocket.send_json(bridge.get_fleet_snapshot())
        while True:
            # Keepalive / client command listener
            data = await websocket.receive_text()
            if data == "step":
                snapshot = bridge.step()
                await ws_manager.broadcast(snapshot)
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


# Mount dashboard static directory
dashboard_dir = Path(__file__).resolve().parent.parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/static", StaticFiles(directory=str(dashboard_dir)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(str(dashboard_dir / "index.html"))
