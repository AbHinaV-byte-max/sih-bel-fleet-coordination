"""
Task and Robot Capability Data Models for SIH 26123 Fleet Coordination System.
Provides structured types for warehouse logistics orders and AMR capabilities.
"""

from enum import Enum
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass, field
import time


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TaskPriority(int, Enum):
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class WarehouseTask:
    id: str
    pickup_pos: Tuple[int, int]
    dropoff_pos: Tuple[int, int]
    payload_weight_kg: float = 20.0
    priority: TaskPriority = TaskPriority.NORMAL
    assigned_robot_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    blocked_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pickup_pos": list(self.pickup_pos),
            "dropoff_pos": list(self.dropoff_pos),
            "payload_weight_kg": self.payload_weight_kg,
            "priority": self.priority.name,
            "assigned_robot_id": self.assigned_robot_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "blocked_reason": self.blocked_reason,
        }


@dataclass
class RobotCapability:
    id: str
    robot_type: str
    current_pos: Tuple[int, int]
    is_busy: bool = False
    battery_level_pct: float = 100.0
    max_payload_kg: float = 250.0
    max_speed: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "robot_type": self.robot_type,
            "current_pos": list(self.current_pos),
            "is_busy": self.is_busy,
            "battery_level_pct": self.battery_level_pct,
            "max_payload_kg": self.max_payload_kg,
            "max_speed": self.max_speed,
        }


@dataclass
class AssignmentResult:
    robot_id: str
    task_id: str
    cost: float
    reason: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "robot_id": self.robot_id,
            "task_id": self.task_id,
            "cost": round(self.cost, 2),
            "reason": self.reason,
            "timestamp": self.timestamp,
        }
