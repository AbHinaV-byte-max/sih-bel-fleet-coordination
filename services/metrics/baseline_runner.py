"""
Naive Stop-and-Wait Baseline Simulator (SIH 26123 - Bharat Electronics Limited).
Simulates multi-robot execution under a naive, non-coordinating stop-and-wait scheme
to establish the baseline performance against which the decentralized DSS is benchmarked.
"""

from typing import List, Tuple, Dict, Set, Optional, Any
import time
import copy

from services.robot_agent.pathfinding import GridAStarPathfinder
from services.task_allocation.task_models import WarehouseTask


class NaiveRobot:
    """
    Simulated robot using naive proximity-based stop-and-wait.
    Has no peer intent awareness or right-of-way protocol.
    """

    def __init__(self, robot_id: str, start_pos: Tuple[int, int], pathfinder: GridAStarPathfinder):
        self.robot_id = robot_id
        self.current_pos = start_pos
        self.pathfinder = pathfinder
        self.planned_path: List[Tuple[int, int]] = []
        self.target_goal: Optional[Tuple[int, int]] = None
        self.completed = False
        self.wait_cooldown = 0

    def set_goal(self, goal: Tuple[int, int]):
        self.target_goal = goal
        path = self.pathfinder.find_path(self.current_pos, goal)
        if path and len(path) > 1:
            self.planned_path = path[1:]
        else:
            self.planned_path = []


class NaiveBaselineSimulator:
    """
    Executes identical tasks and start configurations under a naive stop-and-wait protocol.
    Whenever two robots come within safety radius (Manhattan distance <= 1),
    they stop blindly and wait for fixed delays.
    """

    def __init__(
        self,
        grid_width: int,
        grid_height: int,
        static_obstacles: Set[Tuple[int, int]],
    ):
        self.grid_width = grid_width
        self.grid_height = grid_height
        self.static_obstacles = static_obstacles
        self.pathfinder = GridAStarPathfinder(grid_width, grid_height, static_obstacles)

    def run_scenario(
        self,
        robot_configs: List[Dict[str, Any]],
        task_list: List[WarehouseTask],
        max_ticks: int = 500,
    ) -> Dict[str, Any]:
        """
        Runs the simulation until all tasks are completed or max_ticks is reached.
        Returns total ticks, per-robot times, and collision incidents.
        """
        robots: Dict[str, NaiveRobot] = {}
        for cfg in robot_configs:
            r_id = cfg["id"]
            start_pos = tuple(cfg["start_pos"])
            robots[r_id] = NaiveRobot(r_id, start_pos, self.pathfinder)

        # Assign tasks to robots sequentially
        active_tasks = copy.deepcopy(task_list)
        for i, task in enumerate(active_tasks):
            r_ids = list(robots.keys())
            r_id = r_ids[i % len(r_ids)]
            robots[r_id].set_goal(task.dropoff_pos)

        ticks = 0
        total_wait_stalls = 0
        completion_ticks_per_task: Dict[str, int] = {}

        while ticks < max_ticks:
            ticks += 1
            all_done = True

            # Check mutual proximity
            occupied_positions = {r_id: r.current_pos for r_id, r in robots.items()}

            for r_id, robot in robots.items():
                if not robot.planned_path:
                    continue
                all_done = False

                if robot.wait_cooldown > 0:
                    robot.wait_cooldown -= 1
                    total_wait_stalls += 1
                    continue

                next_cell = robot.planned_path[0]

                # Naive conflict check: check if next cell or adjacent cell has another robot
                conflict = False
                for other_id, other_pos in occupied_positions.items():
                    if other_id == r_id:
                        continue
                    # Cell collision or blind proximity stop
                    dist = abs(next_cell[0] - other_pos[0]) + abs(next_cell[1] - other_pos[1])
                    if dist <= 1:
                        conflict = True
                        break

                if conflict:
                    # Blind stop-and-wait penalty: wait 3 ticks
                    robot.wait_cooldown = 3
                    total_wait_stalls += 1
                else:
                    # Move
                    robot.current_pos = robot.planned_path.pop(0)
                    occupied_positions[r_id] = robot.current_pos

                    if not robot.planned_path:
                        completion_ticks_per_task[r_id] = ticks

            if all_done:
                break

        return {
            "mode": "NAIVE_BASELINE_STOP_AND_WAIT",
            "total_ticks": ticks,
            "total_wait_stalls": total_wait_stalls,
            "completion_ticks_per_task": completion_ticks_per_task,
        }
