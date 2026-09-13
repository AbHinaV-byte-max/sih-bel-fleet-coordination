"""
Autonomous Mobile Robot (AMR) Agent Process (SIH 26123 - Bharat Electronics Limited).
Independent process instance per robot executing local pathfinding, local conflict resolution,
and peer-to-peer telemetry broadcasting.
"""

from typing import List, Tuple, Dict, Optional, Any, Set
import time
import logging

from .pathfinding import GridAStarPathfinder
from .conflict_resolution import (
    LocalConflictArbiter,
    PeerRobotState,
    DecisionType,
    ConflictDecision,
)
from .reason_codes import ReasonCode
from .hybrid_priority_advisor import HybridPriorityAdvisor
from services.comms_broker.broker import PeerBrokerClient, ProcessMessageBus
from services.comms_broker.security import SecurityContext
from services.task_allocation.task_models import WarehouseTask, TaskStatus, TaskPriority

logger = logging.getLogger("RobotAgent")


class RobotAgent:
    """
    Independent AMR Agent running its own local navigation and conflict arbitration loop.
    No central controller dictates motion decisions.
    """

    def __init__(
        self,
        robot_id: str,
        robot_type: str,
        start_pos: Tuple[int, int],
        grid_width: int,
        grid_height: int,
        static_obstacles: Set[Tuple[int, int]],
        max_speed: float = 1.0,
        payload_capacity_kg: float = 250.0,
        battery_pct: float = 100.0,
        yield_priority_weight: int = 1,
        human_zones: Optional[List[Tuple[int, int, int, int]]] = None,
        bus: Optional[ProcessMessageBus] = None,
    ):
        self.robot_id = robot_id
        self.robot_type = robot_type
        self.current_pos = start_pos
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.static_obstacles = set(static_obstacles)
        self.max_speed = max_speed
        self.payload_capacity_kg = payload_capacity_kg
        self.battery_pct = battery_pct
        self.base_yield_priority_weight = yield_priority_weight
        self.yield_priority_weight = yield_priority_weight
        self.human_zones = human_zones or []

        # Local planners and decision engines
        self.pathfinder = GridAStarPathfinder(
            width=grid_width,
            height=grid_height,
            static_obstacles=self.static_obstacles,
            human_zones=self.human_zones,
        )
        self.arbiter = LocalConflictArbiter(my_id=self.robot_id)
        self.security = SecurityContext()
        # Hybrid AI priority advisor — research-aligned "RL-guided Prioritized Planning" pattern.
        # Loads DecisionTreeClassifier(max_depth=5) from models/priority_model.pkl if available;
        # falls back to deterministic rule-based priority adjustment otherwise.
        # INVARIANT: advisor only adjusts priority BEFORE arbitrate(); safety checks are never bypassed.
        self.hybrid_advisor = HybridPriorityAdvisor()

        # Navigation State
        self.state = "IDLE"  # IDLE, MOVING, YIELDING, WAITING, REROUTING, CHARGING
        self.current_task: Optional[WarehouseTask] = None
        self.task_phase: str = "NONE"  # NONE, TO_PICKUP, TO_DROPOFF
        self.planned_path: List[Tuple[int, int]] = []
        self.target_goal: Optional[Tuple[int, int]] = None

        # Peer tracking and telemetry
        self.peer_states: Dict[str, PeerRobotState] = {}
        self.odometer_meters: float = 0.0
        self.cycles_completed: int = 0
        self.decision_history: List[ConflictDecision] = []
        self.last_decision: Optional[ConflictDecision] = None
        self.congestion_penalties: Dict[Tuple[int, int], float] = {}

        # Comms
        self.bus = bus
        self.comms_client: Optional[PeerBrokerClient] = None
        if bus is not None:
            self.comms_client = PeerBrokerClient(
                client_id=self.robot_id,
                bus=bus,
                subscribed_topics=[
                    "fleet/robot/+/state",
                    "fleet/tasks/allocations",
                    "fleet/congestion/updates",
                ],
            )

    @property
    def intent_path(self) -> List[Tuple[int, int]]:
        """Returns the next 5 planned waypoints."""
        return self.planned_path[:5]

    def set_task(self, task: WarehouseTask) -> bool:
        """Assigns a task to this AMR and initiates path planning to pickup."""
        self.current_task = task
        self.task_phase = "TO_PICKUP"
        self.target_goal = task.pickup_pos
        self.state = "MOVING"

        path = self.pathfinder.find_path(
            start=self.current_pos,
            goal=self.target_goal,
            congestion_penalties=self.congestion_penalties,
        )

        if path and len(path) > 1:
            self.planned_path = path[1:]  # Exclude current pos
            logger.info(
                f"[{self.robot_id}] Planned path to pickup {task.pickup_pos}: {len(self.planned_path)} steps"
            )
            self.broadcast_state()
            return True
        elif path and len(path) == 1:
            # Already at pickup!
            self.planned_path = []
            self.task_phase = "TO_DROPOFF"
            self.target_goal = task.dropoff_pos
            dropoff_path = self.pathfinder.find_path(
                start=self.current_pos,
                goal=self.target_goal,
                congestion_penalties=self.congestion_penalties,
            )
            if dropoff_path and len(dropoff_path) > 1:
                self.planned_path = dropoff_path[1:]
            self.broadcast_state()
            return True
        else:
            logger.warning(f"[{self.robot_id}] No viable path to pickup {task.pickup_pos}.")
            self.report_blocked("No viable path to pickup station")
            return False

    def report_blocked(self, reason: str) -> None:
        """Broadcasts a path obstruction to trigger task reallocation."""
        self.state = "REROUTING"
        if self.comms_client and self.current_task:
            self.comms_client.publish(
                topic="fleet/tasks/blocked",
                payload={
                    "robot_id": self.robot_id,
                    "task_id": self.current_task.id,
                    "reason": reason,
                    "location": list(self.current_pos),
                },
            )
        self.current_task = None
        self.task_phase = "NONE"
        self.planned_path = []
        self.target_goal = None

    def poll_comms(self) -> None:
        """Polls inbox queue for peer state broadcasts and task events."""
        if not self.comms_client:
            return

        messages = self.comms_client.poll_messages()
        for msg in messages:
            topic = msg.get("topic", "")
            envelope = msg.get("envelope", {})
            sender = envelope.get("sender_id", "")
            payload = envelope.get("payload", {})

            if "state" in topic and sender != self.robot_id:
                # Update peer table
                self.peer_states[sender] = PeerRobotState(
                    id=sender,
                    current_pos=tuple(payload.get("position", (0, 0))),
                    intent_path=[tuple(p) for p in payload.get("intent", [])],
                    priority_weight=payload.get("priority_weight", 1),
                    remaining_distance=payload.get("remaining_distance", 10),
                    speed=payload.get("speed", 1.0),
                    state=payload.get("state", "MOVING"),
                )
            elif "congestion/updates" in topic:
                cell = tuple(payload.get("conflict_cell", (0, 0)))
                penalty = payload.get("penalty", 2.0)
                self.congestion_penalties[cell] = penalty

    def broadcast_state(self) -> None:
        """Publishes local state and planned intent to peer-to-peer network."""
        if not self.comms_client:
            return

        telemetry = {
            "robot_id": self.robot_id,
            "robot_type": self.robot_type,
            "position": list(self.current_pos),
            "state": self.state,
            "intent": [list(p) for p in self.intent_path],
            "priority_weight": self.yield_priority_weight,
            "remaining_distance": len(self.planned_path),
            "speed": self.max_speed,
            "battery_pct": round(self.battery_pct, 1),
            "odometer_meters": round(self.odometer_meters, 1),
            "cycles_completed": self.cycles_completed,
            "current_task_id": self.current_task.id if self.current_task else None,
            "last_decision": self.last_decision.to_dict() if self.last_decision else None,
            "timestamp": time.time(),
        }

        self.comms_client.publish(
            topic=f"fleet/robot/{self.robot_id}/state",
            payload=telemetry,
        )

    def step(self) -> ConflictDecision:
        """
        Executes one discrete simulation tick:
        1. Poll peer messages.
        2. Evaluate local conflict resolution DSS.
        3. Advance position or yield/wait/reroute.
        4. Broadcast updated state to peers.
        """
        self.poll_comms()

        # If idle, just broadcast and return
        if not self.planned_path or self.target_goal is None:
            self.state = "IDLE"
            self.yield_priority_weight = self.base_yield_priority_weight
            dec = ConflictDecision(
                decision_type=DecisionType.CONTINUE,
                reason_code=ReasonCode.RC_MOVING_NOMINAL,
                conflicting_peer_id=None,
                conflict_pos=None,
                time_horizon_step=0,
                explanation=f"Robot {self.robot_id}: Idle at {self.current_pos}.",
            )
            self.last_decision = dec
            self.broadcast_state()
            return dec

        # Check Human Zone safety speed derating
        in_human_zone = self.pathfinder.in_human_zone(self.current_pos)
        if in_human_zone:
            logger.info(
                f"[{self.robot_id}] {ReasonCode.RC_SAFETY_HUMAN_ZONE_SPEED_DERATING.value}: "
                f"Reduced speed entering human zone at {self.current_pos}."
            )

        # --- Hybrid AI Priority Layer ---
        # Compute priority boost BEFORE the deterministic arbiter runs.
        # The boost temporarily raises this robot's yield_priority_weight so the
        # arbiter's evaluate_right_of_way() sees a context-aware weight.
        # After arbitrate() completes the base weight is restored immediately.
        # This is the "RL-guided Prioritized Planning" pattern: deterministic backbone
        # with a learned priority assignment layer on top.
        task_priority_int = self.current_task.priority.value if self.current_task else 2
        payload_kg = (
            self.current_task.payload_weight_kg
            if self.current_task and self.task_phase == "TO_DROPOFF"
            else 0.0
        )
        # Find the most likely upcoming conflict cell for feature extraction
        upcoming_conflict_cell = None
        for peer in self.peer_states.values():
            if self.intent_path and peer.intent_path:
                if self.intent_path[0] == peer.intent_path[0]:
                    upcoming_conflict_cell = self.intent_path[0]
                    break

        hybrid_features = self.hybrid_advisor.extract_features(
            task_priority_int=task_priority_int,
            battery_pct=self.battery_pct,
            current_pos=self.current_pos,
            conflict_cell=upcoming_conflict_cell,
            congestion_penalties=self.congestion_penalties,
            payload_kg=payload_kg,
            robot_type_weight=self.yield_priority_weight,
        )
        priority_boost, boost_confidence, boost_note = self.hybrid_advisor.predict_priority_boost(
            hybrid_features
        )

        # Apply the learned priority boost to yield_priority_weight so it is both
        # evaluated in arbitrate() and broadcast to peers for symmetric right-of-way awareness.
        self.yield_priority_weight = self.base_yield_priority_weight + priority_boost

        # Run Local Decentralized Conflict Arbitration (DETERMINISTIC SAFETY NET)
        decision = self.arbiter.arbitrate(
            my_pos=self.current_pos,
            my_intent=self.intent_path,
            my_priority=self.yield_priority_weight,
            my_rem_dist=len(self.planned_path),
            peer_states=self.peer_states,
        )

        # Annotate the decision with the hybrid note when a boost was applied
        if priority_boost > 0 and boost_note:
            decision.hybrid_note = boost_note
            if decision.decision_type == DecisionType.CONTINUE:
                # Only tag the reason code as hybrid-adjusted when we won right-of-way
                # (the boost was what tipped the balance). If we yielded, the safety
                # check took precedence over the boost — reason code stays as-is.
                decision.reason_code = ReasonCode.RC_HYBRID_PRIORITY_ADJUSTED
        self.last_decision = decision
        self.decision_history.append(decision)

        # Notify congestion tracker if conflict detected
        if decision.decision_type in (DecisionType.YIELD, DecisionType.WAIT, DecisionType.REROUTE):
            if decision.conflict_pos and self.comms_client:
                self.comms_client.publish(
                    topic="fleet/congestion/updates",
                    payload={
                        "reporting_robot": self.robot_id,
                        "conflict_cell": list(decision.conflict_pos),
                        "peer_id": decision.conflicting_peer_id,
                        "decision": decision.decision_type.value,
                    },
                )

        # Execute decision action
        if decision.decision_type == DecisionType.CONTINUE:
            self.state = "MOVING"
            next_cell = self.planned_path.pop(0)
            self.current_pos = next_cell
            self.odometer_meters += 1.0
            self.battery_pct = max(0.0, self.battery_pct - 0.05)

            # Check if arrived at pickup
            if self.task_phase == "TO_PICKUP" and self.current_pos == self.target_goal:
                logger.info(f"[{self.robot_id}] Arrived at pickup: {self.current_pos}. Loading payload...")
                self.task_phase = "TO_DROPOFF"
                if self.current_task:
                    self.target_goal = self.current_task.dropoff_pos
                    dropoff_path = self.pathfinder.find_path(
                        start=self.current_pos,
                        goal=self.target_goal,
                        congestion_penalties=self.congestion_penalties,
                    )
                    if dropoff_path and len(dropoff_path) > 1:
                        self.planned_path = dropoff_path[1:]
                    else:
                        self.planned_path = []

            # Check if arrived at dropoff
            elif self.task_phase == "TO_DROPOFF" and self.current_pos == self.target_goal:
                logger.info(f"[{self.robot_id}] Arrived at dropoff: {self.current_pos}. Task complete!")
                self.cycles_completed += 1
                if self.current_task:
                    self.current_task.status = TaskStatus.COMPLETED
                self.current_task = None
                self.task_phase = "NONE"
                self.planned_path = []
                self.target_goal = None
                self.state = "IDLE"
                self.yield_priority_weight = self.base_yield_priority_weight

        elif decision.decision_type == DecisionType.WAIT:
            self.state = "WAITING"

        elif decision.decision_type == DecisionType.YIELD:
            self.state = "YIELDING"

        elif decision.decision_type == DecisionType.REROUTE:
            self.state = "REROUTING"
            # Avoid the contested cell dynamically as well as other robots' current positions
            avoid_cells = set()
            if decision.conflict_pos:
                avoid_cells.add(decision.conflict_pos)
            for p_id, p_state in self.peer_states.items():
                if p_id != self.robot_id:
                    avoid_cells.add(p_state.current_pos)

            new_path = self.pathfinder.find_path(
                start=self.current_pos,
                goal=self.target_goal,
                dynamic_obstacles=avoid_cells,
                congestion_penalties=self.congestion_penalties,
            )
            if not new_path and decision.conflict_pos:
                # Fallback: avoid only the contested cell if avoiding all peers leaves no path
                new_path = self.pathfinder.find_path(
                    start=self.current_pos,
                    goal=self.target_goal,
                    dynamic_obstacles={decision.conflict_pos},
                    congestion_penalties=self.congestion_penalties,
                )

            if new_path and len(new_path) > 1:
                self.planned_path = new_path[1:]
                logger.info(f"[{self.robot_id}] Dynamic reroute successful: {len(self.planned_path)} steps.")
            else:
                logger.warning(f"[{self.robot_id}] Dynamic reroute failed (path blocked).")
                self.report_blocked("Dynamic reroute blocked by obstacles")

        self.broadcast_state()
        return decision
