"""
Unit Tests: Hybrid AI Priority Advisor (SIH 26123 - BEL).

CRITICAL INVARIANT TESTED: The hybrid layer can ONLY re-rank priority among
safe options. It can never bypass the deterministic safety check. Even with
the maximum boost (+2), if the deterministic arbiter decides YIELD or WAIT,
that decision stands.
"""

import pytest
from unittest.mock import patch, MagicMock

from services.robot_agent.hybrid_priority_advisor import (
    HybridPriorityAdvisor,
    PriorityFeatures,
)
from services.robot_agent.conflict_resolution import (
    LocalConflictArbiter,
    PeerRobotState,
    DecisionType,
    ConflictDecision,
)
from services.robot_agent.reason_codes import ReasonCode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_features(
    task_urgency=0.5,
    battery_pct=80.0,
    distance_to_conflict=3,
    congestion_score=2.0,
    payload_kg=50.0,
    robot_type_weight=1,
) -> PriorityFeatures:
    return PriorityFeatures(
        task_urgency=task_urgency,
        battery_pct=battery_pct,
        distance_to_conflict=distance_to_conflict,
        congestion_score=congestion_score,
        payload_kg=payload_kg,
        robot_type_weight=robot_type_weight,
    )


# ---------------------------------------------------------------------------
# Test 1: Boost is always bounded to valid range {0, 1, 2}
# ---------------------------------------------------------------------------

class TestBoostBounds:
    def test_boost_never_below_zero(self):
        advisor = HybridPriorityAdvisor(model_path="nonexistent_model.pkl")
        features = make_features(task_urgency=0.0, battery_pct=100.0, congestion_score=0.0)
        boost, _, _ = advisor.predict_priority_boost(features)
        assert boost >= 0, f"Boost must never be negative, got {boost}"

    def test_boost_never_above_two(self):
        advisor = HybridPriorityAdvisor(model_path="nonexistent_model.pkl")
        # Even maximum urgency + low battery + heavy load should cap at 2
        features = make_features(
            task_urgency=1.0, battery_pct=5.0,
            payload_kg=300.0, congestion_score=20.0, robot_type_weight=4
        )
        boost, _, _ = advisor.predict_priority_boost(features)
        assert boost <= HybridPriorityAdvisor.BOOST_HIGH, (
            f"Boost must never exceed BOOST_HIGH={HybridPriorityAdvisor.BOOST_HIGH}, got {boost}"
        )

    def test_boost_is_integer(self):
        advisor = HybridPriorityAdvisor(model_path="nonexistent_model.pkl")
        features = make_features()
        boost, _, _ = advisor.predict_priority_boost(features)
        assert isinstance(boost, int), f"Boost must be int, got {type(boost)}"

    def test_boost_in_valid_set(self):
        """Boost must always be one of {0, 1, 2} regardless of features."""
        advisor = HybridPriorityAdvisor(model_path="nonexistent_model.pkl")
        test_cases = [
            make_features(task_urgency=0.0),
            make_features(task_urgency=0.5),
            make_features(task_urgency=0.75),
            make_features(task_urgency=1.0),
            make_features(battery_pct=10.0),
            make_features(payload_kg=200.0, congestion_score=15.0),
        ]
        for feat in test_cases:
            boost, _, _ = advisor.predict_priority_boost(feat)
            assert boost in {0, 1, 2}, f"Invalid boost value: {boost}"


# ---------------------------------------------------------------------------
# Test 2: System works correctly without a trained model file (fallback mode)
# ---------------------------------------------------------------------------

class TestFallbackWithoutModel:
    def test_fallback_when_no_model_file(self):
        """Advisor must work with rule-based fallback when no .pkl exists."""
        advisor = HybridPriorityAdvisor(model_path="/nonexistent/path/model.pkl")
        assert not advisor.is_model_active
        features = make_features(task_urgency=0.8, battery_pct=90.0)
        boost, confidence, _ = advisor.predict_priority_boost(features)
        assert isinstance(boost, int)
        assert 0.0 <= confidence <= 1.0

    def test_fallback_critical_urgency_gives_boost(self):
        """Rule-based fallback: task_urgency >= 0.75 should always give boost > 0."""
        advisor = HybridPriorityAdvisor(model_path="/nonexistent/path/model.pkl")
        features = make_features(task_urgency=0.8, battery_pct=90.0)
        boost, _, _ = advisor.predict_priority_boost(features)
        assert boost > 0, "Critical urgency (>=0.75) should produce boost > 0 in fallback"

    def test_fallback_low_urgency_no_boost(self):
        """Rule-based fallback: low urgency + good battery + low congestion = no boost."""
        advisor = HybridPriorityAdvisor(model_path="/nonexistent/path/model.pkl")
        features = make_features(task_urgency=0.25, battery_pct=95.0, congestion_score=0.5)
        boost, _, _ = advisor.predict_priority_boost(features)
        assert boost == 0, "Low urgency/congestion should produce no boost in fallback"


# ---------------------------------------------------------------------------
# Test 3: Hybrid note appears in decision when boost > 0
# ---------------------------------------------------------------------------

class TestExplanationString:
    def test_no_explanation_when_no_boost(self):
        """When boost == 0, _build_explanation must return None."""
        result = HybridPriorityAdvisor._build_explanation(
            make_features(task_urgency=0.1), boost=0, confidence=0.9, learned=False
        )
        assert result is None

    def test_explanation_contains_key_fields_when_boosted(self):
        """Explanation must mention boost amount and deterministic safety guarantee."""
        result = HybridPriorityAdvisor._build_explanation(
            make_features(task_urgency=0.9, battery_pct=15.0),
            boost=2, confidence=0.81, learned=True
        )
        assert result is not None
        assert "Priority boost +2" in result
        assert "deterministic" in result.lower() or "safety" in result.lower()
        assert "0.81" in result  # confidence should appear

    def test_explanation_mentions_learned_layer(self):
        """When learned=True, explanation should reference DecisionTree."""
        result = HybridPriorityAdvisor._build_explanation(
            make_features(task_urgency=1.0),
            boost=1, confidence=0.75, learned=True
        )
        assert "DecisionTree" in result

    def test_explanation_mentions_fallback_layer(self):
        """When learned=False, explanation should reference rule-based fallback."""
        result = HybridPriorityAdvisor._build_explanation(
            make_features(task_urgency=1.0),
            boost=1, confidence=0.72, learned=False
        )
        assert "fallback" in result.lower() or "rule" in result.lower()


# ---------------------------------------------------------------------------
# Test 4: CRITICAL — Hybrid layer NEVER bypasses zero-collision guarantee
#
# Architecture proof: HybridPriorityAdvisor only changes the INPUT
# (yield_priority_weight) to LocalConflictArbiter.arbitrate(). It cannot
# change arbitrate()'s OUTPUT decision type.
# We verify: even with max boost (+2), when arbiter would YIELD, it still does.
# ---------------------------------------------------------------------------

class TestZeroCollisionGuaranteePreserved:

    def _setup_head_on_collision_scenario(self):
        """
        Creates a head-on swap scenario where AMR-A and AMR-B are about to swap cells.
        In this scenario, the lower-priority robot MUST yield regardless of boost.
        """
        # AMR-A is at (5,5) moving to (5,6)
        # AMR-B is at (5,6) moving to (5,5) — head-on swap!
        arbiter_a = LocalConflictArbiter(my_id="AMR-A")
        peer_b = PeerRobotState(
            id="AMR-B",
            current_pos=(5, 6),
            intent_path=[(5, 5)],   # B is moving toward A's position
            priority_weight=3,       # B has HIGHER base priority than A
            remaining_distance=5,
            speed=1.0,
            state="MOVING",
        )
        # A has lower base priority (1) and even with max boost (+2) reaches only 3 = tied
        # Tie-breaker: "AMR-A" < "AMR-B" → A wins alphabetically, but B has higher remaining
        return arbiter_a, peer_b

    def test_yield_decision_not_overridden_by_max_boost(self):
        """
        Even when priority_weight is boosted to its maximum, if the deterministic
        arbiter decides YIELD or REROUTE, that decision must stand.
        This test verifies the architectural safety invariant.
        """
        # Peer has much higher base priority
        arbiter = LocalConflictArbiter(my_id="AMR-LOW")
        peer = PeerRobotState(
            id="AMR-HIGH",
            current_pos=(3, 3),
            intent_path=[(2, 3)],   # Peer heading to my next cell
            priority_weight=10,      # Peer has very high priority
            remaining_distance=2,
            speed=1.0,
            state="MOVING",
        )

        # With even max priority_weight (1 + 2 boost = 3), peer_priority=10 still wins
        # → arbiter must return YIELD or REROUTE regardless of boost
        my_priority_with_max_boost = 1 + HybridPriorityAdvisor.BOOST_HIGH  # = 3

        decision = arbiter.arbitrate(
            my_pos=(2, 3),
            my_intent=[(3, 3)],   # I'm heading to peer's current cell
            my_priority=my_priority_with_max_boost,
            my_rem_dist=5,
            peer_states={"AMR-HIGH": peer},
        )

        # With peer at priority 10 vs my boosted 3, I must still yield/wait/reroute
        assert decision.decision_type in (
            DecisionType.YIELD, DecisionType.WAIT, DecisionType.REROUTE
        ), (
            f"SAFETY VIOLATION: Max boost should NOT allow bypassing YIELD when "
            f"peer has overwhelming priority advantage. Got: {decision.decision_type}"
        )

    def test_collision_count_stays_zero_after_many_arbitrations(self):
        """
        Run 100 arbitration cycles with boosted priority and verify
        no head-on swap collision ever succeeds.
        """
        from services.metrics.tracker import FleetMetricsTracker

        tracker = FleetMetricsTracker()
        arbiter_a = LocalConflictArbiter(my_id="AMR-01")
        arbiter_b = LocalConflictArbiter(my_id="AMR-02")

        pos_a = (0, 5)
        pos_b = (10, 5)
        collisions_detected = 0

        for _ in range(100):
            # Both robots moving toward each other with max-boosted priority
            peer_b_state = PeerRobotState(
                id="AMR-02", current_pos=pos_b,
                intent_path=[(pos_b[0] - 1, pos_b[1])],
                priority_weight=1 + HybridPriorityAdvisor.BOOST_HIGH,
                remaining_distance=5, speed=1.0, state="MOVING",
            )
            dec_a = arbiter_a.arbitrate(
                my_pos=pos_a,
                my_intent=[(pos_a[0] + 1, pos_a[1])],
                my_priority=1 + HybridPriorityAdvisor.BOOST_HIGH,
                my_rem_dist=5,
                peer_states={"AMR-02": peer_b_state},
            )

            peer_a_state = PeerRobotState(
                id="AMR-01", current_pos=pos_a,
                intent_path=[(pos_a[0] + 1, pos_a[1])],
                priority_weight=1 + HybridPriorityAdvisor.BOOST_HIGH,
                remaining_distance=5, speed=1.0, state="MOVING",
            )
            dec_b = arbiter_b.arbitrate(
                my_pos=pos_b,
                my_intent=[(pos_b[0] - 1, pos_b[1])],
                my_priority=1 + HybridPriorityAdvisor.BOOST_HIGH,
                my_rem_dist=5,
                peer_states={"AMR-01": peer_a_state},
            )

            # Invariant: both robots must never simultaneously decide CONTINUE into the same cell or edge-swap
            if dec_a.decision_type == DecisionType.CONTINUE and dec_b.decision_type == DecisionType.CONTINUE:
                target_a = (pos_a[0] + 1, pos_a[1])
                target_b = (pos_b[0] - 1, pos_b[1])
                if target_a == target_b or (target_a == pos_b and target_b == pos_a):
                    collisions_detected += 1

            # Execute moves according to decision:
            # CONTINUE moves forward along path; REROUTE detours laterally off the conflict lane
            if dec_a.decision_type == DecisionType.CONTINUE:
                new_pos_a = (pos_a[0] + 1, pos_a[1])
            elif dec_a.decision_type == DecisionType.REROUTE:
                new_pos_a = (pos_a[0], pos_a[1] - 1)  # Detour off the lane
            else:
                new_pos_a = pos_a

            if dec_b.decision_type == DecisionType.CONTINUE:
                new_pos_b = (pos_b[0] - 1, pos_b[1])
            elif dec_b.decision_type == DecisionType.REROUTE:
                new_pos_b = (pos_b[0], pos_b[1] + 1)  # Detour off the lane
            else:
                new_pos_b = pos_b

            # Check for collision (same cell)
            if new_pos_a == new_pos_b:
                collisions_detected += 1

            pos_a = new_pos_a
            pos_b = new_pos_b

            # Stop if they've passed each other safely
            if pos_a[0] >= pos_b[0]:
                break

        assert collisions_detected == 0, (
            f"SAFETY VIOLATION: {collisions_detected} collision(s) detected even "
            f"with max priority boost active. Zero-collision guarantee BROKEN."
        )


# ---------------------------------------------------------------------------
# Test 5: Feature extraction is correct
# ---------------------------------------------------------------------------

class TestFeatureExtraction:
    def test_extract_features_basic(self):
        advisor = HybridPriorityAdvisor(model_path="/nonexistent/model.pkl")
        feat = advisor.extract_features(
            task_priority_int=4,       # CRITICAL
            battery_pct=30.0,
            current_pos=(5, 5),
            conflict_cell=(5, 6),
            congestion_penalties={(5, 6): 8.0},
            payload_kg=150.0,
            robot_type_weight=2,
        )
        assert feat.task_urgency == pytest.approx(1.0)   # 4/4
        assert feat.battery_pct == 30.0
        assert feat.distance_to_conflict == 1            # Manhattan (5,5) to (5,6)
        assert feat.congestion_score == 8.0
        assert feat.payload_kg == 150.0
        assert feat.robot_type_weight == 2

    def test_feature_vector_length(self):
        advisor = HybridPriorityAdvisor(model_path="/nonexistent/model.pkl")
        feat = advisor.extract_features(
            task_priority_int=2, battery_pct=80.0,
            current_pos=(3, 3), conflict_cell=(4, 3),
            congestion_penalties={}, payload_kg=0.0, robot_type_weight=1,
        )
        vec = feat.to_list()
        assert len(vec) == 6, f"Feature vector must have 6 elements, got {len(vec)}"

    def test_feature_vector_all_normalized_0_to_1(self):
        """All normalized feature values must be in [0, 1]."""
        advisor = HybridPriorityAdvisor(model_path="/nonexistent/model.pkl")
        feat = advisor.extract_features(
            task_priority_int=4, battery_pct=5.0,
            current_pos=(0, 0), conflict_cell=(20, 20),
            congestion_penalties={(20, 20): 100.0},
            payload_kg=500.0, robot_type_weight=4,
        )
        vec = feat.to_list()
        for i, v in enumerate(vec):
            assert 0.0 <= v <= 1.0, (
                f"Feature[{i}]={v} is out of [0,1] range — normalization bug"
            )
