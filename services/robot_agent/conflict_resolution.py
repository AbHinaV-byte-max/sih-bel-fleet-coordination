"""
Decentralized Local Conflict Resolution Engine (SIH 26123 - Bharat Electronics Limited).
Decision-Support System (DSS) executing locally on edge AMR processes.

NO CENTRAL ARBITER: Each robot evaluates peer broadcasts and makes autonomous,
explainable local arbitration decisions (CONTINUE / YIELD / WAIT / REROUTE).
Zero black-box ML: 100% deterministic, auditable right-of-way protocol.
"""

from enum import Enum
from typing import List, Tuple, Dict, Optional, Any
from dataclasses import dataclass
import time

from .reason_codes import ReasonCode


class DecisionType(str, Enum):
    CONTINUE = "CONTINUE"
    YIELD = "YIELD"
    WAIT = "WAIT"
    REROUTE = "REROUTE"


@dataclass
class ConflictDecision:
    decision_type: DecisionType
    reason_code: ReasonCode
    conflicting_peer_id: Optional[str]
    conflict_pos: Optional[Tuple[int, int]]
    time_horizon_step: int
    explanation: str
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_type": self.decision_type.value,
            "reason_code": self.reason_code.value,
            "conflicting_peer_id": self.conflicting_peer_id,
            "conflict_pos": list(self.conflict_pos) if self.conflict_pos else None,
            "time_horizon_step": self.time_horizon_step,
            "explanation": self.explanation,
            "timestamp": self.timestamp,
        }


@dataclass
class PeerRobotState:
    id: str
    current_pos: Tuple[int, int]
    intent_path: List[Tuple[int, int]]  # Next N planned waypoints
    priority_weight: int = 1
    remaining_distance: int = 10
    speed: float = 1.0
    state: str = "MOVING"


class LocalConflictArbiter:
    """
    Decentralized Decision-Support System for multi-agent collision avoidance.
    Runs locally on each AMR without consulting any centralized coordinator.
    """

    def __init__(self, my_id: str, intent_horizon: int = 5):
        self.my_id = my_id
        self.intent_horizon = intent_horizon
        self.wait_ticks_counter: int = 0
        self.max_wait_ticks_before_reroute: int = 3

    def evaluate_right_of_way(
        self,
        my_priority: int,
        my_rem_dist: int,
        peer_id: str,
        peer_priority: int,
        peer_rem_dist: int,
    ) -> bool:
        """
        Deterministic, auditable right-of-way protocol:
        1. Higher priority weight wins (e.g. heavy payload or high-priority order).
        2. If tied, closer remaining distance to goal wins (clears intersection faster).
        3. If tied, deterministic tie-breaker on robot ID string comparison.
        """
        if my_priority != peer_priority:
            return my_priority > peer_priority
        if my_rem_dist != peer_rem_dist:
            return my_rem_dist < peer_rem_dist
        return self.my_id < peer_id

    def arbitrate(
        self,
        my_pos: Tuple[int, int],
        my_intent: List[Tuple[int, int]],
        my_priority: int,
        my_rem_dist: int,
        peer_states: Dict[str, PeerRobotState],
    ) -> ConflictDecision:
        """
        Evaluates peer intents against own intent up to intent_horizon steps ahead.
        Detects head-on swap collisions, intersection contention, and choke point deadlocks.
        """
        if not my_intent:
            return ConflictDecision(
                decision_type=DecisionType.CONTINUE,
                reason_code=ReasonCode.RC_MOVING_NOMINAL,
                conflicting_peer_id=None,
                conflict_pos=None,
                time_horizon_step=0,
                explanation=f"Robot {self.my_id}: No forward intent planned. Nominal idle.",
            )

        horizon = min(self.intent_horizon, len(my_intent))
        best_continue_decision: Optional[ConflictDecision] = None

        for step in range(horizon):
            my_cell = my_intent[step]

            for peer_id, peer in peer_states.items():
                if peer_id == self.my_id:
                    continue

                # Check 1: Head-on edge swap collision (Swap at step 0)
                # Robot A is at P1 moving to P2, Robot B is at P2 moving to P1
                is_head_on_swap = False
                if step == 0 and len(peer.intent_path) > 0:
                    peer_next_cell = peer.intent_path[0]
                    if my_cell == peer.current_pos and peer_next_cell == my_pos:
                        is_head_on_swap = True
                        i_have_row = self.evaluate_right_of_way(
                            my_priority, my_rem_dist, peer_id, peer.priority_weight, peer.remaining_distance
                        )
                        if i_have_row:
                            if best_continue_decision is None:
                                best_continue_decision = ConflictDecision(
                                    decision_type=DecisionType.CONTINUE,
                                    reason_code=ReasonCode.RC_CONTINUE_RIGHT_OF_WAY,
                                    conflicting_peer_id=peer_id,
                                    conflict_pos=my_cell,
                                    time_horizon_step=step,
                                    explanation=f"Robot {self.my_id}: CONTINUE — right-of-way maintained over {peer_id} in head-on encounter at {my_cell}.",
                                )
                        else:
                            return ConflictDecision(
                                decision_type=DecisionType.REROUTE,
                                reason_code=ReasonCode.RC_YIELD_HEAD_ON_SWAP,
                                conflicting_peer_id=peer_id,
                                conflict_pos=my_cell,
                                time_horizon_step=step,
                                explanation=f"Robot {self.my_id}: REROUTE — dynamic detour to avoid head-on swap collision with {peer_id} between {my_pos} and {my_cell}.",
                            )

                # Check 2: Contention on current cell (Peer already occupies my target cell)
                if not is_head_on_swap and step == 0 and my_cell == peer.current_pos:
                    self.wait_ticks_counter += 1
                    if self.wait_ticks_counter >= self.max_wait_ticks_before_reroute:
                        self.wait_ticks_counter = 0
                        return ConflictDecision(
                            decision_type=DecisionType.REROUTE,
                            reason_code=ReasonCode.RC_REROUTE_DYNAMIC,
                            conflicting_peer_id=peer_id,
                            conflict_pos=my_cell,
                            time_horizon_step=0,
                            explanation=f"Robot {self.my_id}: REROUTE — {peer_id} stationary at {my_cell} exceeded wait threshold ({self.max_wait_ticks_before_reroute} ticks).",
                        )
                    return ConflictDecision(
                        decision_type=DecisionType.WAIT,
                        reason_code=ReasonCode.RC_WAIT_CLEARANCE,
                        conflicting_peer_id=peer_id,
                        conflict_pos=my_cell,
                        time_horizon_step=0,
                        explanation=f"Robot {self.my_id}: WAIT — waiting for {peer_id} to vacate immediate forward cell {my_cell}.",
                    )

                # Check 3: Future space-time cell contention (Both planning same cell at step t)
                if step < len(peer.intent_path):
                    peer_cell = peer.intent_path[step]
                    if my_cell == peer_cell:
                        i_have_row = self.evaluate_right_of_way(
                            my_priority, my_rem_dist, peer_id, peer.priority_weight, peer.remaining_distance
                        )
                        if i_have_row:
                            if best_continue_decision is None:
                                best_continue_decision = ConflictDecision(
                                    decision_type=DecisionType.CONTINUE,
                                    reason_code=ReasonCode.RC_CONTINUE_RIGHT_OF_WAY,
                                    conflicting_peer_id=peer_id,
                                    conflict_pos=my_cell,
                                    time_horizon_step=step + 1,
                                    explanation=f"Robot {self.my_id}: CONTINUE — right-of-way maintained at intersection {my_cell} (T+{step+1}) over {peer_id}.",
                                )
                        else:
                            # If conflict is detected, pause or yield to let winner pass
                            self.wait_ticks_counter += 1
                            if self.wait_ticks_counter >= self.max_wait_ticks_before_reroute:
                                self.wait_ticks_counter = 0
                                return ConflictDecision(
                                    decision_type=DecisionType.REROUTE,
                                    reason_code=ReasonCode.RC_REROUTE_DYNAMIC,
                                    conflicting_peer_id=peer_id,
                                    conflict_pos=my_cell,
                                    time_horizon_step=step + 1,
                                    explanation=f"Robot {self.my_id}: REROUTE — persistent conflict at {my_cell} with {peer_id}; calculating alternative corridor.",
                                )
                            return ConflictDecision(
                                decision_type=DecisionType.YIELD,
                                reason_code=ReasonCode.RC_YIELD_INTERSECTION_CONFLICT,
                                conflicting_peer_id=peer_id,
                                conflict_pos=my_cell,
                                time_horizon_step=step + 1,
                                explanation=f"Robot {self.my_id}: YIELD — yielding at intersection {my_cell} (T+{step+1}) to {peer_id} under right-of-way protocol.",
                            )

        # If any encounter gave us right-of-way and we had no conflicting yield/reroute/wait:
        if best_continue_decision is not None:
            self.wait_ticks_counter = 0
            return best_continue_decision

        # No conflicts detected in horizon
        self.wait_ticks_counter = 0
        return ConflictDecision(
            decision_type=DecisionType.CONTINUE,
            reason_code=ReasonCode.RC_MOVING_NOMINAL,
            conflicting_peer_id=None,
            conflict_pos=None,
            time_horizon_step=0,
            explanation=f"Robot {self.my_id}: CONTINUE — trajectory clear across {horizon}-step horizon.",
        )
