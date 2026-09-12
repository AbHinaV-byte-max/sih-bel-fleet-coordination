"""
A* Pathfinding Algorithm for Warehouse AMR Grid Navigation.
Open, auditable algorithm with zero foreign proprietary dependencies.

Features:
- 4-directional Manhattan grid navigation with turn cost penalties.
- Dynamic obstacle avoidance (temporary reserved cells).
- Congestion-history cost penalties (Amazon Robotics DeepFleet-style proactive rerouting).
- Human-presence safety zone cost biasing (prefers routes avoiding human zones if alternatives exist).
"""

import heapq
from typing import List, Tuple, Set, Dict, Optional
import math


class GridAStarPathfinder:
    def __init__(
        self,
        width: int,
        height: int,
        static_obstacles: Set[Tuple[int, int]],
        human_zones: Optional[List[Tuple[int, int, int, int]]] = None,
    ):
        self.width = width
        self.height = height
        self.static_obstacles = set(static_obstacles)
        self.human_zones = human_zones or []  # list of (min_x, min_y, max_x, max_y)

    def is_valid(self, pos: Tuple[int, int], dynamic_obstacles: Optional[Set[Tuple[int, int]]] = None) -> bool:
        x, y = pos
        if not (0 <= x < self.width and 0 <= y < self.height):
            return False
        if pos in self.static_obstacles:
            return False
        if dynamic_obstacles and pos in dynamic_obstacles:
            return False
        return True

    def in_human_zone(self, pos: Tuple[int, int]) -> bool:
        x, y = pos
        for min_x, min_y, max_x, max_y in self.human_zones:
            if min_x <= x <= max_x and min_y <= y <= max_y:
                return True
        return False

    @staticmethod
    def _heuristic(a: Tuple[int, int], b: Tuple[int, int]) -> float:
        # Manhattan distance heuristic
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def find_path(
        self,
        start: Tuple[int, int],
        goal: Tuple[int, int],
        dynamic_obstacles: Optional[Set[Tuple[int, int]]] = None,
        congestion_penalties: Optional[Dict[Tuple[int, int], float]] = None,
        human_zone_penalty: float = 3.0,
    ) -> Optional[List[Tuple[int, int]]]:
        """
        Computes the minimum cost path from start to goal using A*.
        Applies congestion history cost penalties and human zone biasing.
        """
        if start == goal:
            return [start]

        if not self.is_valid(start) or not self.is_valid(goal, dynamic_obstacles):
            # If goal is blocked by dynamic obstacle, check if start is valid
            if not self.is_valid(goal):
                return None

        # Priority queue entries: (f_score, counter, current_node, previous_direction)
        counter = 0
        frontier = [(0.0, counter, start, (0, 0))]
        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
        cost_so_far: Dict[Tuple[int, int], float] = {start: 0.0}

        # 4-connected movements: Right, Down, Left, Up
        directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]

        while frontier:
            _, _, current, prev_dir = heapq.heappop(frontier)

            if current == goal:
                # Reconstruct path
                path = []
                curr: Optional[Tuple[int, int]] = current
                while curr is not None:
                    path.append(curr)
                    curr = came_from.get(curr)
                path.reverse()
                return path

            for dx, dy in directions:
                neighbor = (current[0] + dx, current[1] + dy)

                if not self.is_valid(neighbor, dynamic_obstacles):
                    continue

                # Base step cost = 1.0
                move_cost = 1.0

                # Slight turn penalty (0.1) to encourage straight-line corridors
                if prev_dir != (0, 0) and prev_dir != (dx, dy):
                    move_cost += 0.1

                # Congestion penalty: Elevated conflict history cell
                if congestion_penalties and neighbor in congestion_penalties:
                    move_cost += congestion_penalties[neighbor]

                # Human-presence zone penalty: Biases robots to avoid human zones if alternatives exist
                if self.in_human_zone(neighbor):
                    move_cost += human_zone_penalty

                new_cost = cost_so_far[current] + move_cost

                if neighbor not in cost_so_far or new_cost < cost_so_far[neighbor]:
                    cost_so_far[neighbor] = new_cost
                    priority = new_cost + self._heuristic(neighbor, goal)
                    counter += 1
                    came_from[neighbor] = current
                    heapq.heappush(frontier, (priority, counter, neighbor, (dx, dy)))

        return None  # No valid path found
