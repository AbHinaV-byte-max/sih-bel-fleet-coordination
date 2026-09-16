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


@app.get("/api/metrics/maintenance", tags=["Metrics & Benchmarks"])
async def get_maintenance_status():
    """
    Returns full per-robot predictive maintenance status.

    LAYERS:
    - **Threshold layer** (always active): odometer, cycle count, battery floor hard-limits.
    - **Isolation Forest layer** (activates after 50 baseline samples per robot):
      anomaly_score, predicted_failure_type, estimated_days_to_failure, reasoning.

    RESEARCH BASIS: 2026 industry case study showed 97%→81% uptime collapse in a 60-unit
    AMR fleet due to absent predictive maintenance. Isolation Forest detects battery
    discharge rate anomalies, drive wear signatures, and LiDAR sensor drift 4-6 days
    before failure — delivering ~78% reduction in unplanned downtime.
    """
    health = bridge.metrics_tracker.get_live_metrics().get("robots_health", {})
    alerts = [
        {"robot_id": r_id, **data}
        for r_id, data in health.items()
        if data.get("needs_attention") or data.get("is_anomaly")
    ]
    return {
        "robots_health": health,
        "active_alerts": alerts,
        "total_alerts": len(alerts),
    }


@app.get("/api/model/status", tags=["Metrics & Benchmarks"])
async def get_model_status():
    """
    Returns the status of the Hybrid AI Priority Model (DecisionTreeClassifier).

    Reports whether the trained model is loaded (requires running
    scripts/generate_training_data.py then scripts/train_priority_model.py),
    plus validation accuracy and feature importances if the model file exists.
    """
    import os
    import json

    metrics_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "models", "validation_metrics.json"
    )
    model_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "models", "priority_model.pkl"
    )

    # Check if any robot agent has the model loaded
    first_agent = next(iter(bridge.robots.values()), None)
    model_active = first_agent.hybrid_advisor.is_model_active if first_agent else False

    result = {
        "hybrid_priority_model_active": model_active,
        "model_file_exists": os.path.exists(os.path.abspath(model_path)),
        "research_note": (
            "Implements RL-guided Prioritized Planning pattern (MAPF research 2025/2026): "
            "DecisionTreeClassifier(max_depth=5) adjusts yield_priority_weight before "
            "deterministic LocalConflictArbiter.arbitrate() runs. Zero-collision guarantee "
            "is architecturally preserved — the learned layer feeds inputs to the arbiter, "
            "never overrides its safety output."
        ),
        "next_steps_if_inactive": [
            "python scripts/generate_training_data.py",
            "python scripts/train_priority_model.py",
            "Restart server: python -m uvicorn services.api_gateway.app:app --port 8000",
        ],
    }

    metrics_abs = os.path.abspath(metrics_path)
    if os.path.exists(metrics_abs):
        try:
            with open(metrics_abs) as f:
                saved = json.load(f)
            result["validation_accuracy"] = saved.get("validation_accuracy")
            result["feature_importances"] = saved.get("feature_importances")
            result["n_train_samples"] = saved.get("n_train_samples")
            result["max_depth"] = saved.get("max_depth")
        except Exception:
            pass

    return result


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


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(..., description="Scenario ID: S1, S2, S3, S4, S5, S6, S7, S8, S9, or S10")
    seed: int = Field(42, description="Random seed for reproducibility")


class DynamicObstacleRequest(BaseModel):
    x: int
    y: int
    action: str = Field("add", description="'add' or 'remove'")


class SimulatorCommandRequest(BaseModel):
    command: str = Field(..., description="Command type: 'reset', 'speed', 'pause', 'resume'")
    params: dict = Field(default_factory=dict)


@app.post("/api/scenarios/run", tags=["Simulation Controls"])
async def run_scenario(req: ScenarioRequest):
    """
    Executes a named scenario from the S1–S10 taxonomy (§14) with a reproducible seed.
    Each scenario modifies the environment to produce specific coordination challenges:
    - S1: Normal traffic | S2: Crossing conflict | S3: Narrow aisle | S4: Deadlock
    - S5: Blocked aisle | S6: Robot failure | S7: Comms degradation | S8: Emergency task
    - S9: Battery constraint | S10: Congestion concentration
    """
    result = bridge.run_scenario(scenario_id=req.scenario_id, seed=req.seed)
    snapshot = bridge.get_fleet_snapshot()
    await ws_manager.broadcast(snapshot)
    return result


@app.post("/api/obstacles/dynamic", tags=["Simulation Controls"])
async def manage_dynamic_obstacle(req: DynamicObstacleRequest):
    """
    Adds or removes a dynamic obstacle (§8.3) at a given grid cell.
    Dynamic obstacles represent fallen boxes, blocked aisles, or temporary restricted zones.
    All robot A* pathfinders are updated immediately.
    """
    cell = (req.x, req.y)
    if req.action == "add":
        result = bridge.add_dynamic_obstacle(cell)
        action_done = "added"
    elif req.action == "remove":
        result = bridge.remove_dynamic_obstacle(cell)
        action_done = "removed"
    else:
        raise HTTPException(status_code=400, detail="action must be 'add' or 'remove'")
    snapshot = bridge.get_fleet_snapshot()
    await ws_manager.broadcast(snapshot)
    return {"status": "success", "action": action_done, "cell": list(cell), "total_dynamic": len(bridge.dynamic_obstacles)}


@app.post("/api/simulator/command", tags=["External Simulation Bridge (Isaac Sim / Omniverse)"])
async def simulator_command(req: SimulatorCommandRequest):
    """
    Omniverse / Isaac Sim bridge command endpoint (§8.5).
    Supports: 'reset' (reset all robot positions), 'speed' (set sim speed factor),
    'pause' / 'resume' (control sim loop).
    """
    if req.command == "reset":
        for robot in bridge.robots.values():
            robot.current_pos = robot.pathfinder.start_pos if hasattr(robot.pathfinder, 'start_pos') else (0, 0)
        return {"status": "reset"}
    elif req.command == "speed":
        factor = req.params.get("factor", 1.0)
        bridge.sim_speed_factor = float(factor)
        return {"status": "ok", "sim_speed_factor": bridge.sim_speed_factor}
    elif req.command == "pause":
        bridge.is_running = False
        return {"status": "paused"}
    elif req.command == "resume":
        bridge.is_running = True
        return {"status": "running"}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown command: {req.command}")


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
        return FileResponse(
            str(dashboard_dir / "index.html"),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
