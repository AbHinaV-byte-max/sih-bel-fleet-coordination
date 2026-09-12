"""
Unit Tests for Fleet Metrics Service (SIH 26123 - Bharat Electronics Limited).
Validates zero-collision detection, percentage improvement calculations, predictive maintenance thresholds,
and rolling congestion window tracking.
"""

import pytest
import time
from services.metrics import (
    FleetMetricsTracker,
    CongestionTracker,
    PredictiveMaintenanceClassifier,
)


def test_zero_collision_monitor_success():
    """Verify that distinct robot positions register 0 collisions."""
    tracker = FleetMetricsTracker()
    positions = {
        "AMR-01": (1, 1),
        "AMR-02": (2, 2),
        "AMR-03": (3, 3),
    }
    assert tracker.verify_no_collisions(positions) is True
    assert tracker.total_collisions == 0


def test_collision_detection_trigger():
    """Verify that overlapping robot positions trigger a collision alert and increment counter."""
    tracker = FleetMetricsTracker()
    colliding_positions = {
        "AMR-01": (5, 5),
        "AMR-02": (5, 5),  # Same cell!
    }
    assert tracker.verify_no_collisions(colliding_positions) is False
    assert tracker.total_collisions == 1
    assert len(tracker.collision_incidents) == 1


def test_efficiency_improvement_calculation():
    """Verify percentage improvement formula: ((T_base - T_dec) / T_base) * 100%."""
    tracker = FleetMetricsTracker()

    # Task 1: Decentralized took 70s, Baseline took 100s -> 30% reduction
    tracker.record_completed_task(decentralized_duration=70.0, baseline_duration=100.0)

    improvement = tracker.compute_efficiency_improvement()
    assert improvement == 30.0
    assert tracker.get_live_metrics()["success_criteria_met"] is True


def test_predictive_maintenance_thresholds():
    """Verify that exceeding distance or cycle counts triggers 'service_due' flag."""
    classifier = PredictiveMaintenanceClassifier(
        distance_km_threshold=10.0,
        operating_cycles_threshold=20,
    )

    # Robot 1: Under thresholds
    eval_1 = classifier.evaluate_robot(
        robot_id="AMR-01",
        odometer_meters=5000.0,  # 5 km
        cycles_completed=10,
        battery_pct=90.0,
    )
    assert eval_1["service_due"] is False
    assert eval_1["wear_pct"] == 50.0

    # Robot 2: Odometer exceeded (12 km >= 10 km)
    eval_2 = classifier.evaluate_robot(
        robot_id="AMR-02",
        odometer_meters=12000.0,
        cycles_completed=10,
        battery_pct=80.0,
    )
    assert eval_2["service_due"] is True
    assert any("Odometer" in r for r in eval_2["reasons"])

    # Robot 3: Cycles exceeded (25 >= 20)
    eval_3 = classifier.evaluate_robot(
        robot_id="AMR-03",
        odometer_meters=2000.0,
        cycles_completed=25,
        battery_pct=85.0,
    )
    assert eval_3["service_due"] is True
    assert any("cycles" in r for r in eval_3["reasons"])


def test_congestion_tracker_rolling_window():
    """Verify conflict event recording and heatmap intensity counts."""
    tracker = CongestionTracker(window_seconds=1.0)

    tracker.record_conflict(cell=(5, 5), reporting_robot="AMR-01")
    tracker.record_conflict(cell=(5, 5), reporting_robot="AMR-02")
    tracker.record_conflict(cell=(10, 10), reporting_robot="AMR-03")

    heatmap = tracker.get_heatmap_data()
    cell_map = {(c["x"], c["y"]): c["intensity"] for c in heatmap["cells"]}

    assert cell_map[(5, 5)] == 2
    assert cell_map[(10, 10)] == 1
    assert heatmap["total_events_in_window"] == 3
