"""
Hybrid Priority Model Trainer (SIH 26123 - BEL).

Trains a DecisionTreeClassifier(max_depth=5) on the synthetic dataset produced by
generate_training_data.py. Holds out 20% for validation, prints accuracy, feature
importances, and the full decision tree as a human-readable rule set.

DESIGN CHOICE — max_depth=5:
  Deliberately shallow to keep the model interpretable. Every prediction path can
  be expressed as ≤5 if-else rules, satisfying defense-grade explainability
  requirements. sklearn's export_text() renders the full tree as readable text.

RESEARCH NOTE:
  "While machine learning methods have been explored, their superiority over
  search-based methods remains inconclusive." (MAPF research, 2025/2026).
  This model does NOT replace the deterministic arbiter — it only pre-adjusts
  priority weights feeding into it (RL-guided Prioritized Planning pattern).

Usage:
    python scripts/train_priority_model.py [--data PATH] [--model-out PATH]

Output:
    models/priority_model.pkl          — trained classifier
    models/validation_metrics.json     — accuracy, report, feature importances
"""

import sys
import os
import json
import pickle
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FEATURE_NAMES = [
    "task_urgency",
    "battery_pct_norm",
    "distance_to_conflict_norm",
    "congestion_score_norm",
    "payload_kg_norm",
    "robot_type_weight_norm",
]


def parse_args():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description="Train hybrid priority DecisionTree")
    parser.add_argument(
        "--data", type=str,
        default=os.path.join(base, "models", "training_data.csv"),
        help="Path to training_data.csv"
    )
    parser.add_argument(
        "--model-out", type=str,
        default=os.path.join(base, "models", "priority_model.pkl"),
        help="Output model pickle path"
    )
    parser.add_argument(
        "--metrics-out", type=str,
        default=os.path.join(base, "models", "validation_metrics.json"),
        help="Output validation metrics JSON path"
    )
    parser.add_argument(
        "--max-depth", type=int, default=5,
        help="DecisionTree max_depth (default 5 for interpretability)"
    )
    parser.add_argument(
        "--test-size", type=float, default=0.2,
        help="Validation split fraction (default 0.2)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print(f"\n{'='*60}")
    print(f"  Hybrid Priority Model -- Trainer")
    print(f"  SIH PS 26123 | Bharat Electronics Limited")
    print(f"{'='*60}")

    # --- Dependency check ---
    try:
        import numpy as np
        from sklearn.tree import DecisionTreeClassifier, export_text
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score, classification_report
    except ImportError as e:
        print(f"\n  ERROR: {e}")
        print("  Install dependencies: pip install scikit-learn numpy")
        sys.exit(1)

    # --- Load data ---
    if not os.path.exists(args.data):
        print(f"\n  ERROR: Training data not found at {args.data}")
        print("  Run: python scripts/generate_training_data.py first.")
        sys.exit(1)

    import csv
    rows = []
    with open(args.data, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    print(f"\n  Loaded {len(rows)} samples from {args.data}")
    if len(rows) < 20:
        print("  WARNING: Very few samples. Run generate_training_data.py with more episodes.")

    X = np.array([[float(r[fn]) for fn in FEATURE_NAMES] for r in rows])
    y = np.array([int(r["label"]) for r in rows])

    # Label distribution
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    print(f"  Label balance: {n_pos} positive ({n_pos/len(y)*100:.1f}%) "
          f"/ {n_neg} negative ({n_neg/len(y)*100:.1f}%)")

    # --- Train/val split ---
    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=args.test_size, random_state=42, stratify=y if n_pos > 1 and n_neg > 1 else None
    )
    print(f"  Train: {len(X_train)} samples  |  Val: {len(X_val)} samples")

    # --- Train ---
    print(f"\n  Training DecisionTreeClassifier(max_depth={args.max_depth}, random_state=42)...")
    clf = DecisionTreeClassifier(
        max_depth=args.max_depth,
        random_state=42,
        class_weight="balanced",   # Handle imbalanced label distribution
        min_samples_leaf=3,        # Prevent overfitting on tiny leaves
    )
    clf.fit(X_train, y_train)

    # --- Validate ---
    y_pred = clf.predict(X_val)
    acc = accuracy_score(y_val, y_pred)
    report = classification_report(y_val, y_pred, labels=[0, 1], target_names=["poor_priority", "good_priority"],
                                   output_dict=True, zero_division=0)
    importances = dict(zip(FEATURE_NAMES, [round(float(v), 4) for v in clf.feature_importances_]))

    print(f"\n  {'-'*50}")
    print(f"  Validation Accuracy:  {acc*100:.2f}%")
    print(f"  {'-'*50}")
    print(f"  Feature Importances:")
    for fname, imp in sorted(importances.items(), key=lambda x: -x[1]):
        bar = "#" * int(imp * 30)
        print(f"    {fname:<35} {imp:.4f}  {bar}")
    print(f"  {'-'*50}")

    # --- Print human-readable decision tree ---
    print(f"\n  Decision Tree Rules (max_depth={args.max_depth}) -- Full Interpretable Rule Set:")
    print(f"  {'-'*50}")
    tree_text = export_text(clf, feature_names=FEATURE_NAMES, max_depth=args.max_depth)
    for line in tree_text.split("\n")[:60]:   # Cap output at 60 lines for readability
        print(f"    {line}")
    if tree_text.count("\n") > 60:
        print("    ... (truncated for display; see validation_metrics.json for full tree)")
    print(f"  {'-'*50}")

    # --- Save model ---
    os.makedirs(os.path.dirname(args.model_out), exist_ok=True)
    with open(args.model_out, "wb") as f:
        pickle.dump(clf, f)
    print(f"\n  [+] Model saved:    {args.model_out}")

    # --- Save validation metrics ---
    metrics = {
        "validation_accuracy": round(acc, 4),
        "n_train_samples": len(X_train),
        "n_val_samples": len(X_val),
        "max_depth": args.max_depth,
        "feature_importances": importances,
        "classification_report": report,
        "decision_tree_rules": tree_text,
        "label_distribution": {"positive": int(n_pos), "negative": int(n_neg)},
        "model_path": args.model_out,
        "research_note": (
            "Hybrid AI layer -- DecisionTreeClassifier(max_depth=5) implementing the "
            "RL-guided Prioritized Planning pattern (MAPF research 2025/2026). "
            "This model ONLY adjusts yield_priority_weight before deterministic "
            "LocalConflictArbiter.arbitrate() runs. Zero-collision guarantee is "
            "architecturally preserved: the learned layer feeds inputs to the arbiter, "
            "it never receives or overrides the arbiter's output decisions."
        ),
    }
    with open(args.metrics_out, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"  [+] Metrics saved:  {args.metrics_out}")

    print(f"\n  Hybrid priority layer is now ACTIVE.")
    print(f"  Restart the server to load the new model:")
    print(f"  python -m uvicorn services.api_gateway.app:app --port 8000\n")


if __name__ == "__main__":
    main()
