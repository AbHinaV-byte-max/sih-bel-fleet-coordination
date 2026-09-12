"""
Full End-to-End Integration Test for SIH Problem Statement 26123.
Sponsored by Bharat Electronics Limited (BEL).

CRITICAL SUCCESS CRITERIA:
1. ZERO inter-robot collisions across entire scenario execution (assert collisions == 0).
2. At least 20% reduction in total task completion time vs. naive stop-and-wait baseline
   when handling overlapping, crossing, and head-on paths.
3. Multi-agent decentralization: Genuine independent processes coordinating peer-to-peer.
"""

import pytest
import time
from typing import Dict, List, Tuple

from services.robot_agent.agent import RobotAgent
from services.comms_broker.broker import ProcessMessageBus
from services.metrics.tracker import FleetMetricsTracker
from services.metrics.baseline_runner import NaiveBaselineSimulator
from services.task_allocation.task_models import WarehouseTask, TaskStatus, TaskPriority


def test_full_success_criteria_scenario():
    """
    Scenario Setup:
    4 AMRs forced into simultaneous intersecting and head-on crossing trajectories
    at central intersection (10, 10):
    - AMR-01: moves (2, 10) -> (18, 10)   (West to East)
    - AMR-02: moves (18, 10) -> (2, 10)   (East to West, HEAD-ON against AMR-01)
    - AMR-03: moves (10, 2) -> (10, 18)   (North to South, CROSSING AMR-01 and AMR-02)
    - AMR-04: moves (10, 18) -> (10, 2)   (South to North, 4-WAY CHOKE POINT)
    """
    grid_w = 24
    grid_h = 20
    # Warehouse obstacles leaving central crossroads open
    obstacles = {
        (5, 5), (5, 6), (5, 7), (5, 8),
        (15, 5), (15, 6), (15, 7), (15, 8),
        (5, 12), (5, 13), (5, 14), (5, 15),
        (15, 12), (15, 13), (15, 14), (15, 15),
    }

    bus = ProcessMessageBus(enable_security=True)
    tracker = FleetMetricsTracker()

    # Define the 4 conflicting tasks
    tasks = [
        WarehouseTask(id="TASK-W-E", pickup_pos=(2, 10), dropoff_pos=(18, 10), priority=TaskPriority.HIGH),
        WarehouseTask(id="TASK-E-W", pickup_pos=(18, 10), dropoff_pos=(2, 10), priority=TaskPriority.NORMAL),
        WarehouseTask(id="TASK-N-S", pickup_pos=(10, 2), dropoff_pos=(10, 18), priority=TaskPriority.NORMAL),
        WarehouseTask(id="TASK-S-N", pickup_pos=(10, 18), dropoff_pos=(10, 2), priority=TaskPriority.LOW),
    ]

    # Initialize 4 distinct edge robot agents
    robot_configs = [
        {"id": "AMR-01", "type": "HEAVY_CARRIER", "start": (2, 10), "prio": 3, "task": tasks[0]},
        {"id": "AMR-02", "type": "STANDARD_HAULER", "start": (18, 10), "prio": 2, "task": tasks[1]},
        {"id": "AMR-03", "type": "STANDARD_HAULER", "start": (10, 2), "prio": 2, "task": tasks[2]},
        {"id": "AMR-04", "type": "LIGHT_RUNNER", "start": (10, 18), "prio": 1, "task": tasks[3]},
    ]

    robots: Dict[str, RobotAgent] = {}
    for cfg in robot_configs:
        agent = RobotAgent(
            robot_id=cfg["id"],
            robot_type=cfg["type"],
            start_pos=cfg["start"],
            grid_width=grid_w,
            grid_height=grid_h,
            static_obstacles=obstacles,
            yield_priority_weight=cfg["prio"],
            bus=bus,
        )
        agent.set_task(cfg["task"])
        robots[cfg["id"]] = agent

    # -------------------------------------------------------------------------
    # 1. RUN DECENTRALIZED DECISION-SUPPORT SYSTEM (DSS)
    # -------------------------------------------------------------------------
    max_ticks = 150
    dec_ticks = 0
    all_completed = False

    while dec_ticks < max_ticks and not all_completed:
        dec_ticks += 1

        # Advance each independent robot agent
        for r_id, r in robots.items():
            r.step()

        # Check spatial occupancy: ENFORCE ZERO COLLISIONS
        current_positions = {r_id: r.current_pos for r_id, r in robots.items()}
        no_collision = tracker.verify_no_collisions(current_positions)
        assert no_collision is True, f"Collision occurred at tick {dec_ticks}: {tracker.collision_incidents}"

        # Check if all robots reached dropoffs
        completed_count = sum(1 for r in robots.values() if r.current_task is None)
        if completed_count == len(robots):
            all_completed = True

    # -------------------------------------------------------------------------
    # 2. RUN NAIVE STOP-AND-WAIT BASELINE ON IDENTICAL SCENARIO
    # -------------------------------------------------------------------------
    baseline_sim = NaiveBaselineSimulator(
        grid_width=grid_w,
        grid_height=grid_h,
        static_obstacles=obstacles,
    )
    baseline_robots = [
        {"id": cfg["id"], "start_pos": cfg["start"]}
        for cfg in robot_configs
    ]

    baseline_res = baseline_sim.run_scenario(
        robot_configs=baseline_robots,
        task_list=tasks,
        max_ticks=200,
    )
    baseline_ticks = baseline_res["total_ticks"]

    # -------------------------------------------------------------------------
    # 3. VERIFY SUCCESS CRITERIA
    # -------------------------------------------------------------------------
    # Criterion 1: ZERO Inter-Robot Collisions
    assert tracker.total_collisions == 0, (
        f"FAILED CRITERIA: Expected 0 collisions, got {tracker.total_collisions}"
    )

    # Criterion 2: At least 20% completion-time improvement vs baseline
    # Efficiency improvement = ((T_baseline - T_decentralized) / T_baseline) * 100
    improvement_pct = ((baseline_ticks - dec_ticks) / baseline_ticks) * 100.0

    print(f"\n=======================================================")
    print(f"SIH 26123 SUCCESS CRITERIA BENCHMARK RESULTS:")
    print(f"- Total Collisions:            {tracker.total_collisions} (TARGET: STRICTLY 0) -> PASSED")
    print(f"- Decentralized DSS Duration:  {dec_ticks} ticks")
    print(f"- Naive Baseline Duration:     {baseline_ticks} ticks")
    print(f"- Baseline Wait Stalls:        {baseline_res['total_wait_stalls']} stalls")
    print(f"- Efficiency Improvement:      {improvement_pct:.1f}% (TARGET: >= 20.0%) -> PASSED")
    print(f"=======================================================\n")

    assert improvement_pct >= 20.0, (
        f"FAILED CRITERIA: Expected >= 20% improvement, got {improvement_pct:.1f}%"
    )
