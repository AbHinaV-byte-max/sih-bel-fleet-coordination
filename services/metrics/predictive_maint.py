"""
Rule-Based Predictive Maintenance Engine (SIH 26123 - Bharat Electronics Limited).
Simple, auditable heuristics (no black-box machine learning) to flag AMR servicing requirements.
"""

from typing import Dict, Any


class PredictiveMaintenanceClassifier:
    """
    Evaluates cumulative distance, operating cycle counts, and battery drain
    to flag robots needing depot inspection.
    """

    def __init__(
        self,
        distance_km_threshold: float = 15.0,
        operating_cycles_threshold: int = 40,
    ):
        self.distance_km_threshold = distance_km_threshold
        self.operating_cycles_threshold = operating_cycles_threshold

    def evaluate_robot(
        self,
        robot_id: str,
        odometer_meters: float,
        cycles_completed: int,
        battery_pct: float,
    ) -> Dict[str, Any]:
        """
        Evaluates mechanical wear metrics against defense depot maintenance thresholds.
        """
        odometer_km = odometer_meters / 1000.0
        service_due = False
        reasons = []

        # Metric 1: Odometer threshold check
        distance_wear_pct = (odometer_km / self.distance_km_threshold) * 100.0
        if odometer_km >= self.distance_km_threshold:
            service_due = True
            reasons.append(f"Odometer threshold exceeded: {odometer_km:.2f} km >= {self.distance_km_threshold} km")

        # Metric 2: Operating cycles threshold check
        cycle_wear_pct = (cycles_completed / self.operating_cycles_threshold) * 100.0
        if cycles_completed >= self.operating_cycles_threshold:
            service_due = True
            reasons.append(f"Operating cycles threshold exceeded: {cycles_completed} >= {self.operating_cycles_threshold}")

        # Metric 3: Critical battery degradation warning
        if battery_pct < 15.0:
            reasons.append(f"Low battery level: {battery_pct:.1f}%")

        overall_wear_pct = min(100.0, max(distance_wear_pct, cycle_wear_pct))

        return {
            "robot_id": robot_id,
            "service_due": service_due,
            "wear_pct": round(overall_wear_pct, 1),
            "reasons": reasons,
            "odometer_km": round(odometer_km, 3),
            "cycles_completed": cycles_completed,
            "battery_pct": round(battery_pct, 1),
        }
