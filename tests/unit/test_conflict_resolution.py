"""
Unit Tests for Decentralized Local Conflict Resolution Engine (SIH 26123 - Bharat Electronics Limited).
Validates right-of-way arbitration, head-on swap avoidance, 90-degree intersection conflicts,
and deterministic tie-breaking.
"""

import pytest
from services.robot_agent.conflict_resolution import (
    LocalConflictArbiter,
    PeerRobotState,
    DecisionType,
)
from services.robot_agent.reason_codes import ReasonCode


def test_head_on_swap_conflict():
    """
    Two robots moving head-on toward each other.
    AMR-01 (Priority 2) vs AMR-02 (Priority 1):
    AMR-01 should CONTINUE, while AMR-02 should REROUTE / YIELD.
    """
    # AMR-01 at (2, 2) moving to (3, 2)
    arbiter_1 = LocalConflictArbiter(my_id="AMR-01")
    peer_2 = PeerRobotState(
        id="AMR-02",
        current_pos=(3, 2),
        intent_path=[(2, 2)],
        priority_weight=1,
        remaining_distance=5,
    )
    decision_1 = arbiter_1.arbitrate(
        my_pos=(2, 2),
        my_intent=[(3, 2)],
        my_priority=2,
        my_rem_dist=5,
        peer_states={"AMR-02": peer_2},
    )
    assert decision_1.decision_type == DecisionType.CONTINUE
    assert decision_1.reason_code == ReasonCode.RC_CONTINUE_RIGHT_OF_WAY

    # AMR-02 at (3, 2) moving to (2, 2)
    arbiter_2 = LocalConflictArbiter(my_id="AMR-02")
    peer_1 = PeerRobotState(
        id="AMR-01",
        current_pos=(2, 2),
        intent_path=[(3, 2)],
        priority_weight=2,
        remaining_distance=5,
    )
    decision_2 = arbiter_2.arbitrate(
        my_pos=(3, 2),
        my_intent=[(2, 2)],
        my_priority=1,
        my_rem_dist=5,
        peer_states={"AMR-01": peer_1},
    )
    assert decision_2.decision_type == DecisionType.REROUTE
    assert decision_2.reason_code == ReasonCode.RC_YIELD_HEAD_ON_SWAP
    assert decision_2.conflicting_peer_id == "AMR-01"


def test_intersection_90_degree_conflict():
    """
    Two robots converging at an intersection cell (5, 5) at the same future step.
    Equal priority, but AMR-01 is closer to goal than AMR-02.
    AMR-01 should CONTINUE, AMR-02 should YIELD.
    """
    # AMR-01 at (5, 4) moving to (5, 5), remaining distance 2
    arbiter_1 = LocalConflictArbiter(my_id="AMR-01")
    peer_2 = PeerRobotState(
        id="AMR-02",
        current_pos=(4, 5),
        intent_path=[(5, 5), (6, 5)],
        priority_weight=1,
        remaining_distance=8,
    )
    decision_1 = arbiter_1.arbitrate(
        my_pos=(5, 4),
        my_intent=[(5, 5), (5, 6)],
        my_priority=1,
        my_rem_dist=2,
        peer_states={"AMR-02": peer_2},
    )
    assert decision_1.decision_type == DecisionType.CONTINUE
    assert decision_1.reason_code == ReasonCode.RC_CONTINUE_RIGHT_OF_WAY

    # AMR-02 at (4, 5) moving to (5, 5), remaining distance 8
    arbiter_2 = LocalConflictArbiter(my_id="AMR-02")
    peer_1 = PeerRobotState(
        id="AMR-01",
        current_pos=(5, 4),
        intent_path=[(5, 5), (5, 6)],
        priority_weight=1,
        remaining_distance=2,
    )
    decision_2 = arbiter_2.arbitrate(
        my_pos=(4, 5),
        my_intent=[(5, 5), (6, 5)],
        my_priority=1,
        my_rem_dist=8,
        peer_states={"AMR-01": peer_1},
    )
    assert decision_2.decision_type == DecisionType.YIELD
    assert decision_2.reason_code == ReasonCode.RC_YIELD_INTERSECTION_CONFLICT
    assert decision_2.conflicting_peer_id == "AMR-01"


def test_deterministic_tie_breaking():
    """
    Identical priorities and identical remaining distance.
    Lexicographical comparison: 'AMR-01' < 'AMR-02' => AMR-01 wins.
    """
    arbiter_1 = LocalConflictArbiter(my_id="AMR-01")
    peer_2 = PeerRobotState(
        id="AMR-02",
        current_pos=(4, 5),
        intent_path=[(5, 5)],
        priority_weight=1,
        remaining_distance=4,
    )
    dec_1 = arbiter_1.arbitrate(
        my_pos=(5, 4),
        my_intent=[(5, 5)],
        my_priority=1,
        my_rem_dist=4,
        peer_states={"AMR-02": peer_2},
    )
    assert dec_1.decision_type == DecisionType.CONTINUE

    arbiter_2 = LocalConflictArbiter(my_id="AMR-02")
    peer_1 = PeerRobotState(
        id="AMR-01",
        current_pos=(5, 4),
        intent_path=[(5, 5)],
        priority_weight=1,
        remaining_distance=4,
    )
    dec_2 = arbiter_2.arbitrate(
        my_pos=(4, 5),
        my_intent=[(5, 5)],
        my_priority=1,
        my_rem_dist=4,
        peer_states={"AMR-01": peer_1},
    )
    assert dec_2.decision_type == DecisionType.YIELD


def test_cell_currently_occupied_yield():
    """If target immediate next cell is currently occupied, robot must WAIT."""
    arbiter = LocalConflictArbiter(my_id="AMR-01")
    peer = PeerRobotState(
        id="AMR-02",
        current_pos=(3, 3),
        intent_path=[(4, 3)],
        priority_weight=1,
        remaining_distance=5,
    )
    decision = arbiter.arbitrate(
        my_pos=(2, 3),
        my_intent=[(3, 3), (4, 3)],
        my_priority=1,
        my_rem_dist=5,
        peer_states={"AMR-02": peer},
    )
    assert decision.decision_type == DecisionType.WAIT
    assert decision.reason_code == ReasonCode.RC_WAIT_CLEARANCE
