from __future__ import annotations

import csv
import json
import platform
import random
import sys
from collections import defaultdict
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prescription_mcp.router_features import FEATURE_NAMES


DATA = ROOT / "data" / "public" / "processed"
MODEL_DIR = ROOT / "prescription_mcp" / "data"
SEEDS = [20260115, 20260116, 20260117, 20260118, 20260119]


def load_rows() -> list[dict]:
    with (DATA / "router_pairs_public_policy.csv").open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def split_indices(rows: list[dict], seed: int) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = defaultdict(list)
    group_labels = {}
    for index, row in enumerate(rows):
        grouped[row["group_id"]].append(index)
        group_labels[row["group_id"]] = row["expert_label"]
    by_label = defaultdict(list)
    for group, label in group_labels.items():
        by_label[label].append(group)
    rng = random.Random(seed)
    assignments = {"train": [], "validation": [], "test": []}
    for groups in by_label.values():
        rng.shuffle(groups)
        n = len(groups)
        train_end = round(n * 0.70)
        validation_end = train_end + round(n * 0.15)
        for split, selected in [
            ("train", groups[:train_end]),
            ("validation", groups[train_end:validation_end]),
            ("test", groups[validation_end:]),
        ]:
            for group in selected:
                assignments[split].extend(grouped[group])
    return assignments


def make_model(seed: int) -> Pipeline:
    return Pipeline([
        ("scale", StandardScaler()),
        ("router", MLPClassifier(
            hidden_layer_sizes=(24, 12),
            activation="relu",
            solver="adam",
            alpha=1e-4,
            batch_size=32,
            learning_rate_init=5e-4,
            max_iter=200,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=15,
            random_state=seed,
        )),
    ])


def main() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    x = np.asarray([[float(row[name]) for name in FEATURE_NAMES] for row in rows], dtype=float)
    y = np.asarray([row["expert_label"] for row in rows])
    runs = []
    primary = None
    primary_split = None
    for seed in SEEDS:
        split = split_indices(rows, seed)
        model = make_model(seed)
        model.fit(x[split["train"]], y[split["train"]])
        validation_prediction = model.predict(x[split["validation"]])
        prediction = model.predict(x[split["test"]])
        labels = ["ExpertA", "ExpertB", "ExpertC"]
        precision, recall, f1, support = precision_recall_fscore_support(y[split["test"]], prediction, labels=labels, zero_division=0)
        run = {
            "seed": seed,
            "train_pairs": len(split["train"]),
            "validation_pairs": len(split["validation"]),
            "test_pairs": len(split["test"]),
            "validation_accuracy": accuracy_score(y[split["validation"]], validation_prediction),
            "accuracy": accuracy_score(y[split["test"]], prediction),
            "macro_f1": f1_score(y[split["test"]], prediction, average="macro"),
            "confusion_matrix": confusion_matrix(y[split["test"]], prediction, labels=labels).tolist(),
            "per_expert": {labels[i]: {"precision": precision[i], "recall": recall[i], "f1": f1[i], "support": int(support[i])} for i in range(3)},
        }
        runs.append(run)
        if seed == SEEDS[0]:
            primary = model
            primary_split = split
    assert primary is not None and primary_split is not None
    probabilities = primary.predict_proba(x[primary_split["test"]])
    predictions = primary.classes_[probabilities.argmax(axis=1)]
    thresholds = []
    for threshold in [0.50, 0.60, 0.70, 0.80, 0.90]:
        accepted = probabilities.max(axis=1) >= threshold
        thresholds.append({
            "threshold": threshold,
            "coverage": float(accepted.mean()),
            "accepted_accuracy": float(accuracy_score(y[primary_split["test"]][accepted], predictions[accepted])) if accepted.any() else None,
        })
    metrics = {
        "evidence_scope": "Policy-label replication on public drug labels and Synthea indicators; not clinical performance",
        "labels": list(primary.classes_),
        "feature_names": FEATURE_NAMES,
        "runs": runs,
        "accuracy_mean": float(np.mean([run["accuracy"] for run in runs])),
        "accuracy_sd": float(np.std([run["accuracy"] for run in runs], ddof=1)),
        "macro_f1_mean": float(np.mean([run["macro_f1"] for run in runs])),
        "macro_f1_sd": float(np.std([run["macro_f1"] for run in runs], ddof=1)),
        "threshold_sensitivity_primary_seed": thresholds,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }
    artifact = {"model": primary, "feature_names": FEATURE_NAMES, "classes": list(primary.classes_), "metrics": metrics}
    joblib.dump(artifact, MODEL_DIR / "router_model_public.joblib")
    (MODEL_DIR / "router_metrics_public.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    with (DATA / "router_primary_split.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["pair_id", "group_id", "expert_label", "split"])
        writer.writeheader()
        for split_name, indices in primary_split.items():
            for index in indices:
                writer.writerow({"pair_id": rows[index]["pair_id"], "group_id": rows[index]["group_id"], "expert_label": rows[index]["expert_label"], "split": split_name})
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
