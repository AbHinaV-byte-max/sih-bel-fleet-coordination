"""
Unit Tests for Grid A* Pathfinding (SIH 26123 - Bharat Electronics Limited).
Validates obstacle avoidance, dynamic obstacle updates, congestion history penalties, and human zone biasing.
"""

import pytest
from services.robot_agent.pathfinding import GridAStarPathfinder


def test_straight_path_nominal():
    """Verify standard shortest path in empty grid."""
    pf = GridAStarPathfinder(width=10, height=10, static_obstacles=set())
    path = pf.find_path(start=(0, 0), goal=(0, 4))
    assert path == [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]


def test_static_obstacle_avoidance():
    """Verify path navigates around a wall of static obstacles."""
    obstacles = {(2, 0), (2, 1), (2, 2)}
    pf = GridAStarPathfinder(width=10, height=10, static_obstacles=obstacles)
    path = pf.find_path(start=(0, 1), goal=(4, 1))

    assert path is not None
    # Ensure no obstacle cells are included in path
    for cell in path:
        assert cell not in obstacles
    assert path[0] == (0, 1)
    assert path[-1] == (4, 1)


def test_dynamic_obstacle_avoidance():
    """Verify path dynamically detours when dynamic obstacles are passed at query time."""
    pf = GridAStarPathfinder(width=10, height=10, static_obstacles=set())
    # Block straight line (1, 1) to (1, 3) dynamically
    dynamic_obs = {(1, 2)}
    path = pf.find_path(start=(1, 1), goal=(1, 3), dynamic_obstacles=dynamic_obs)

    assert path is not None
    assert (1, 2) not in path
    assert path[-1] == (1, 3)


def test_congestion_penalty_proactive_reroute():
    """
    Verify Amazon Robotics DeepFleet-style proactive rerouting:
    Pathfinder prefers a slightly longer path around an intersection with elevated conflict history.
    """
    pf = GridAStarPathfinder(width=10, height=10, static_obstacles=set())

    # Path directly through (2, 1) would be 4 steps: (0, 1) -> (1, 1) -> (2, 1) -> (3, 1) -> (4, 1)
    # If (2, 1) has high congestion penalty, pathfinder should route around it (e.g. via y=0 or y=2)
    congestion_penalties = {(2, 1): 10.0}

    path = pf.find_path(
        start=(0, 1),
        goal=(4, 1),
        congestion_penalties=congestion_penalties,
    )

    assert path is not None
    # Must NOT pass through heavily congested cell (2, 1)
    assert (2, 1) not in path
    assert path[-1] == (4, 1)


def test_human_zone_biasing():
    """
    Verify that robots proactively route around human-presence safety zones when
    an alternative route of comparable distance exists.
    """
    # Human zone from x=2..3, y=1..2
    human_zones = [(2, 1, 3, 2)]
    pf = GridAStarPathfinder(width=10, height=10, static_obstacles=set(), human_zones=human_zones)

    # Route from (0, 1) to (5, 1)
    path = pf.find_path(start=(0, 1), goal=(5, 1), human_zone_penalty=5.0)

    assert path is not None
    # Verify path steps outside human zone
    for cell in path:
        x, y = cell
        assert not (2 <= x <= 3 and 1 <= y <= 2)
