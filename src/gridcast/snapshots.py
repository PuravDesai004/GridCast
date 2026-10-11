"""Small network-free snapshots published as complete immutable generations."""

import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from .util import contained, file_hash, now, read_json, uid, write_json

FILES = {
    "forecast_examples.parquet",
    "evaluation_by_horizon.csv",
    "peak_error.csv",
    "health_summary.json",
    "business_findings.json",
    "model_card.md",
}


def published_directory(root):
    root = Path(root)
    # Pointer is a single atomic replacement; the prior generation remains intact.
    pointer = read_json(root / "published/current.json")
    return contained(root / "published/generations", pointer["generation_id"])


def validate_demo(directory):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if manifest.get("schema_version") != 1 or manifest.get("display_mode") != "HISTORICAL_SNAPSHOT":
        raise ValueError("unsupported demo manifest")
    if set(manifest["files"]) != FILES:
        raise ValueError("incomplete/unknown demo files")
    for relative, receipt in manifest["files"].items():
        path = contained(directory, relative)
        if (
            not path.is_file()
            or path.stat().st_size != receipt["bytes"]
            or file_hash(path) != receipt["sha256"]
        ):
            raise ValueError("demo artifact integrity failure")
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("demo artifact too large")
    forecasts = pd.read_parquet(directory / "forecast_examples.parquet")
    required = {
        "origin",
        "target",
        "horizon",
        "prediction",
        "baseline",
        "actual",
        "release_id",
        "unit",
        "split",
        "serving_path",
    }
    if not required.issubset(forecasts.columns) or forecasts.empty:
        raise ValueError("forecast example schema/coverage failed")
    for column in ["origin", "target"]:
        if (
            not isinstance(forecasts[column].dtype, pd.DatetimeTZDtype)
            or str(forecasts[column].dt.tz) != "UTC"
            or forecasts[column].isna().any()
        ):
            raise ValueError("forecast timestamps require typed nonmissing UTC values")
    for column in ["prediction", "baseline", "actual", "horizon"]:
        if not pd.api.types.is_numeric_dtype(forecasts[column]):
            raise ValueError("forecast numeric schema failed")
    if forecasts["actual"].notna().any() and (
        not np.isfinite(forecasts.actual.dropna()).all() or (forecasts.actual.dropna() < 0).any()
    ):
        raise ValueError("invalid snapshot actuals")
    if forecasts.duplicated(["origin", "horizon", "release_id"]).any():
        raise ValueError("duplicate forecast key")
    if forecasts.unit.unique().tolist() != [
        "megawatthours"
    ] or forecasts.release_id.unique().tolist() != [manifest["release_id"]]:
        raise ValueError("forecast identity/unit mismatch")
    if (
        not np.isfinite(forecasts[["prediction", "baseline"]].to_numpy()).all()
        or (forecasts[["prediction", "baseline"]] < 0).any().any()
    ):
        raise ValueError("invalid snapshot predictions")
    for _, group in forecasts.groupby("origin"):
        if sorted(group.horizon) != list(range(1, 25)):
            raise ValueError("snapshot needs complete 24 horizons")
    origin = pd.to_datetime(forecasts.origin, utc=True)
    target = pd.to_datetime(forecasts.target, utc=True)
    if (
        not ((target - origin).dt.total_seconds() / 3600 == forecasts.horizon).all()
        or not (origin == origin.dt.normalize()).all()
    ):
        raise ValueError("snapshot target/origin timestamps failed")
    metrics = pd.read_csv(directory / "evaluation_by_horizon.csv")
    expected_metrics = {
        "split",
        "model",
        "horizon",
        "paired_targets",
        "absolute_error_sum",
        "actual_abs_sum",
        "mae",
        "wape",
    }
    if (
        not expected_metrics.issubset(metrics.columns)
        or set(metrics.split) != {"validation", "test"}
        or set(metrics.model) != {"baseline", "candidate"}
    ):
        raise ValueError("evaluation schema/scope failed")
    numeric = ["horizon", "paired_targets", "absolute_error_sum", "actual_abs_sum", "mae"]
    if (
        any(not pd.api.types.is_numeric_dtype(metrics[column]) for column in numeric)
        or not np.isfinite(metrics[numeric].to_numpy()).all()
        or (metrics[numeric] < 0).any().any()
    ):
        raise ValueError("evaluation numeric schema failed")
    if not (metrics.paired_targets == metrics.paired_targets.astype(int)).all():
        raise ValueError("evaluation target counts require integers")
    if (
        metrics.duplicated(["split", "model", "horizon"]).any()
        or (metrics.paired_targets <= 0).any()
    ):
        raise ValueError("evaluation scope/coverage failed")
    if not np.allclose(
        metrics.mae, metrics.absolute_error_sum / metrics.paired_targets, rtol=1e-10
    ):
        raise ValueError("snapshot MAE arithmetic failed")
    positive = metrics.actual_abs_sum > 0
    if not np.allclose(
        metrics.loc[positive, "wape"],
        100 * metrics.loc[positive, "absolute_error_sum"] / metrics.loc[positive, "actual_abs_sum"],
        rtol=1e-10,
    ):
        raise ValueError("snapshot WAPE arithmetic failed")
    if metrics.loc[~positive, "wape"].notna().any():
        raise ValueError("zero-denominator WAPE must be unavailable")
    for (_, _), group in metrics.groupby(["split", "model"]):
        if sorted(group.horizon) != list(range(1, 25)):
            raise ValueError("incomplete horizon metrics")
    health = read_json(directory / "health_summary.json")
    if health["release_id"] != manifest["release_id"] or health["kind"] != manifest["kind"]:
        raise ValueError("health lineage mismatch")
    peaks = pd.read_csv(directory / "peak_error.csv")
    if not {"split", "model", "local_hour", "weekday", "paired_targets", "peak_mae"}.issubset(
        peaks.columns
    ):
        raise ValueError("peak schema failed")
    if not peaks.empty:
        peak_numeric = ["local_hour", "weekday", "paired_targets", "peak_mae"]
        if (
            peaks.duplicated(["split", "model", "local_hour", "weekday"]).any()
            or not np.isfinite(peaks[peak_numeric].to_numpy()).all()
            or (peaks.paired_targets <= 0).any()
            or (peaks.peak_mae < 0).any()
        ):
            raise ValueError("peak keys/numeric values failed")
    findings = read_json(directory / "business_findings.json")
    if (
        not isinstance(findings.get("findings"), list)
        or not (directory / "model_card.md").read_text(encoding="utf-8").strip()
    ):
        raise ValueError("findings/model card schema failed")
    return {
        "validated_at": now(),
        "status": "PASS",
        "generation": manifest["generation_id"],
        "forecast_rows": len(forecasts),
        "metric_rows": len(metrics),
        "manifest_hash": file_hash(directory / "manifest.json"),
    }


def export_demo(workspace, fail=False):
    from .releases import resolve_release
    from .storage import connect

    release, bundle, _ = resolve_release(workspace)
    generation_id = uid()
    directory = workspace.path(f"demo/published/generations/{generation_id}/manifest.json").parent
    try:
        predictions = pd.read_parquet(workspace.path("data/test_predictions.parquet"))
        origins = sorted(predictions.origin.unique())[:7]
        examples = predictions[predictions.origin.isin(origins)].copy()
        examples["prediction"] = examples[release["champion"]]
        examples["release_id"], examples["unit"] = release["release_id"], "megawatthours"
        examples["split"], examples["serving_path"] = "test", release["champion"]
        examples.to_parquet(directory / "forecast_examples.parquet", index=False)
        for name in ("evaluation_by_horizon.csv", "peak_error.csv"):
            shutil.copyfile(workspace.path(f"state/{name}"), directory / name)
        analysis = read_json(workspace.path("state/analysis.json"))
        write_json(directory / "business_findings.json", analysis)
        with connect(workspace) as connection:
            batches = (
                connection.execute(
                    "SELECT status,serving_path,count(*) batches FROM forecast_batch GROUP BY ALL"
                )
                .df()
                .to_dict("records")
            )
        scenarios_path = workspace.root / "docs/evidence/recovery.json"
        health = {
            "mode": "HISTORICAL_SNAPSHOT",
            "execution_origin": "LOCAL",
            "kind": release["kind"],
            "release_id": release["release_id"],
            "source": read_json(workspace.path("state/source_validation.json")),
            "validation": read_json(workspace.path("state/selection.json")),
            "test": read_json(workspace.path("state/test_result.json")),
            "fit": read_json(workspace.path("state/final_fit.json")),
            "batches": batches,
            "recovery": read_json(scenarios_path)
            if scenarios_path.exists()
            else {"status": "PENDING"},
            "generated_at": now(),
            "disclosure": "historical revisions, simulated three-hour availability; no prospective results",
        }
        write_json(directory / "health_summary.json", health)
        shutil.copyfile(bundle / "model_card.md", directory / "model_card.md")
        manifest = {
            "schema_version": 1,
            "generation_id": generation_id,
            "release_id": release["release_id"],
            "source_snapshot": release["source_snapshot"],
            "generated_at": now(),
            "kind": release["kind"],
            "display_mode": "HISTORICAL_SNAPSHOT",
            "execution_origin": "LOCAL",
            "files": {
                name: {
                    "sha256": file_hash(directory / name),
                    "bytes": (directory / name).stat().st_size,
                }
                for name in FILES
            },
        }
        write_json(directory / "manifest.json", manifest, immutable=True)
        checked = validate_demo(directory)
        if fail:
            raise RuntimeError("synthetic export interruption before pointer replacement")
        pointer = {
            "generation_id": generation_id,
            "manifest_checksum": file_hash(directory / "manifest.json"),
        }
        write_json(workspace.path("demo/published/current.json"), pointer)
        with connect(workspace) as connection:
            connection.execute(
                "UPDATE forecast_attempt SET export_status='EXPORTED' WHERE export_status='PENDING'"
            )
        write_json(workspace.path("state/demo_validation.json"), checked)
        return checked
    except Exception:
        write_json(
            workspace.path(f"state/export_failures/{generation_id}.json"),
            {
                "at": now(),
                "status": "EXPORT_PENDING",
                "database_commits_preserved": True,
                "generation_id": generation_id,
            },
            immutable=True,
        )
        raise


def load_demo(root):
    root = Path(root)
    pointer = read_json(root / "published/current.json")
    directory = published_directory(root)
    if file_hash(directory / "manifest.json") != pointer["manifest_checksum"]:
        raise ValueError("published manifest pointer mismatch")
    validate_demo(directory)
    return {
        "directory": directory,
        "manifest": read_json(directory / "manifest.json"),
        "forecasts": pd.read_parquet(directory / "forecast_examples.parquet"),
        "metrics": pd.read_csv(directory / "evaluation_by_horizon.csv"),
        "peaks": pd.read_csv(directory / "peak_error.csv"),
        "health": read_json(directory / "health_summary.json"),
        "findings": read_json(directory / "business_findings.json"),
        "model_card": (directory / "model_card.md").read_text(encoding="utf-8"),
    }
