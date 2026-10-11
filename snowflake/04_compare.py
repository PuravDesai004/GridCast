"""OFFLINE: fail closed on warehouse/local parity; no Snowflake imports or connection."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


def compare(directory, fixture=False, predictions=False):
    left_name, right_name = (
        ("local_predictions.csv", "warehouse_predictions.csv")
        if predictions
        else (
            ("local_fixture_parity.csv", "warehouse_fixture_features.csv")
            if fixture
            else ("local_feature_parity.csv", "warehouse_features.csv")
        )
    )
    left, right = pd.read_csv(directory / left_name), pd.read_csv(directory / right_name)
    keys = ["origin", "horizon"]
    for frame in (left, right):
        frame["origin"] = pd.to_datetime(frame.origin, utc=True)
        if frame.duplicated(keys).any():
            raise ValueError("duplicate parity keys")
    left, right = (frame.set_index(keys).sort_index() for frame in (left, right))
    if not left.index.equals(right.index) or set(left.columns) != set(right.columns):
        raise ValueError("parity schema/key mismatch")
    exact = {
        "local_hour",
        "weekday",
        "month",
        "weekend",
        "utc_offset_hours",
        "dst_fold",
        "count_24",
        "count_168",
    }
    for column in left.columns:
        a, b = left[column].to_numpy(float), right[column].to_numpy(float)
        if not np.allclose(
            a,
            b,
            equal_nan=True,
            rtol=0 if column in exact else 1e-9,
            atol=0 if column in exact else 1e-8,
        ):
            raise ValueError(f"parity mismatch in {column}")
    receipt = {
        "status": "PASS",
        "scope": "SYNTHETIC_REVISION" if fixture else "REAL_HISTORICAL",
        "rows": len(left),
        "columns": list(left.columns),
        "prediction_parity": predictions,
        "files": {
            name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
            for name in [left_name, right_name]
        },
    }
    (
        directory
        / (
            "prediction_parity.json"
            if predictions
            else "fixture_parity.json"
            if fixture
            else "feature_parity.json"
        )
    ).write_text(json.dumps(receipt, indent=2))
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--predictions", action="store_true")
    args = parser.parse_args()
    print(compare(args.export_dir, args.fixture, args.predictions))
