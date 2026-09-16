"""
Defense-Grade Explainable Reason Codes for Autonomous Mobile Robots (SIH 26123 - BEL).
Zero black-box ML: every routing, yield, wait, and speed adjustment decision is logged
with auditable, standardized reason codes aligned to §11.1 tie-break hierarchy.

Priority Hierarchy (§11.1):
  1. EMERGENCY_TASK       — highest override
  2. SAFETY_CONSTRAINT    — ISO 3691-4 / ANSI B56.5 hard safety limits
  3. EXISTING_RESERVATION — space-time reservation already claimed (§11.2)
  4. TASK_URGENCY         — task priority tier (1–4)
  5. REMAINING_PATH_COST  — remaining distance to goal (clears intersections faster)
  6. ROBOT_ID_TIEBREAK    — deterministic lexicographic ID tiebreaker
"""

from enum import Enum


class ReasonCode(str, Enum):
    # ─── Nominal Navigation ───────────────────────────────────────────────────
    RC_TASK_ASSIGNED = "RC_TASK_ASSIGNED"
    RC_MOVING_NOMINAL = "RC_MOVING_NOMINAL"
    RC_TASK_PICKUP_ARRIVED = "RC_TASK_PICKUP_ARRIVED"
    RC_TASK_DROPOFF_COMPLETE = "RC_TASK_DROPOFF_COMPLETE"

    # ─── §11.1 Tie-Break Hierarchy — Decentralized Conflict Arbitration ───────
    # Tier 1: Emergency task override
    RC_EMERGENCY_TASK_OVERRIDE = "RC_EMERGENCY_TASK_OVERRIDE"
    # Tier 2: ISO 3691-4 / ANSI B56.5 safety constraints
    RC_SAFETY_CONSTRAINT = "RC_SAFETY_CONSTRAINT"
    # Tier 3: Existing space-time reservation takes precedence (§11.2)
    RC_EXISTING_RESERVATION = "RC_EXISTING_RESERVATION"
    # Tier 4: Task urgency comparison
    RC_TASK_URGENCY = "RC_TASK_URGENCY"
    # Tier 5: Remaining path cost (closer to goal wins intersection)
    RC_REMAINING_PATH_COST = "RC_REMAINING_PATH_COST"
    # Tier 6: Lexicographic robot ID deterministic tiebreak
    RC_ROBOT_ID_TIEBREAK = "RC_ROBOT_ID_TIEBREAK"

    # ─── Conflict Resolution Outcomes ─────────────────────────────────────────
    RC_CONTINUE_RIGHT_OF_WAY = "RC_CONTINUE_RIGHT_OF_WAY"
    RC_YIELD_INTERSECTION_CONFLICT = "RC_YIELD_INTERSECTION_CONFLICT"
    RC_YIELD_HEAD_ON_SWAP = "RC_YIELD_HEAD_ON_SWAP"
    RC_WAIT_CLEARANCE = "RC_WAIT_CLEARANCE"
    RC_REROUTE_DYNAMIC = "RC_REROUTE_DYNAMIC"
    RC_REROUTE_BLOCKED = "RC_REROUTE_BLOCKED"
    RC_DEADLOCK_DETECTED = "RC_DEADLOCK_DETECTED"
    RC_DEADLOCK_RESOLVED = "RC_DEADLOCK_RESOLVED"

    # ─── Industry-Alignment: Proactive Congestion & Safety ────────────────────
    RC_PROACTIVE_REROUTE_CONGESTION = "RC_PROACTIVE_REROUTE_CONGESTION"
    RC_SAFETY_HUMAN_ZONE_SPEED_DERATING = "RC_SAFETY_HUMAN_ZONE_SPEED_DERATING"
    RC_DYNAMIC_OBSTACLE_BLOCKED = "RC_DYNAMIC_OBSTACLE_BLOCKED"

    # ─── Health & Maintenance ─────────────────────────────────────────────────
    RC_BATTERY_LOW_RETURN_TO_CHARGE = "RC_BATTERY_LOW_RETURN_TO_CHARGE"
    RC_MAINTENANCE_SERVICE_DUE = "RC_MAINTENANCE_SERVICE_DUE"
    RC_ROBOT_DEGRADED = "RC_ROBOT_DEGRADED"
    RC_ROBOT_FAILED = "RC_ROBOT_FAILED"

    # ─── Communication States (§8.1, §12) ─────────────────────────────────────
    RC_COMMS_DEGRADED = "RC_COMMS_DEGRADED"
    RC_COMMS_SAFE_MODE = "RC_COMMS_SAFE_MODE"

    # ─── Hybrid AI Layer (Research-Aligned: RL-guided Prioritized Planning) ───
    # Applied ONLY as a priority-weight adjustment before the deterministic arbiter runs.
    # The deterministic DSS arbiter's safety checks are NEVER bypassed.
    RC_HYBRID_PRIORITY_ADJUSTED = "RC_HYBRID_PRIORITY_ADJUSTED"
