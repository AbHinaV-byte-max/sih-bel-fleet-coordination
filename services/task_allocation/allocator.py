"""
Task Allocation Microservice using the Hungarian Algorithm (Munkres Algorithm).
Sponsored by Bharat Electronics Limited (BEL) - SIH Problem Statement 26123.

ARCHITECTURAL DISTINCTION:
Task allocation operates as a macro-planning optimization layer that maps warehouse orders
to available robots based on global travel distance, payload constraints, and urgency.
Real-time collision avoidance and conflict resolution operate as a strictly decentralized,
peer-to-peer micro-coordination layer on the edge AMRs. Running task allocation as an
independent service does NOT compromise the decentralization claim of the safety and navigation stack.
"""

from typing import List, Dict, Optional, Tuple
import logging
import numpy as np
from scipy.optimize import linear_sum_assignment

from .task_models import WarehouseTask, RobotCapability, AssignmentResult, TaskStatus

logger = logging.getLogger("TaskAllocationService")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


class HungarianTaskAllocator:
    """
    Computes minimum-cost assignment of pickup-and-delivery tasks to available robots
    using SciPy's linear_sum_assignment (Hungarian Algorithm).

    Features:
    - Multi-Robot-Type capability matching (respects payload capacities).
    - Proactive battery and priority weighting.
    - Automatic re-triggering when a robot broadcasts a blocked path.
    - Zero proprietary dependencies (open, auditable algorithms).
    """

    INFEASIBLE_COST: float = 1e6

    def __init__(self, battery_penalty_weight: float = 0.5):
        self.battery_penalty_weight = battery_penalty_weight
        self.active_assignments: Dict[str, str] = {}  # task_id -> robot_id
        logger.info("Initialized Hungarian Task Allocation Service (SciPy linear_sum_assignment).")

    @staticmethod
    def _manhattan_distance(p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
        return abs(p1[0] - p2[0]) + abs(p1[1] - p2[1])

    def compute_cost_matrix(
        self,
        available_robots: List[RobotCapability],
        pending_tasks: List[WarehouseTask],
    ) -> np.ndarray:
        """
        Builds an M x N cost matrix where rows correspond to available robots
        and columns correspond to pending tasks.
        """
        n_robots = len(available_robots)
        n_tasks = len(pending_tasks)

        if n_robots == 0 or n_tasks == 0:
            return np.empty((n_robots, n_tasks))

        cost_matrix = np.zeros((n_robots, n_tasks), dtype=float)

        for i, robot in enumerate(available_robots):
            for j, task in enumerate(pending_tasks):
                # 1. Physical capability constraint: Payload check
                if task.payload_weight_kg > robot.max_payload_kg:
                    cost_matrix[i, j] = self.INFEASIBLE_COST
                    continue

                # 2. Distance cost: AMR to Pickup + Pickup to Dropoff
                dist_to_pickup = self._manhattan_distance(robot.current_pos, task.pickup_pos)
                dist_task = self._manhattan_distance(task.pickup_pos, task.dropoff_pos)
                travel_cost = (dist_to_pickup + dist_task) / max(robot.max_speed, 0.1)

                # 3. Battery health penalty: Lower battery incurs higher cost
                battery_penalty = (100.0 - robot.battery_level_pct) * self.battery_penalty_weight

                # 4. Priority weighting: High priority tasks discount cost to ensure matching
                priority_discount = (task.priority.value - 1) * 3.0

                total_cost = max(1.0, travel_cost + battery_penalty - priority_discount)
                cost_matrix[i, j] = total_cost

        return cost_matrix

    def assign_tasks(
        self,
        robots: List[RobotCapability],
        tasks: List[WarehouseTask],
    ) -> List[AssignmentResult]:
        """
        Performs Hungarian matching on idle robots and pending tasks.
        Returns the optimal robot-to-task assignments.
        """
        # Filter only idle robots and pending tasks
        idle_robots = [r for r in robots if not r.is_busy and r.battery_level_pct > 15.0]
        unassigned_tasks = [t for t in tasks if t.status == TaskStatus.PENDING]

        if not idle_robots or not unassigned_tasks:
            return []

        cost_matrix = self.compute_cost_matrix(idle_robots, unassigned_tasks)

        # Solve assignment problem with Hungarian algorithm
        row_indices, col_indices = linear_sum_assignment(cost_matrix)

        assignments: List[AssignmentResult] = []

        for r_idx, t_idx in zip(row_indices, col_indices):
            cost = cost_matrix[r_idx, t_idx]
            # Ignore infeasible assignments (e.g. payload exceeded)
            if cost >= self.INFEASIBLE_COST / 2:
                logger.warning(
                    f"Task {unassigned_tasks[t_idx].id} payload ({unassigned_tasks[t_idx].payload_weight_kg} kg) "
                    f"exceeds capacity of robot {idle_robots[r_idx].id} ({idle_robots[r_idx].max_payload_kg} kg). Skipped."
                )
                continue

            robot = idle_robots[r_idx]
            task = unassigned_tasks[t_idx]

            task.assigned_robot_id = robot.id
            task.status = TaskStatus.ASSIGNED
            self.active_assignments[task.id] = robot.id

            reason = (
                f"Assigned {task.id} to {robot.id} (Type: {robot.robot_type}, "
                f"Cost: {cost:.1f}, Dist to pickup: {self._manhattan_distance(robot.current_pos, task.pickup_pos):.0f})"
            )
            assignments.append(
                AssignmentResult(
                    robot_id=robot.id,
                    task_id=task.id,
                    cost=cost,
                    reason=reason,
                )
            )
            logger.info(f"OPTIMAL HUNGARIAN ASSIGNMENT: {reason}")

        return assignments

    def handle_blocked_task(
        self,
        task_id: str,
        reporting_robot_id: str,
        reason: str,
        tasks_lookup: Dict[str, WarehouseTask],
    ) -> bool:
        """
        Automatic re-trigger when a robot reports an unresolvable blockage.
        Resets task state so the allocator will re-assign it to another candidate robot.
        """
        if task_id not in tasks_lookup:
            logger.warning(f"Reported blocked task {task_id} not found in task catalog.")
            return False

        task = tasks_lookup[task_id]
        logger.warning(
            f"RE-TRIGGERING ALLOCATOR: Robot {reporting_robot_id} reported task {task_id} blocked. Reason: {reason}"
        )

        task.status = TaskStatus.PENDING
        task.assigned_robot_id = None
        task.blocked_reason = reason
        if task_id in self.active_assignments:
            del self.active_assignments[task_id]

        return True
