"""Explicit matched denominators and immutable delayed error vintages."""

import numpy as np
import pandas as pd

from .config import utc
from .storage import connect, source_view
from .util import now, read_json, write_json


def metrics(actual, prediction, peak_threshold=None):
    actual, prediction = np.asarray(actual, dtype=float), np.asarray(prediction, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(prediction)
    actual, prediction = actual[mask], prediction[mask]
    errors = prediction - actual
    count = len(actual)
    numerator, denominator = float(np.abs(errors).sum()), float(np.abs(actual).sum())
    peak = actual > peak_threshold if peak_threshold is not None else np.zeros(count, dtype=bool)
    return {
        "paired_targets": count,
        "absolute_error_sum": numerator,
        "actual_abs_sum": denominator,
        "mae": numerator / count if count else None,
        "wape": 100 * numerator / denominator if denominator else None,
        "signed_bias": float(errors.mean()) if count else None,
        "peak_threshold": peak_threshold,
        "peak_count": int(peak.sum()),
        "peak_absolute_error_sum": float(np.abs(errors[peak]).sum()),
        "peak_mae": float(np.abs(errors[peak]).mean()) if peak.any() else None,
    }


def comparison(frame):
    result = {}
    for model in ("baseline", "candidate"):
        result[model] = metrics(frame.actual, frame[model])
        peak = frame.actual > frame.peak_threshold
        result[model]["peak_count"] = int(peak.sum())
        result[model]["peak_absolute_error_sum"] = float(
            abs(frame.loc[peak, model] - frame.loc[peak, "actual"]).sum()
        )
        result[model]["peak_mae"] = (
            (result[model]["peak_absolute_error_sum"] / int(peak.sum())) if peak.any() else None
        )
    return result


def choose_champion(result, coverage, settings):
    b, c = result["baseline"], result["candidate"]
    reduction = None
    if b["wape"] is not None and b["wape"] > 0 and c["wape"] is not None:
        reduction = (b["wape"] - c["wape"]) / b["wape"]
    peak_ok = (
        b["peak_mae"] is not None
        and c["peak_mae"] is not None
        and c["peak_mae"] <= settings.maximum_peak_mae_ratio * b["peak_mae"]
    )
    candidate = (
        reduction is not None
        and reduction >= settings.minimum_relative_wape_improvement
        and peak_ok
        and coverage >= settings.minimum_paired_origin_coverage
    )
    return {
        "champion": "candidate" if candidate else "baseline",
        "relative_wape_reduction": reduction,
        "peak_gate_passed": peak_ok,
        "paired_origin_coverage": coverage,
        "coverage_gate_passed": coverage >= settings.minimum_paired_origin_coverage,
        "selection_rule": "wape >=2% relative improvement; peak <=1.05 baseline; >=90% scheduled origins",
    }


def evaluate_outcomes(workspace, cutoff=None, policy=None):
    settings = workspace.settings
    cutoff = utc(cutoff or now())
    if settings.availability_mode == "retrospective":
        policy = policy or "retrospective_frozen"
        if policy != "retrospective_frozen":
            raise ValueError("retrospective actual policy must be frozen")
        actuals = pd.read_parquet(workspace.path("data/frozen_source.parquet"))
        actuals = actuals[
            actuals.observation_time + pd.Timedelta(hours=settings.assumed_delay_hours) <= cutoff
        ]
    else:
        policy = policy or "prospective_latest_revision"
        if policy not in {"prospective_first_seen", "prospective_latest_revision"}:
            raise ValueError("invalid prospective actual policy")
        actuals = source_view(workspace, cutoff, first=policy == "prospective_first_seen")
        actuals = actuals[actuals.observation_time <= cutoff]
    inserted = 0
    with connect(workspace) as connection:
        forecasts = connection.execute(
            "SELECT * FROM forecast WHERE mode=?", [settings.availability_mode]
        ).df()
        if not forecasts.empty:
            merged = forecasts.merge(
                actuals,
                left_on=["authority", "metric", "target", "unit"],
                right_on=["authority", "metric", "observation_time", "unit"],
            )
            for row in merged.itertuples():
                existed = connection.execute(
                    "SELECT count(*) FROM forecast_error WHERE logical_id=? "
                    "AND horizon=? AND actual_version=? AND policy=?",
                    [row.logical_id, row.horizon, row.version_id, policy],
                ).fetchone()[0]
                if not existed:
                    error = row.prediction - row.value
                    connection.execute(
                        "INSERT INTO forecast_error VALUES (?,?,?,?,?,?,?,?)",
                        [
                            row.logical_id,
                            row.horizon,
                            row.version_id,
                            policy,
                            row.value,
                            error,
                            abs(error),
                            now(),
                        ],
                    )
                    inserted += 1
    receipt = {"at": now(), "policy": policy, "cutoff": str(cutoff), "new_error_vintages": inserted}
    write_json(workspace.path("state/outcomes.json"), receipt)
    return receipt


def test_results(workspace):
    receipt = read_json(workspace.path("state/first_test_evaluation.json"))
    return read_json(workspace.path(receipt["result_path"]))
