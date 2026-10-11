"""Four scoped SQL analyses, query receipts and independent arithmetic reconciliation."""

import numpy as np
import pandas as pd

from .config import ROOT
from .releases import resolve_release
from .storage import connect
from .util import file_hash, now, read_json, write_json


def analysis_frames(workspace):
    tables = []
    for split, name in [("validation", "validation_predictions"), ("test", "test_predictions")]:
        source = pd.read_parquet(workspace.path(f"data/{name}.parquet"))
        for model in ("baseline", "candidate"):
            rows = source.copy()
            rows["split"], rows["model"] = split, model
            rows["prediction"] = rows[model]
            rows["serving_path"] = model  # raw candidate/baseline comparisons contain no fallbacks
            tables.append(rows)
    return pd.concat(tables, ignore_index=True)


def analyze(workspace):
    release, _, _ = resolve_release(workspace)
    evaluations = analysis_frames(workspace)
    demand = pd.read_parquet(workspace.path("data/frozen_source.parquet"))
    local = demand.observation_time.dt.tz_convert(workspace.settings.calendar_timezone)
    demand["month"], demand["local_hour"], demand["weekday"] = (
        local.dt.month,
        local.dt.hour,
        local.dt.weekday,
    )
    receipts, horizons, peaks = [], [], []
    directory = workspace.path("reports/sql/receipt.json").parent
    with connect(workspace) as connection:
        connection.register("evaluations", evaluations)
        connection.register("demand_scope", demand)
        for split in ("validation", "test"):
            for model in ("baseline", "candidate"):
                for name in ("error_by_horizon", "peak_demand_error"):
                    path = ROOT / "sql" / f"{name}.sql"
                    frame = connection.execute(path.read_text(), [split, model]).df()
                    frame["split"], frame["model"] = split, model
                    output = directory / f"{name}_{split}_{model}.csv"
                    frame.to_csv(output, index=False)
                    receipts.append(
                        {
                            "query": name,
                            "query_hash": file_hash(path),
                            "split": split,
                            "model": model,
                            "release_id": release["release_id"],
                            "output": str(output.relative_to(workspace.root)),
                            "checksum": file_hash(output),
                            "rows": len(frame),
                        }
                    )
                    if name == "error_by_horizon":
                        check = evaluations[
                            (evaluations.split == split) & (evaluations.model == model)
                        ]
                        numerator = float(
                            np.abs(check.prediction.to_numpy() - check.actual.to_numpy()).sum()
                        )
                        denominator = float(np.abs(check.actual.to_numpy()).sum())
                        if not (
                            np.isclose(frame.absolute_error_sum.sum(), numerator, rtol=1e-12)
                            and np.isclose(frame.actual_abs_sum.sum(), denominator, rtol=1e-12)
                            and frame.paired_targets.sum() == len(check)
                        ):
                            raise ValueError("SQL / NumPy metric reconciliation failed")
                        receipts[-1]["numpy_reconciliation"] = "PASS"
                        horizons.append(frame)
                    else:
                        check = evaluations[
                            (evaluations.split == split) & (evaluations.model == model)
                        ]
                        check = check[check.actual > check.peak_threshold]
                        if frame.paired_targets.sum() != len(check) or not np.isclose(
                            (frame.peak_mae * frame.paired_targets).sum(),
                            abs(check.prediction - check.actual).sum(),
                            rtol=1e-12,
                        ):
                            raise ValueError("SQL peak reconciliation failed")
                        receipts[-1]["numpy_reconciliation"] = "PASS"
                        peaks.append(frame)
        for name, parameters in [
            ("demand_seasonality", [workspace.settings.core_start, workspace.settings.core_end]),
            ("model_source_health", [release["release_id"]]),
        ]:
            path = ROOT / "sql" / f"{name}.sql"
            frame = connection.execute(path.read_text(), parameters).df()
            output = directory / f"{name}.csv"
            frame.to_csv(output, index=False)
            receipts.append(
                {
                    "query": name,
                    "query_hash": file_hash(path),
                    "parameters": parameters,
                    "output": str(output.relative_to(workspace.root)),
                    "checksum": file_hash(output),
                    "rows": len(frame),
                }
            )
    by_horizon = pd.concat(horizons, ignore_index=True)
    by_horizon.to_csv(workspace.path("state/evaluation_by_horizon.csv"), index=False)
    pd.concat(peaks, ignore_index=True).to_csv(workspace.path("state/peak_error.csv"), index=False)
    chosen = by_horizon[(by_horizon.split == "test") & (by_horizon.model == release["champion"])]
    worst = chosen.loc[chosen.mae.idxmax()]
    test = read_json(workspace.path("state/test_result.json"))
    native = test["metrics"][release["champion"]]
    peak_text = (f"test peak MAE is {native['peak_mae']:.2f} megawatthours across {native['peak_count']} targets. "
                 if native["peak_mae"] is not None else
                 "there are zero test peak targets; peak MAE is unavailable. ")
    findings = [
        {
            "text": f"Horizon {int(worst.horizon)} has the highest measured {release['champion']} test MAE: "
            f"{worst.mae:.2f} megawatthours across {int(worst.paired_targets)} matched targets. "
            "Review this part of the daily profile; this does not establish procurement impact.",
            "period": [test["test_start"], test["test_end_exclusive"]],
            "scope": "frozen test",
            "unit": "megawatthours",
        },
        {
            "text": f"The locked {release['champion']} has WAPE {native['wape']:.4f}% on {native['paired_targets']} "
            f"matched test targets (absolute actual denominator {native['actual_abs_sum']:.0f} megawatthours). "
            "This describes historical error under the declared availability assumption.",
            "period": [test["test_start"], test["test_end_exclusive"]],
            "scope": "frozen test",
            "unit": "megawatthours",
        },
        {
            "text": f"Above the final training-derived peak threshold {test['peak_threshold']:.2f} megawatthours, "
            f"{peak_text}"
            "Peak periods warrant review; no operational safety claim follows.",
            "period": [test["test_start"], test["test_end_exclusive"]],
            "scope": "frozen test",
            "unit": "megawatthours",
        },
    ]
    result = {
        "generated_at": now(),
        "kind": release["kind"],
        "release_id": release["release_id"],
        "query_receipts": receipts,
        "findings": findings,
        "reconciliation": "PASS",
    }
    write_json(workspace.path("state/analysis.json"), result)
    workspace.path("docs/business_findings.md").write_text(
        f"# Measured findings ({release['kind']})\n\n"
        + "\n\n".join(f["text"] for f in findings)
        + "\n\nQuery scopes, hashes, output CSVs and NumPy reconciliations: reports/sql and state/analysis.json.\n",
        encoding="utf-8",
    )
    return result
