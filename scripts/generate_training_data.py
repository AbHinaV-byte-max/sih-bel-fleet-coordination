"""
Training Data Generator for Hybrid Priority Model (SIH 26123 - BEL).

Runs N synthetic simulation episodes using the existing FleetCoordinatorBridge and logs
per-conflict feature vectors with outcome quality (resulting_delay_ticks) as the label.

RESEARCH NOTE: Synthetic data generation from existing simulation is standard practice
for bootstrapping learned layers in multi-agent systems where real-world operational
data is not yet available (pre-deployment). The resulting dataset captures the statistical
distribution of conflict scenarios the fleet will encounter in the warehouse environment.

Usage:
    python scripts/generate_training_data.py [--episodes N] [--output PATH]

Output:
    models/training_data.csv — labeled dataset for train_priority_model.py
"""

import sys
import os
import csv
import random
import argparse
import time
import logging

# Silence noisy simulation logs during bulk data generation
logging.disable(logging.CRITICAL)

# Allow imports from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.api_gateway.simulation_bridge import FleetCoordinatorBridge
from services.robot_agent.hybrid_priority_advisor import HybridPriorityAdvisor


def parse_args():
    parser = argparse.ArgumentParser(description="Generate hybrid model training data")
    parser.add_argument(
        "--episodes", type=int, default=50,
        help="Number of simulation episodes to run (default: 50)"
    )
    parser.add_argument(
        "--ticks-per-episode", type=int, default=60,
        help="Simulation ticks per episode (default: 60)"
    )
    parser.add_argument(
        "--output", type=str,
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "models", "training_data.csv"),
        help="Output CSV path"
    )
    return parser.parse_args()


FIELDNAMES = [
    "task_urgency",
    "battery_pct_norm",
    "distance_to_conflict_norm",
    "congestion_score_norm",
    "payload_kg_norm",
    "robot_type_weight_norm",
    # Label: 1 = this robot having high priority led to low delay (good outcome)
    #        0 = high priority led to blocking others (bad outcome — should yield)
    "label",
    # Metadata (not used for training, kept for analysis)
    "resulting_delay_ticks",
    "episode_id",
]


def run_episode(bridge: FleetCoordinatorBridge, ticks: int, episode_id: int) -> list:
    """
    Runs one simulation episode, collecting (features, outcome) pairs for each
    conflict event observed during the episode.

    Returns a list of row dicts suitable for CSV writing.
    """
    # Reset with randomized task mix
    advisor = HybridPriorityAdvisor()
    rows = []

    # Submit 2–4 random delivery tasks
    w = bridge.config.warehouse.width
    h = bridge.config.warehouse.height
    obstacles = bridge.static_obstacles
    n_tasks = random.randint(2, 4)

    free_cells = [
        (x, y) for x in range(w) for y in range(h)
        if (x, y) not in obstacles
    ]

    for _ in range(n_tasks):
        if len(free_cells) < 2:
            break
        pickup = random.choice(free_cells)
        dropoff = random.choice([c for c in free_cells if c != pickup])
        priority = random.randint(1, 4)
        try:
            bridge.submit_task(
                pickup_pos=pickup,
                dropoff_pos=dropoff,
                payload_weight_kg=random.uniform(10.0, 250.0),
                priority_int=priority,
            )
        except Exception:
            pass

    # Run ticks and collect conflict-decision samples
    tick_start = time.time()
    conflict_ticks: dict = {}  # robot_id -> tick when conflict observed
    pre_conflict_positions: dict = {}  # robot_id -> position at conflict time

    for tick in range(ticks):
        try:
            snapshot = bridge.step()
        except Exception:
            break

        robots = snapshot.get("robots", {})
        for r_id, r_data in robots.items():
            state = r_data.get("state", "IDLE")
            last_dec = r_data.get("last_decision") or {}
            decision_type = last_dec.get("decision_type", "CONTINUE")

            if decision_type in ("YIELD", "WAIT") and r_id not in conflict_ticks:
                # Record when this robot first entered a conflict state
                conflict_ticks[r_id] = tick
                pre_conflict_positions[r_id] = tuple(r_data.get("position", [0, 0]))

                # Extract features at conflict time
                battery = r_data.get("battery_pct", 100.0)
                task_id = r_data.get("current_task_id")
                task_priority_int = 2
                payload_kg = 50.0

                # Look up task details from bridge
                if task_id and task_id in bridge.tasks:
                    task = bridge.tasks[task_id]
                    task_priority_int = getattr(task.priority, "value", 2)
                    payload_kg = getattr(task, "payload_weight_kg", 50.0)

                conflict_pos = last_dec.get("conflict_pos")
                conflict_cell = tuple(conflict_pos) if conflict_pos else None

                congestion_score = 0.0
                if conflict_cell:
                    agent = bridge.robots.get(r_id)
                    if agent:
                        congestion_score = agent.congestion_penalties.get(conflict_cell, 0.0)

                feat = advisor.extract_features(
                    task_priority_int=task_priority_int,
                    battery_pct=battery,
                    current_pos=pre_conflict_positions[r_id],
                    conflict_cell=conflict_cell,
                    congestion_penalties={conflict_cell: congestion_score} if conflict_cell else {},
                    payload_kg=payload_kg,
                    robot_type_weight=bridge.robots[r_id].yield_priority_weight if r_id in bridge.robots else 1,
                )

                rows.append({
                    "__feat": feat,
                    "__r_id": r_id,
                    "__tick": tick,
                    "episode_id": episode_id,
                })

            elif r_id in conflict_ticks and state == "MOVING":
                # Robot resumed — compute delay
                delay = tick - conflict_ticks[r_id]
                conflict_ticks.pop(r_id)

                # Find the pending row for this robot
                for row in rows:
                    if row.get("__r_id") == r_id and "__feat" in row:
                        feat = row.pop("__feat")
                        row.pop("__r_id", None)
                        row.pop("__tick", None)

                        vec = feat.to_list()
                        # Label: 1 = good priority decision (delay ≤ 3 ticks = quick resolution)
                        #        0 = poor priority decision (long blockage → should have yielded sooner)
                        label = 1 if delay <= 3 else 0

                        row.update({
                            "task_urgency": round(vec[0], 4),
                            "battery_pct_norm": round(vec[1], 4),
                            "distance_to_conflict_norm": round(vec[2], 4),
                            "congestion_score_norm": round(vec[3], 4),
                            "payload_kg_norm": round(vec[4], 4),
                            "robot_type_weight_norm": round(vec[5], 4),
                            "label": label,
                            "resulting_delay_ticks": delay,
                        })
                        break

    # Drop any unresolved (still in conflict at episode end) — ambiguous labels
    completed_rows = [r for r in rows if "label" in r and "__feat" not in r]
    return completed_rows


def main():
    args = parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  Hybrid Priority Model — Training Data Generator")
    print(f"  SIH PS 26123 | Bharat Electronics Limited")
    print(f"{'='*60}")
    print(f"  Episodes:          {args.episodes}")
    print(f"  Ticks/episode:     {args.ticks_per_episode}")
    print(f"  Output:            {args.output}")
    print(f"{'='*60}\n")

    all_rows = []
    bridge = FleetCoordinatorBridge()

    t_start = time.time()
    for ep in range(args.episodes):
        rows = run_episode(bridge, args.ticks_per_episode, episode_id=ep)
        all_rows.extend(rows)

        if (ep + 1) % 10 == 0 or ep == 0:
            elapsed = time.time() - t_start
            print(
                f"  Episode {ep+1:>4}/{args.episodes}  |  "
                f"Samples so far: {len(all_rows):>5}  |  "
                f"Elapsed: {elapsed:.1f}s",
                flush=True
            )

    print(f"\n  Total samples collected: {len(all_rows)}")
    if len(all_rows) == 0:
        print("  WARNING: No conflict events observed. Try more episodes or denser task submission.")
        return

    # Label distribution
    n_pos = sum(1 for r in all_rows if r.get("label") == 1)
    n_neg = len(all_rows) - n_pos
    print(f"  Label distribution: {n_pos} good ({n_pos/len(all_rows)*100:.1f}%) "
          f"/ {n_neg} poor ({n_neg/len(all_rows)*100:.1f}%)")

    with open(args.output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\n  [+] Saved: {args.output}")
    print(f"\nNext step: python scripts/train_priority_model.py\n")


if __name__ == "__main__":
    main()
