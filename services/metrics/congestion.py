"""
Rolling Congestion History Tracker (SIH 26123 - Industry-Alignment Layer).
Inspired by Amazon Robotics DeepFleet multi-agent forecasting:
Tracks rolling conflict and near-miss frequency per intersection to proactively bias pathfinding.
"""

from typing import Dict, Tuple, List, Any, Optional
import time


class CongestionTracker:
    """
    Maintains a rolling time-window of conflict events across the warehouse grid.
    Provides data for the live heatmap and cost penalties for proactive A* rerouting.
    """

    def __init__(self, window_seconds: float = 60.0, penalty_multiplier: float = 4.0):
        self.window_seconds = window_seconds
        self.penalty_multiplier = penalty_multiplier
        # List of (timestamp, (x, y), reporting_robot, peer_id)
        self.conflict_events: List[Dict[str, Any]] = []

    def record_conflict(
        self,
        cell: Tuple[int, int],
        reporting_robot: str,
        peer_id: Optional[str] = None,
        timestamp: Optional[float] = None,
    ) -> None:
        """Records a conflict or yield event at a specific grid cell."""
        ts = timestamp if timestamp is not None else time.time()
        self.conflict_events.append({
            "timestamp": ts,
            "cell": cell,
            "reporting_robot": reporting_robot,
            "peer_id": peer_id,
        })
        self._prune_expired()

    def _prune_expired(self) -> None:
        """Removes events older than window_seconds."""
        now = time.time()
        cutoff = now - self.window_seconds
        self.conflict_events = [e for e in self.conflict_events if e["timestamp"] >= cutoff]

    def get_heatmap_data(self) -> Dict[str, Any]:
        """
        Returns JSON-serializable per-cell conflict counts within the rolling window.
        Format: {"cells": [{"x": int, "y": int, "intensity": int}], "total_events": int}
        """
        self._prune_expired()
        counts: Dict[Tuple[int, int], int] = {}
        for event in self.conflict_events:
            c = event["cell"]
            counts[c] = counts.get(c, 0) + 1

        cells = [
            {"x": x, "y": y, "intensity": count}
            for (x, y), count in counts.items()
        ]
        return {
            "cells": cells,
            "total_events_in_window": len(self.conflict_events),
            "window_seconds": self.window_seconds,
        }

    def get_cell_penalties(self) -> Dict[Tuple[int, int], float]:
        """
        Computes additive A* cost penalties proportional to recent conflict counts.
        """
        self._prune_expired()
        penalties: Dict[Tuple[int, int], float] = {}
        for event in self.conflict_events:
            c = event["cell"]
            penalties[c] = penalties.get(c, 0.0) + self.penalty_multiplier
        return penalties
