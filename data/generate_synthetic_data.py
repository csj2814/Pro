"""Generate deterministic, de-identified synthetic mmWave training data.

This dataset is for pipeline development and demonstrations only. It must not be
used to make clinical decisions or to claim performance on real residents.
"""

from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


SEED = 20261104
ROWS_PER_SUBJECT = 240
LABELS = {
    "normal": 0,
    "apnea": 1,
    "tachycardia": 2,
    "bradycardia": 3,
    "fall": 4,
    "bed_exit": 5,
}
LABEL_WEIGHTS = (0.58, 0.12, 0.08, 0.08, 0.07, 0.07)
SEVERITY = {
    "normal": "none",
    "apnea": "high",
    "tachycardia": "medium",
    "bradycardia": "medium",
    "fall": "critical",
    "bed_exit": "low",
}
FIELDS = [
    "segment_id",
    "timestamp",
    "subject_id",
    "room_id",
    "bed_id",
    "tracked_people",
    "respiration_bpm",
    "heart_rate_bpm",
    "motion_energy",
    "range_change_m",
    "body_height_change_m",
    "signal_quality",
    "label_id",
    "label",
    "severity",
]
NUMERIC_FEATURES = FIELDS[6:12]


def clipped_gauss(rng: random.Random, mean: float, std: float, low: float, high: float) -> float:
    return min(high, max(low, rng.gauss(mean, std)))


def features_for(label: str, rng: random.Random, phase: float) -> dict[str, float]:
    """Sample plausible-looking radar-derived features for one 30-second window."""
    circadian = math.sin(phase * 2 * math.pi)

    if label == "normal":
        values = (15 + circadian, 68 + 2 * circadian, 0.07, 0.015, 0.01, 0.93)
        stds = (1.8, 6.0, 0.025, 0.009, 0.008, 0.035)
    elif label == "apnea":
        values = (3.0, 64.0, 0.025, 0.006, 0.004, 0.89)
        stds = (1.8, 7.0, 0.012, 0.004, 0.004, 0.05)
    elif label == "tachycardia":
        values = (20.0, 116.0, 0.12, 0.025, 0.015, 0.91)
        stds = (3.0, 9.0, 0.045, 0.012, 0.01, 0.04)
    elif label == "bradycardia":
        values = (11.0, 43.0, 0.035, 0.009, 0.006, 0.92)
        stds = (2.0, 4.5, 0.015, 0.005, 0.005, 0.04)
    elif label == "fall":
        values = (22.0, 104.0, 0.88, 0.72, 0.82, 0.84)
        stds = (4.0, 13.0, 0.11, 0.16, 0.13, 0.07)
    else:  # bed_exit
        values = (18.0, 82.0, 0.55, 1.05, 0.34, 0.87)
        stds = (3.0, 10.0, 0.12, 0.22, 0.11, 0.06)

    bounds = (
        (0.0, 35.0),
        (25.0, 160.0),
        (0.0, 1.0),
        (0.0, 1.8),
        (0.0, 1.2),
        (0.55, 1.0),
    )
    sampled = [
        clipped_gauss(rng, mean, std, low, high)
        for mean, std, (low, high) in zip(values, stds, bounds)
    ]
    return dict(zip(FIELDS[6:12], sampled))


def make_subject_rows(subject_number: int, split: str) -> list[dict[str, object]]:
    rng = random.Random(SEED + subject_number)
    subject_id = f"S{subject_number:03d}"
    room_id = f"R{((subject_number - 1) // 3) + 1:02d}"
    bed_id = ((subject_number - 1) % 3) + 1
    start = datetime(2026, 1, 15, 21, 0) + timedelta(days=subject_number)
    rows: list[dict[str, object]] = []

    for index in range(ROWS_PER_SUBJECT):
        label = rng.choices(tuple(LABELS), weights=LABEL_WEIGHTS, k=1)[0]
        timestamp = start + timedelta(seconds=30 * index)
        feature_values = features_for(label, rng, index / ROWS_PER_SUBJECT)
        row: dict[str, object] = {
            "segment_id": f"{split.upper()}-{subject_id}-{index + 1:04d}",
            "timestamp": timestamp.isoformat(timespec="seconds"),
            "subject_id": subject_id,
            "room_id": room_id,
            "bed_id": bed_id,
            "tracked_people": 3,
            **{key: f"{value:.3f}" for key, value in feature_values.items()},
            "label_id": LABELS[label],
            "label": label,
            "severity": SEVERITY[label],
        }
        rows.append(row)
    return rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: list[float], quantile: float) -> float:
    """Return a linearly interpolated percentile for a non-empty sequence."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] * (1 - fraction) + ordered[upper_index] * fraction


def calculate_iqr_bounds(
    training_rows: list[dict[str, object]],
) -> dict[str, dict[str, tuple[float, float]]]:
    """Learn label-specific 1.5 IQR bounds from the training split only."""
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in training_rows:
        label = str(row["label"])
        for feature in NUMERIC_FEATURES:
            grouped[label][feature].append(float(row[feature]))

    bounds: dict[str, dict[str, tuple[float, float]]] = {}
    for label, features in grouped.items():
        bounds[label] = {}
        for feature, values in features.items():
            first_quartile = percentile(values, 0.25)
            third_quartile = percentile(values, 0.75)
            iqr = third_quartile - first_quartile
            bounds[label][feature] = (
                first_quartile - 1.5 * iqr,
                third_quartile + 1.5 * iqr,
            )
    return bounds


def remove_outliers(
    rows: list[dict[str, object]],
    bounds: dict[str, dict[str, tuple[float, float]]],
) -> list[dict[str, object]]:
    """Remove rows with any numeric feature outside its label-specific bounds."""
    return [
        row
        for row in rows
        if all(
            bounds[str(row["label"])][feature][0]
            <= float(row[feature])
            <= bounds[str(row["label"])][feature][1]
            for feature in NUMERIC_FEATURES
        )
    ]


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "samples"
    split_subjects = {
        "train": range(1, 55),
        "validation": range(55, 73),
        "test": range(73, 91),
    }
    raw_splits = {
        split: [row for subject in subjects for row in make_subject_rows(subject, split)]
        for split, subjects in split_subjects.items()
    }
    bounds = calculate_iqr_bounds(raw_splits["train"])

    for split, raw_rows in raw_splits.items():
        rows = remove_outliers(raw_rows, bounds)
        write_csv(output_dir / f"{split}.csv", rows)
        print(
            f"{split}: {len(rows)} rows "
            f"({len(raw_rows) - len(rows)} outliers removed) -> "
            f"{output_dir / f'{split}.csv'}"
        )


if __name__ == "__main__":
    main()
