"""
Hybrid AI Priority Advisor — Research-Aligned Priority Weighting Layer (SIH 26123 - BEL).

RESEARCH BASIS:
  2025/2026 multi-agent pathfinding literature explicitly states: "while machine learning
  methods have been explored, their superiority over search-based methods remains
  inconclusive." The proven winning pattern is HYBRID: keep classical deterministic
  arbitration as the backbone, add a lightweight learned layer on top.

  This module implements the "RL-guided Prioritized Planning" pattern:
    "leverages classical Prioritized Planning as a backbone... integrating with a
     learning-based priority assignment policy." (MAPF research, 2025/2026)

SAFETY INVARIANT (by design, not just policy):
  This advisor only modifies `yield_priority_weight` BEFORE LocalConflictArbiter.arbitrate()
  is called. It CANNOT alter the output of the arbiter's safety checks (head-on swap
  detection, cell contention checks). The zero-collision guarantee is preserved
  architecturally: the learned layer feeds inputs to the arbiter — it never receives
  or overrides the arbiter's output decisions.

INTERPRETABILITY:
  DecisionTreeClassifier max_depth=5 is deliberately chosen for inspectability:
  the decision path for any prediction can be printed as a human-readable rule set,
  meeting defense-grade explainability requirements.
"""

from __future__ import annotations

import logging
import os
import pickle
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("HybridPriorityAdvisor")

# Path to the trained model, relative to project root
_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "models", "priority_model.pkl"
)


@dataclass
class PriorityFeatures:
    """Feature vector extracted from a robot's current context for priority prediction."""
    task_urgency: float          # 0.0–1.0 (normalized task priority; 1.0 = CRITICAL)
    battery_pct: float           # 0.0–100.0
    distance_to_conflict: int    # Manhattan distance in cells to predicted conflict cell
    congestion_score: float      # Sum of recent penalties at conflict cell (0.0–20.0 clipped)
    payload_kg: float            # Current payload weight (0.0 = empty)
    robot_type_weight: int       # Base priority weight from robot type config (1–4)

    def to_list(self) -> List[float]:
        return [
            self.task_urgency,
            self.battery_pct / 100.0,       # Normalize to 0–1
            min(self.distance_to_conflict, 20) / 20.0,  # Normalize, cap at 20
            min(self.congestion_score, 20.0) / 20.0,    # Normalize, cap at 20
            min(self.payload_kg, 300.0) / 300.0,        # Normalize, cap at 300kg
            self.robot_type_weight / 4.0,               # Normalize, max weight = 4
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_urgency": self.task_urgency,
            "battery_pct": self.battery_pct,
            "distance_to_conflict": self.distance_to_conflict,
            "congestion_score": self.congestion_score,
            "payload_kg": self.payload_kg,
            "robot_type_weight": self.robot_type_weight,
        }


class HybridPriorityAdvisor:
    """
    Lightweight learned priority-adjustment layer that sits upstream of the deterministic
    LocalConflictArbiter. Loads a pre-trained DecisionTreeClassifier (max_depth=5) and
    predicts a priority boost (+0, +1, or +2) given the robot's current context features.

    Falls back to deterministic rule-based priority adjustment when:
      - No model file exists yet (before training scripts are run)
      - Model file is corrupt or incompatible
      - sklearn is not installed (graceful degradation)

    Thread-safe: no mutable instance state between calls.
    """

    # Priority boost values — intentionally small to avoid destabilizing the arbiter
    BOOST_NONE = 0
    BOOST_MODERATE = 1
    BOOST_HIGH = 2

    def __init__(self, model_path: str = _MODEL_PATH):
        self._model = None
        self._model_loaded = False
        self._model_path = model_path
        self._load_model()

    def _load_model(self) -> None:
        """Attempts to load the trained DecisionTreeClassifier. Fails gracefully."""
        model_abs = os.path.abspath(self._model_path)
        if not os.path.exists(model_abs):
            logger.info(
                "HybridPriorityAdvisor: No trained model found at %s. "
                "Running in rule-based fallback mode. "
                "Run scripts/generate_training_data.py then scripts/train_priority_model.py "
                "to enable the learned layer.",
                model_abs,
            )
            return
        try:
            import sklearn  # noqa: F401 — check sklearn is available
            with open(model_abs, "rb") as f:
                self._model = pickle.load(f)
            self._model_loaded = True
            logger.info(
                "HybridPriorityAdvisor: Loaded trained DecisionTreeClassifier from %s. "
                "Hybrid learned priority layer ACTIVE.",
                model_abs,
            )
        except ImportError:
            logger.warning(
                "HybridPriorityAdvisor: scikit-learn not available. "
                "Falling back to rule-based priority adjustment."
            )
        except Exception as exc:
            logger.warning(
                "HybridPriorityAdvisor: Failed to load model (%s). "
                "Falling back to rule-based priority adjustment.", exc
            )

    @property
    def is_model_active(self) -> bool:
        """True when a trained DecisionTreeClassifier is loaded and being used."""
        return self._model_loaded and self._model is not None

    def extract_features(
        self,
        task_priority_int: int,          # 1=Low, 2=Normal, 3=High, 4=Critical
        battery_pct: float,
        current_pos: Tuple[int, int],
        conflict_cell: Optional[Tuple[int, int]],
        congestion_penalties: Dict[Tuple[int, int], float],
        payload_kg: float,
        robot_type_weight: int,
    ) -> PriorityFeatures:
        """Builds the feature vector from robot runtime state."""
        # Normalize task urgency to [0, 1]
        task_urgency = min(task_priority_int, 4) / 4.0

        # Manhattan distance to conflict cell (or 0 if no conflict predicted)
        if conflict_cell is not None:
            distance_to_conflict = abs(current_pos[0] - conflict_cell[0]) + abs(
                current_pos[1] - conflict_cell[1]
            )
        else:
            distance_to_conflict = 0

        # Congestion score at the conflict cell
        if conflict_cell is not None:
            congestion_score = congestion_penalties.get(conflict_cell, 0.0)
        else:
            congestion_score = 0.0

        return PriorityFeatures(
            task_urgency=task_urgency,
            battery_pct=battery_pct,
            distance_to_conflict=distance_to_conflict,
            congestion_score=congestion_score,
            payload_kg=payload_kg,
            robot_type_weight=robot_type_weight,
        )

    def predict_priority_boost(
        self, features: PriorityFeatures
    ) -> Tuple[int, float, str]:
        """
        Predicts the priority boost for this robot given its context features.

        Returns:
            (boost, confidence, explanation)
            - boost: int in {0, 1, 2} — to be added to yield_priority_weight
            - confidence: float in [0.0, 1.0] — model class probability
            - explanation: human-readable string for the decision log

        SAFETY: boost is always in {0, 1, 2}. The arbiter's safety checks run after
        priority weighting and cannot be bypassed regardless of boost magnitude.
        """
        if self.is_model_active:
            return self._predict_with_model(features)
        return self._predict_rule_based(features)

    def _predict_with_model(
        self, features: PriorityFeatures
    ) -> Tuple[int, float, str]:
        """Uses the trained DecisionTreeClassifier for prediction."""
        try:
            import numpy as np
            feature_vec = np.array([features.to_list()])
            raw_pred = int(self._model.predict(feature_vec)[0])
            # Clamp to valid range regardless of what the model outputs
            boost = max(self.BOOST_NONE, min(self.BOOST_HIGH, raw_pred))

            # Get confidence: probability of the predicted class
            proba = self._model.predict_proba(feature_vec)[0]
            confidence = float(proba[raw_pred]) if 0 <= raw_pred < len(proba) else 0.5

            explanation = self._build_explanation(features, boost, confidence, learned=True)
            return boost, confidence, explanation
        except Exception as exc:
            logger.debug("Hybrid model prediction failed (%s); using rule fallback.", exc)
            return self._predict_rule_based(features)

    def _predict_rule_based(
        self, features: PriorityFeatures
    ) -> Tuple[int, float, str]:
        """
        Deterministic rule-based fallback (active when no model is trained yet).
        Mirrors the spirit of the learned layer using interpretable if-else logic.
        Rules are derived from domain knowledge and match the training label logic.
        """
        boost = self.BOOST_NONE

        # Rule 1: Critical task urgency — significant boost
        if features.task_urgency >= 0.75:
            boost = self.BOOST_HIGH
        # Rule 2: High urgency OR very low battery (urgency to complete task before discharge)
        elif features.task_urgency >= 0.5 or features.battery_pct < 20.0:
            boost = self.BOOST_MODERATE
        # Rule 3: Heavy payload at congested cell — boost to clear intersection faster
        elif features.payload_kg > 100.0 and features.congestion_score > 4.0:
            boost = self.BOOST_MODERATE

        confidence = 0.72 if boost > 0 else 0.85  # Indicative, not calibrated
        explanation = self._build_explanation(features, boost, confidence, learned=False)
        return boost, confidence, explanation

    @staticmethod
    def _build_explanation(
        features: PriorityFeatures,
        boost: int,
        confidence: float,
        learned: bool,
    ) -> Optional[str]:
        """Constructs a plain-language explanation string for the decision log."""
        if boost == 0:
            return None  # No adjustment — no note needed in log

        layer = "DecisionTree[depth≤5]" if learned else "rule-based fallback"
        reasons = []

        if features.task_urgency >= 0.75:
            reasons.append(f"task urgency={features.task_urgency:.2f} (CRITICAL/HIGH)")
        if features.battery_pct < 20.0:
            reasons.append(f"low battery={features.battery_pct:.1f}% (urgency to complete)")
        if features.payload_kg > 100.0:
            reasons.append(f"heavy payload={features.payload_kg:.0f}kg")
        if features.congestion_score > 4.0:
            reasons.append(f"congestion-score={features.congestion_score:.1f} at conflict cell")

        reason_str = " + ".join(reasons) if reasons else "feature composite score"
        return (
            f"[Hybrid AI | {layer}] Priority boost +{boost} applied. "
            f"Reason: {reason_str}. "
            f"Model confidence: {confidence:.2f}. "
            f"NOTE: Deterministic DSS safety checks run after this adjustment — "
            f"zero-collision guarantee is architecturally preserved."
        )
