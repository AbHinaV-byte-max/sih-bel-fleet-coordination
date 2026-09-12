"""
Unit Tests for Hungarian Task Allocation Service (SIH 26123 - Bharat Electronics Limited).
Validates optimal matching, payload capacity constraints, battery thresholds, and dynamic re-triggering.
"""

import pytest
from services.task_allocation import (
    WarehouseTask,
    RobotCapability,
    HungarianTaskAllocator,
    TaskStatus,
    TaskPriority,
)


def test_optimal_assignment_balanced():
    """Verify that Hungarian algorithm assigns nearest idle robot to pending task."""
    allocator = HungarianTaskAllocator()

    robots = [
        RobotCapability(id="AMR-01", robot_type="STANDARD_HAULER", current_pos=(1, 1), is_busy=False),
        RobotCapability(id="AMR-02", robot_type="STANDARD_HAULER", current_pos=(20, 20), is_busy=False),
    ]

    tasks = [
        WarehouseTask(id="TASK-1", pickup_pos=(2, 2), dropoff_pos=(5, 5), payload_weight_kg=50),
        WarehouseTask(id="TASK-2", pickup_pos=(19, 19), dropoff_pos=(15, 15), payload_weight_kg=50),
    ]

    assignments = allocator.assign_tasks(robots, tasks)

    assert len(assignments) == 2
    mapping = {a.task_id: a.robot_id for a in assignments}
    assert mapping["TASK-1"] == "AMR-01"
    assert mapping["TASK-2"] == "AMR-02"
    assert tasks[0].status == TaskStatus.ASSIGNED
    assert tasks[1].status == TaskStatus.ASSIGNED


def test_payload_capacity_heterogeneous_matching():
    """Verify that heavy task is preferentially assigned to HEAVY_CARRIER even if further away."""
    allocator = HungarianTaskAllocator()

    # AMR-01 is close to task but LIGHT_RUNNER (max 50kg)
    # AMR-02 is further away but HEAVY_CARRIER (max 1000kg)
    robots = [
        RobotCapability(
            id="AMR-LIGHT",
            robot_type="LIGHT_RUNNER",
            current_pos=(2, 2),
            is_busy=False,
            max_payload_kg=50.0,
        ),
        RobotCapability(
            id="AMR-HEAVY",
            robot_type="HEAVY_CARRIER",
            current_pos=(10, 10),
            is_busy=False,
            max_payload_kg=1000.0,
        ),
    ]

    # Task requires 300kg payload
    tasks = [
        WarehouseTask(id="HEAVY-TASK", pickup_pos=(3, 3), dropoff_pos=(6, 6), payload_weight_kg=300.0),
    ]

    assignments = allocator.assign_tasks(robots, tasks)

    assert len(assignments) == 1
    assert assignments[0].task_id == "HEAVY-TASK"
    assert assignments[0].robot_id == "AMR-HEAVY"


def test_low_battery_robot_is_not_assigned():
    """Robots with critical battery (<=15%) should not be assigned new tasks."""
    allocator = HungarianTaskAllocator()

    robots = [
        RobotCapability(
            id="AMR-DEPLETED",
            robot_type="STANDARD_HAULER",
            current_pos=(1, 1),
            is_busy=False,
            battery_level_pct=10.0,
        ),
        RobotCapability(
            id="AMR-CHARGED",
            robot_type="STANDARD_HAULER",
            current_pos=(15, 15),
            is_busy=False,
            battery_level_pct=85.0,
        ),
    ]

    tasks = [
        WarehouseTask(id="TASK-A", pickup_pos=(2, 2), dropoff_pos=(4, 4)),
    ]

    assignments = allocator.assign_tasks(robots, tasks)

    assert len(assignments) == 1
    assert assignments[0].robot_id == "AMR-CHARGED"


def test_more_tasks_than_robots():
    """Verify correct partial assignment when tasks outnumber available AMRs."""
    allocator = HungarianTaskAllocator()

    robots = [
        RobotCapability(id="AMR-01", robot_type="STANDARD_HAULER", current_pos=(1, 1), is_busy=False),
    ]

    tasks = [
        WarehouseTask(id="TASK-1", pickup_pos=(2, 2), dropoff_pos=(3, 3), priority=TaskPriority.NORMAL),
        WarehouseTask(id="TASK-2", pickup_pos=(15, 15), dropoff_pos=(18, 18), priority=TaskPriority.NORMAL),
    ]

    assignments = allocator.assign_tasks(robots, tasks)

    assert len(assignments) == 1
    assert assignments[0].task_id == "TASK-1"
    assert tasks[0].status == TaskStatus.ASSIGNED
    assert tasks[1].status == TaskStatus.PENDING


def test_dynamic_retrigger_on_blocked_path():
    """Verify that reporting a blocked task resets it and reassigns to an alternate AMR."""
    allocator = HungarianTaskAllocator()

    robots = [
        RobotCapability(id="AMR-01", robot_type="STANDARD_HAULER", current_pos=(1, 1), is_busy=False),
        RobotCapability(id="AMR-02", robot_type="STANDARD_HAULER", current_pos=(5, 5), is_busy=False),
    ]

    task = WarehouseTask(id="BLOCKED-TASK-01", pickup_pos=(2, 2), dropoff_pos=(8, 8))
    catalog = {task.id: task}

    # Initial assignment
    initial_assign = allocator.assign_tasks([robots[0]], [task])
    assert initial_assign[0].robot_id == "AMR-01"
    assert task.status == TaskStatus.ASSIGNED

    # Simulate AMR-01 encountering a blockage
    retriggered = allocator.handle_blocked_task(
        task_id=task.id,
        reporting_robot_id="AMR-01",
        reason="Obstacle detected in Aisle 3 corridor",
        tasks_lookup=catalog,
    )
    assert retriggered is True
    assert task.status == TaskStatus.PENDING
    assert task.assigned_robot_id is None

    # Now AMR-01 is busy/damaged, AMR-02 is available
    robots[0].is_busy = True
    new_assign = allocator.assign_tasks(robots, [task])
    assert len(new_assign) == 1
    assert new_assign[0].robot_id == "AMR-02"
    assert task.assigned_robot_id == "AMR-02"
