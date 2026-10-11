"""USER-RUN ONLY: register the trusted fitted artifact and explicitly infer in a warehouse."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument(
        "--python-version", required=True, help="user-confirmed warehouse runtime; must match 3.14"
    )
    args = parser.parse_args()
    manifest = json.loads((args.export_dir / "export_manifest.json").read_text())
    for gate in ["feature_parity.json", "fixture_parity.json"]:
        if json.loads((args.export_dir / gate).read_text())["status"] != "PASS":
            raise ValueError("feature parity must pass before registry access")
    if args.python_version != "3.14":
        raise ValueError(
            "trained runtime is 3.14; do not silently change runtime or retrain for this pilot"
        )
    for package, version in manifest["model_dependencies"].items():
        if importlib.metadata.version(package) != version:
            raise ValueError(f"client package {package} differs from trusted trained environment")
    if hashlib.sha256(args.model.read_bytes()).hexdigest() != manifest["model_checksum"]:
        raise ValueError("trusted fitted model checksum mismatch")
    # Only load your own checksum-verified artifact. No arbitrary downloaded pickle.
    model = joblib.load(args.model)
    local = pd.read_csv(args.export_dir / "local_feature_parity.csv")
    names = list(model.feature_names_in_)
    dependencies = [
        f"{package}=={version}" for package, version in manifest["model_dependencies"].items()
    ]
    from keyed_candidate import KeyedCandidate
    from snowflake.ml.model import custom_model
    from snowflake.ml.registry import Registry
    from user_session import user_session

    session = user_session()
    try:
        registry = Registry(session=session, database_name="GRIDCAST_PILOT", schema_name="FEATURES")
        version_name = "V_" + manifest["model_checksum"][:16].upper() + "_KEYS1"
        adapter = KeyedCandidate(custom_model.ModelContext(candidate=model))
        sample = local[names].astype(float).copy()
        sample["row_id"] = np.arange(len(sample), dtype=np.int64)
        # If already registered, retrieve it. Do not create a second version on retry.
        existing = registry.show_models()
        if "GRIDCAST_CANDIDATE" in existing.get("name", pd.Series(dtype=str)).str.upper().tolist():
            registered = registry.get_model("GRIDCAST_CANDIDATE")
            versions = registered.show_versions()
            if version_name in versions.get("name", pd.Series(dtype=str)).str.upper().tolist():
                version = registered.version(version_name)
            else:
                version = registry.log_model(
                    adapter,
                    model_name="GRIDCAST_CANDIDATE",
                    version_name=version_name,
                    sample_input_data=sample,
                    python_version=args.python_version,
                    conda_dependencies=dependencies,
                    target_platforms=["WAREHOUSE"],
                    comment=manifest["model_checksum"],
                )
        else:
            version = registry.log_model(
                adapter,
                model_name="GRIDCAST_CANDIDATE",
                version_name=version_name,
                sample_input_data=sample,
                python_version=args.python_version,
                conda_dependencies=dependencies,
                target_platforms=["WAREHOUSE"],
                comment=manifest["model_checksum"],
            )
        warehouse = (
            pd.read_csv(args.export_dir / "warehouse_features.csv")
            .sort_values(["origin", "horizon"])
            .reset_index(drop=True)
        )
        inputs = warehouse[names].astype(float).copy()
        inputs["row_id"] = np.arange(len(inputs), dtype=np.int64)
        # Explicit warehouse batch inference. Returned row_id protects key association.
        output = version.run(inputs, function_name="predict")
        output.columns = output.columns.str.lower()
        if (
            set(output.columns) != {"row_id", "prediction"}
            or output.row_id.duplicated().any()
            or set(output.row_id) != set(inputs.row_id)
        ):
            raise ValueError("warehouse batch output identity mismatch")
        predictions = warehouse[["origin", "horizon"]].copy()
        predictions["row_id"] = inputs.row_id
        predictions = predictions.merge(output, on="row_id", validate="one_to_one").drop(
            columns="row_id"
        )
        if not np.isfinite(predictions.prediction).all() or (predictions.prediction < 0).any():
            raise ValueError("invalid warehouse predictions")
        predictions.to_csv(args.export_dir / "warehouse_predictions.csv", index=False)
        from importlib import import_module

        import_module("04_compare").compare(args.export_dir, predictions=True)
        forecast = predictions.copy()
        forecast["target"] = (
            pd.to_datetime(forecast.origin, utc=True) + pd.to_timedelta(forecast.horizon, unit="h")
        ).astype(str)
        feature_hash = hashlib.sha256(
            (args.export_dir / "local_feature_parity.csv").read_bytes()
        ).hexdigest()
        forecast["logical_id"] = [
            hashlib.sha256(f"{origin}|{manifest['release_id']}|{feature_hash}".encode()).hexdigest()
            for origin in forecast.origin
        ]
        forecast["authority"], forecast["metric"], forecast["unit"] = "PJM", "D", "megawatthours"
        forecast["release_id"], forecast["model_version"], forecast["mode"] = (
            manifest["release_id"],
            version_name,
            "HISTORICAL_SNAPSHOT_CANDIDATE_PARITY",
        )
        forecast.columns = forecast.columns.str.upper()
        session.create_dataframe(forecast).write.mode("overwrite").save_as_table(
            "GRIDCAST_PILOT.ANALYTICS.FORECAST_LOAD", table_type="temporary"
        )
        source = "(SELECT * REPLACE(TO_TIMESTAMP_TZ(ORIGIN) AS ORIGIN,TO_TIMESTAMP_TZ(TARGET) AS TARGET) FROM GRIDCAST_PILOT.ANALYTICS.FORECAST_LOAD)"
        on = "t.LOGICAL_ID=s.LOGICAL_ID AND t.HORIZON=s.HORIZON"
        if session.sql(
            f"SELECT COUNT(*) FROM GRIDCAST_PILOT.ANALYTICS.FORECAST t JOIN {source} s ON {on} WHERE NOT EQUAL_NULL(t.PREDICTION,s.PREDICTION)"
        ).collect()[0][0]:
            raise ValueError("immutable forecast identity conflict")
        merge = f"MERGE INTO GRIDCAST_PILOT.ANALYTICS.FORECAST t USING {source} s ON {on} WHEN NOT MATCHED THEN INSERT ALL BY NAME"
        session.sql(merge).collect()
        count = session.sql("SELECT COUNT(*) FROM GRIDCAST_PILOT.ANALYTICS.FORECAST").collect()[0][
            0
        ]
        session.sql(merge).collect()
        if (
            session.sql("SELECT COUNT(*) FROM GRIDCAST_PILOT.ANALYTICS.FORECAST").collect()[0][0]
            != count
        ):
            raise ValueError("forecast replay duplicated rows")
        (args.export_dir / "warehouse_registry.json").write_text(
            json.dumps(
                {
                    "status": "PASS",
                    "model": "GRIDCAST_CANDIDATE",
                    "version": version_name,
                    "checksum": manifest["model_checksum"],
                    "python": args.python_version,
                    "dependencies": dependencies,
                    "rows": len(forecast),
                    "replay_count": count,
                },
                indent=2,
            )
        )
    finally:
        session.sql("ALTER WAREHOUSE GRIDCAST_WH SUSPEND").collect()
        session.close()


if __name__ == "__main__":
    main()
