"""Sequential expanding folds, pre-test candidate fit and immutable evaluation seals."""

import gzip
import time

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .config import ROOT, utc
from .evaluation import choose_champion, comparison
from .features import FEATURES, SCHEMA, build_features, gates
from .util import canonical, digest, file_hash, now, read_json, versions, write_json

SEARCH = [
    {"max_leaf_nodes": leaves, "l2_regularization": l2} for leaves in (15, 31) for l2 in (0.0, 1.0)
]


def splits(workspace):
    path = workspace.root / "config/splits.yaml"
    if not path.exists():
        path = ROOT / "config/splits.yaml"
    specification = yaml.safe_load(path.read_text(encoding="utf-8"))
    start = utc(specification["train_start"])
    bounds = [utc(v) for v in specification["validation_boundaries"]]
    end = utc(specification["test_end"])
    if len(bounds) != 4 or sorted([start, *bounds, end]) != [start, *bounds, end]:
        raise ValueError("invalid chronological split specification")
    return start, bounds, end


def build_dataset(workspace):
    source = pd.read_parquet(workspace.path("data/frozen_source.parquet"))
    start, bounds, end = splits(workspace)
    origins = pd.date_range(start, end, freq="D", inclusive="left")
    rows, membership = [], []
    lineage_directory = workspace.path("data/feature_lineage/index.json").parent
    for origin in origins:
        if workspace.settings.availability_mode != "retrospective":
            raise ValueError("historical research workflow requires retrospective frozen source")
        batch = build_features(source, origin, workspace.settings, lineage=False)
        lineage_path = lineage_directory / f"{batch.snapshot_id}.json.gz"
        with lineage_path.open("wb") as stream:
            stream.write(
                gzip.compress(
                    canonical({"snapshot_id": batch.snapshot_id, "lineage": batch.compact_lineage}),
                    mtime=0,
                )
            )
        frame = batch.frame.copy()
        frame["origin"] = origin
        frame["target"] = origin + pd.to_timedelta(frame.horizon, unit="h")
        frame["snapshot_id"] = batch.snapshot_id
        frame["candidate_eligible"] = not gates(frame, workspace.settings)
        frame["baseline_eligible"] = frame.target_lag_168.notna().all()
        rows.append(frame)
        split = "train" if origin < bounds[0] else "test" if origin >= bounds[-1] else "validation"
        membership.append(
            {
                "origin": str(origin),
                "split": split,
                "snapshot_id": batch.snapshot_id,
                "feature_hash": batch.feature_hash,
                "eligible_hash": batch.eligible_hash,
                "gates": gates(frame, workspace.settings),
                "baseline_eligible": bool(frame.baseline_eligible.iloc[0]),
            }
        )
    dataset = pd.concat(rows, ignore_index=True)
    dataset.to_parquet(workspace.path("data/features.parquet"), index=False)
    write_json(
        lineage_directory / "index.json",
        {
            "grain": "snapshot x horizon x feature x version",
            "storage": "per-snapshot compressed JSON; horizon arrays expand to the exact lineage grain",
            "source_checksum": file_hash(workspace.path("data/frozen_source.parquet")),
            "membership": membership,
        },
    )
    write_json(workspace.path("state/split_membership.json"), membership)
    receipt = {
        "at": now(),
        "feature_rows": len(dataset),
        "scheduled_origins": len(origins),
        "features_checksum": file_hash(workspace.path("data/features.parquet")),
        "membership_checksum": digest(membership),
        "schema": SCHEMA,
        "labels_in_features": False,
    }
    write_json(workspace.path("state/features.json"), receipt)
    return receipt


def attach_labels(features, source, label_cutoff, delay):
    # Filter labels before attaching; selection never reads any test-window actual.
    labels = source[source.observation_time + pd.Timedelta(hours=delay) <= label_cutoff]
    result = features.merge(
        labels[["observation_time", "value"]],
        left_on="target",
        right_on="observation_time",
        how="left",
    ).rename(columns={"value": "actual"})
    return result


def fit_rows(features, source, start, cutoff, settings):
    rows = attach_labels(
        features[(features.origin >= start) & (features.origin < cutoff)],
        source,
        cutoff,
        settings.assumed_delay_hours,
    )
    valid = rows.candidate_eligible & rows.actual.notna()
    eligible = rows[valid].copy()
    if len(eligible) < 100:
        raise ValueError("insufficient eligible chronological training rows")
    return eligible, {
        "fit_cutoff": str(cutoff),
        "rows": len(eligible),
        "scheduled_origins": int(rows.origin.nunique()),
        "eligible_origins": int(eligible.origin.nunique()),
        "purged_label_rows": int(rows.actual.isna().sum()),
        "partially_purged_origins": sorted(
            str(v) for v in rows.loc[rows.actual.isna(), "origin"].unique()
        ),
        "last_target": str(eligible.target.max()),
        "membership_hash": digest(
            eligible[["origin", "horizon", "target"]].astype(str).to_dict("records")
        ),
    }


def model_for(settings, parameters):
    return HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.1,
        max_iter=settings.maximum_iterations,
        random_state=settings.seed,
        early_stopping=False,
        **parameters,
    )


def tracking(workspace):
    import mlflow

    mlflow.set_tracking_uri("sqlite:///" + workspace.path("state/mlflow.sqlite").as_posix())
    name = "GridCast_" + read_json(workspace.path("state/source_contract.json"))["kind"]
    existing = mlflow.get_experiment_by_name(name)
    if existing is None:
        mlflow.create_experiment(
            name, artifact_location=workspace.path("state/mlflow_artifacts").as_uri()
        )
    mlflow.set_experiment(name)
    return mlflow


def log_fit(
    workspace, model, train, parameters, fit_receipt, result, duration, name, register=False
):
    mlflow = tracking(workspace)
    import mlflow.sklearn as mlflow_sklearn
    from mlflow.models import infer_signature

    with mlflow.start_run(run_name=name) as run:
        mlflow.log_params(
            {
                **parameters,
                "seed": workspace.settings.seed,
                "early_stopping": False,
                "max_iter": workspace.settings.maximum_iterations,
                "fit_cutoff": fit_receipt["fit_cutoff"],
                "mode": workspace.settings.availability_mode,
                "delay_hours": workspace.settings.assumed_delay_hours,
                "source_hash": read_json(workspace.path("state/source_validation.json"))[
                    "snapshot_hash"
                ],
                "feature_version": "clock_features_v1",
                "authority": "PJM",
                "unit": "megawatthours",
            }
        )
        mlflow.log_metrics(
            {k: v for k, v in result.items() if isinstance(v, (int, float)) and v is not None}
        )
        mlflow.log_metric("fit_seconds", duration)
        mlflow.log_dict(fit_receipt, "fit_receipt.json")
        mlflow.log_dict(versions(), "dependency_versions.json")
        mlflow.log_dict(read_json(workspace.path("state/features.json")), "features.json")
        leakage = workspace.root / "docs/evidence/leakage.json"
        if leakage.exists():
            mlflow.log_artifact(str(leakage))
        signature = infer_signature(
            train[FEATURES].head(24), model.predict(train[FEATURES].head(24))
        )
        info = mlflow_sklearn.log_model(
            model,
            name="candidate",
            signature=signature,
            input_example=train[FEATURES].head(2),
            serialization_format="cloudpickle",
        )
        registered = (
            mlflow.register_model(info.model_uri, "GridCast_PJM_Candidate") if register else None
        )
        return {
            "run_id": run.info.run_id,
            "model_uri": info.model_uri,
            "registry_version": registered.version if registered else None,
            "duration_seconds": duration,
        }


def backtest(workspace, compact=False):
    if workspace.path("state/first_test_evaluation.json").exists():
        raise ValueError("holdout already viewed: selection may not be retuned in this workspace")
    started = time.perf_counter()
    features = pd.read_parquet(workspace.path("data/features.parquet"))
    source = pd.read_parquet(workspace.path("data/frozen_source.parquet"))
    start, bounds, _ = splits(workspace)
    # Ensure exploratory labels are strictly pre-test before any fold is fitted.
    source = source[
        source.observation_time + pd.Timedelta(hours=workspace.settings.assumed_delay_hours)
        <= bounds[-1]
    ]
    configurations = SEARCH[:1] if compact else SEARCH
    candidates, all_predictions = [], []
    for index, parameters in enumerate(configurations):
        predictions, folds = [], []
        for lower, upper in zip(bounds[:-1], bounds[1:], strict=True):
            train, fit_receipt = fit_rows(features, source, start, lower, workspace.settings)
            peak = float(train.actual.quantile(0.9))
            validation = attach_labels(
                features[(features.origin >= lower) & (features.origin < upper)],
                source,
                upper,
                workspace.settings.assumed_delay_hours,
            )
            complete_actuals = validation.groupby("origin").actual.transform("count") == 24
            paired = validation[
                complete_actuals & validation.candidate_eligible & validation.baseline_eligible
            ].copy()
            model = model_for(workspace.settings, parameters)
            timer = time.perf_counter()
            with threadpool_limits(limits=workspace.settings.threads):
                model.fit(train[FEATURES], train.actual)
                raw = model.predict(paired[FEATURES]) if len(paired) else np.array([])
            duration = time.perf_counter() - timer
            paired["candidate"] = np.maximum(raw, 0)
            paired["baseline"] = paired.target_lag_168
            paired["peak_threshold"] = peak
            paired["fold"] = str(lower)
            result = comparison(paired)
            receipt = {
                **fit_receipt,
                "validation_start": str(lower),
                "validation_end": str(upper),
                "scheduled_validation_origins": int(validation.origin.nunique()),
                "paired_origins": int(paired.origin.nunique()),
                "paired_targets": len(paired),
                "candidate_native_origins": int(
                    validation.loc[validation.candidate_eligible, "origin"].nunique()
                ),
                "baseline_native_origins": int(
                    validation.loc[validation.baseline_eligible, "origin"].nunique()
                ),
                "missing_actual_targets": int(validation.actual.isna().sum()),
                "purged_validation_origins": sorted(
                    str(v) for v in validation.loc[~complete_actuals, "origin"].unique()
                ),
                "quality_failed_origins": int(
                    validation.loc[~validation.candidate_eligible, "origin"].nunique()
                ),
                "clipped_targets": int((raw < 0).sum()),
                "peak_threshold": peak,
                "peak_threshold_basis": "training eligible labels quantile .90",
                "metrics": result,
            }
            tracked = log_fit(
                workspace,
                model,
                train,
                parameters,
                receipt,
                result["candidate"],
                duration,
                f"configuration_{index}_fold_{lower.month}",
            )
            folds.append({**receipt, "mlflow": tracked})
            predictions.append(paired)
            print(
                f"configuration {index}, fold {lower.date()}: {len(paired)} matched targets",
                flush=True,
            )
        paired_all = pd.concat(predictions, ignore_index=True)
        aggregate = comparison(paired_all)
        scheduled = sum(f["scheduled_validation_origins"] for f in folds)
        coverage = paired_all.origin.nunique() / scheduled if scheduled else 0
        candidates.append(
            {
                "index": index,
                "parameters": parameters,
                "metrics": aggregate,
                "scheduled_origins": scheduled,
                "paired_origins": int(paired_all.origin.nunique()),
                "coverage": coverage,
                "folds": folds,
            }
        )
        all_predictions.append(paired_all)
    best = min(
        candidates,
        key=lambda c: (
            c["metrics"]["candidate"]["wape"]
            if c["metrics"]["candidate"]["wape"] is not None
            else float("inf")
        ),
    )
    decision = choose_champion(best["metrics"], best["coverage"], workspace.settings)
    selection = {
        "at": now(),
        "kind": read_json(workspace.path("state/source_contract.json"))["kind"],
        "search": candidates,
        "chosen_configuration": best["parameters"],
        "chosen_index": best["index"],
        "validation_metrics": best["metrics"],
        "decision": decision,
        "duration_seconds": time.perf_counter() - started,
        "final_fit_cutoff": str(bounds[-1]),
    }
    all_predictions[best["index"]].to_parquet(
        workspace.path("data/validation_predictions.parquet"), index=False
    )
    write_json(workspace.path("state/selection.json"), selection)
    return selection


def prediction_files(workspace):
    files = [
        "data/frozen_source.parquet",
        "data/features.parquet",
        "state/split_membership.json",
        "state/features.json",
        "state/selection.json",
        "state/final_fit.json",
        "state/candidate.joblib",
        "state/source_contract.json",
        "state/source_validation.json",
        "state/feature_lineage_receipt.json",
    ]
    hashes = {name: file_hash(workspace.path(name)) for name in files}
    for name in (
        "features.py",
        "training.py",
        "evaluation.py",
        "forecasting.py",
        "releases.py",
        "config.py",
        "source.py",
        "storage.py",
        "util.py",
    ):
        hashes[f"code/{name}"] = file_hash(ROOT / "src/gridcast" / name)
    for name in ("project.yaml", "splits.yaml", "feature_contract.yaml"):
        path = workspace.root / "config" / name
        hashes[f"config/{name}"] = file_hash(path if path.exists() else ROOT / "config" / name)
    return hashes


def seal_selection(workspace):
    path = workspace.path("state/selection_seal.json")
    if path.exists():
        verify_seal(workspace)
        return read_json(path)
    lineage_directory = workspace.path("data/feature_lineage/index.json").parent
    lineage_receipt = {
        "grain": "snapshot x horizon x feature x version",
        "files": {p.name: file_hash(p) for p in sorted(lineage_directory.iterdir()) if p.is_file()},
    }
    write_json(
        workspace.path("state/feature_lineage_receipt.json"), lineage_receipt, immutable=True
    )
    selection = read_json(workspace.path("state/selection.json"))
    features = pd.read_parquet(workspace.path("data/features.parquet"))
    source = pd.read_parquet(workspace.path("data/frozen_source.parquet"))
    start, bounds, _ = splits(workspace)
    train, receipt = fit_rows(features, source, start, bounds[-1], workspace.settings)
    model = model_for(workspace.settings, selection["chosen_configuration"])
    timer = time.perf_counter()
    with threadpool_limits(limits=workspace.settings.threads):
        model.fit(train[FEATURES], train.actual)
    duration = time.perf_counter() - timer
    joblib.dump(model, workspace.path("state/candidate.joblib"))
    receipt.update(
        {
            "model_checksum": file_hash(workspace.path("state/candidate.joblib")),
            "parameters": selection["chosen_configuration"],
            "peak_threshold": float(train.actual.quantile(0.9)),
            "mlflow": log_fit(
                workspace,
                model,
                train,
                selection["chosen_configuration"],
                receipt,
                {},
                duration,
                "final_pretest_fit",
                register=True,
            ),
            "fitted_at": now(),
            "schema": SCHEMA,
        }
    )
    write_json(workspace.path("state/final_fit.json"), receipt, immutable=True)
    seal = {
        "sealed_at": now(),
        "files": prediction_files(workspace),
        "settings": workspace.settings.model_dump(),
        "dependencies": versions(),
        "champion": selection["decision"]["champion"],
        "policies": {
            "clipping": "nonnegative_clip_v1",
            "baseline": "week_lag_v1",
            "peak": "training_q90",
        },
    }
    seal["seal_hash"] = digest(seal)
    write_json(path, seal, immutable=True)
    return seal


def verify_seal(workspace):
    seal = read_json(workspace.path("state/selection_seal.json"))
    if (
        seal["files"] != prediction_files(workspace)
        or seal["dependencies"] != versions()
        or seal["settings"] != workspace.settings.model_dump()
    ):
        raise ValueError("missing/changed selection seal; frozen test evaluation rejected")
    content = {k: v for k, v in seal.items() if k != "seal_hash"}
    if digest(content) != seal["seal_hash"]:
        raise ValueError("seal fingerprint mismatch")
    return seal


def evaluate_test(workspace):
    seal = verify_seal(workspace)
    first_path = workspace.path("state/first_test_evaluation.json")
    if first_path.exists():
        first = read_json(first_path)
        if (
            first["seal_hash"] != seal["seal_hash"]
            or file_hash(workspace.path(first["result_path"])) != first["result_checksum"]
        ):
            raise ValueError("first test evaluation conflict")
        return read_json(workspace.path(first["result_path"]))
    features = pd.read_parquet(workspace.path("data/features.parquet"))
    source = pd.read_parquet(workspace.path("data/frozen_source.parquet"))
    _, bounds, end = splits(workspace)
    validation_end = end + pd.Timedelta(days=workspace.settings.label_padding_days)
    test = attach_labels(
        features[(features.origin >= bounds[-1]) & (features.origin < end)],
        source,
        validation_end,
        workspace.settings.assumed_delay_hours,
    )
    complete = test.groupby("origin").actual.transform("count") == 24
    paired = test[complete & test.candidate_eligible & test.baseline_eligible].copy()
    fit = read_json(workspace.path("state/final_fit.json"))
    model = joblib.load(workspace.path("state/candidate.joblib"))
    with threadpool_limits(limits=workspace.settings.threads):
        raw = model.predict(paired[FEATURES]) if len(paired) else np.array([])
    paired["candidate"] = np.maximum(raw, 0)
    paired["baseline"] = paired.target_lag_168
    paired["peak_threshold"] = fit["peak_threshold"]
    paired.to_parquet(workspace.path("data/test_predictions.parquet"), index=False)
    result = {
        "evaluated_at": now(),
        "seal_hash": seal["seal_hash"],
        "test_start": str(bounds[-1]),
        "test_end_exclusive": str(end),
        "champion": seal["champion"],
        "metrics": comparison(paired),
        "scheduled_origins": int(test.origin.nunique()),
        "paired_origins": int(paired.origin.nunique()),
        "paired_targets": len(paired),
        "coverage": paired.origin.nunique() / test.origin.nunique(),
        "candidate_native_origins": int(test.loc[test.candidate_eligible, "origin"].nunique()),
        "baseline_native_origins": int(test.loc[test.baseline_eligible, "origin"].nunique()),
        "missing_actuals": int(test.actual.isna().sum()),
        "quality_failed_origins": int(test.loc[~test.candidate_eligible, "origin"].nunique()),
        "clipped_targets": int((raw < 0).sum()),
        "peak_threshold": fit["peak_threshold"],
        "holdout_viewed": True,
        "prediction_checksum": file_hash(workspace.path("data/test_predictions.parquet")),
    }
    path = "state/test_result.json"
    write_json(workspace.path(path), result, immutable=True)
    write_json(
        first_path,
        {
            "first_evaluated_at": result["evaluated_at"],
            "seal_hash": seal["seal_hash"],
            "result_path": path,
            "result_checksum": file_hash(workspace.path(path)),
            "model_checksum_before_test": fit["model_checksum"],
        },
        immutable=True,
    )
    return result
