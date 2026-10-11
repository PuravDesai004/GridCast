"""Execute final local replay/daily and trained-candidate leakage checks; package evidence."""

import ast
import shutil
import sqlite3

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from gridcast.config import ROOT, Workspace, load_settings, utc
from gridcast.features import FEATURES, build_features, frame_records
from gridcast.storage import connect
from gridcast.training import verify_seal
from gridcast.util import digest, file_hash, now, read_json, write_json
from gridcast.workflow import run


def counts(workspace):
    with connect(workspace) as connection:
        return {
            name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
            for name in [
                "source_fetch",
                "observation_version",
                "observation_receipt",
                "forecast",
                "feature_snapshot",
                "feature_lineage",
                "forecast_batch",
                "forecast_error",
                "forecast_attempt",
            ]
        }


def main():
    workspace = Workspace(ROOT, load_settings(ROOT / "config/project.yaml"))
    verify_seal(workspace)
    fixed = [
        "state/selection_seal.json",
        "state/first_test_evaluation.json",
        "state/candidate.joblib",
        "state/test_result.json",
    ]
    before_hashes = {path: file_hash(ROOT / path) for path in fixed}
    before = counts(workspace)
    run(workspace, "daily", offline=True, origin="2025-10-01T00:00:00Z")
    after = counts(workspace)
    after_hashes = {path: file_hash(ROOT / path) for path in fixed}
    assert before_hashes == after_hashes
    for table in before:
        if table != "forecast_attempt":
            assert before[table] == after[table]
    write_json(
        ROOT / "docs/evidence/daily_replay.json",
        {
            "at": now(),
            "status": "PASS",
            "command": "python -m gridcast run --mode daily --offline --origin 2025-10-01T00:00:00Z",
            "before": before,
            "after": after,
            "fixed_hashes": before_hashes,
            "retraining": False,
            "test_reevaluation": False,
        },
    )
    source = pd.read_parquet(ROOT / "data/frozen_source.parquet")
    model = joblib.load(ROOT / "state/candidate.joblib")
    origin = utc("2025-10-01T00:00:00Z")
    initial = build_features(source, origin, workspace.settings, lineage=False)
    unavailable = source.observation_time + pd.Timedelta(hours=3) > origin
    altered = source.copy()
    altered.loc[unavailable, "value"] = 999999.0
    appended = altered[unavailable].copy()
    appended["observation_time"] += pd.Timedelta(days=366)
    appended["version_id"] = "UNAVAILABLE_FUTURE_" + appended.version_id
    variants = {
        "mutate": altered,
        "append": pd.concat([source, appended], ignore_index=True),
        "delete": source[~unavailable].copy(),
        "reorder": source.sample(frac=1, random_state=42),
    }
    records = []
    with threadpool_limits(limits=2):
        original = np.maximum(model.predict(initial.frame[FEATURES]), 0)
        for name, variant in variants.items():
            batch = build_features(variant, origin, workspace.settings, lineage=False)
            predictions = np.maximum(model.predict(batch.frame[FEATURES]), 0)
            assert (
                batch.feature_hash == initial.feature_hash
                and batch.eligible_hash == initial.eligible_hash
            )
            assert np.array_equal(predictions, original)
            records.append(
                {
                    "operation": name,
                    "status": "PASS",
                    "feature_hash": batch.feature_hash,
                    "eligible_hash": batch.eligible_hash,
                    "prediction_hash": digest(predictions.tolist()),
                    "full_source_values_hash": digest(
                        frame_records(variant[["value", "version_id"]])
                    ),
                }
            )
    write_json(
        ROOT / "docs/evidence/trained_candidate_leakage.json",
        {
            "at": now(),
            "status": "PASS",
            "source": "REAL_EIA_FROZEN_SOURCE",
            "origin": str(origin),
            "model_checksum": file_hash(ROOT / "state/candidate.joblib"),
            "unavailable_rows": int(unavailable.sum()),
            "delayed_before_cutoff_rows": int(
                (unavailable & (source.observation_time <= origin)).sum()
            ),
            "original_source_values_hash": digest(frame_records(source[["value", "version_id"]])),
            "records": records,
            "after_cutoff_revision_checks": "docs/evidence/leakage.json (synthetic prospective chronology)",
        },
    )
    worked = initial.frame.copy()
    worked["target"] = origin + pd.to_timedelta(worked.horizon, unit="h")
    worked["prediction"] = original
    worked.to_csv(ROOT / "docs/evidence/worked_origin.csv", index=False)
    with connect(workspace) as connection:
        connection.execute(
            "SELECT authority,metric,observation_time,count(*) version_count FROM observation_version GROUP BY ALL HAVING count(*)>1 ORDER BY observation_time"
        ).df().to_csv(ROOT / "reports/revisions.csv", index=False)
        fetches = connection.execute(
            "SELECT count(*),CAST(min(fetched_at) AS VARCHAR),CAST(max(fetched_at) AS VARCHAR) FROM source_fetch WHERE successful"
        ).fetchone()
    with sqlite3.connect(ROOT / "state/mlflow.sqlite") as database:
        runs = database.execute(
            "SELECT run_uuid,name,status,start_time,end_time FROM runs ORDER BY start_time"
        ).fetchall()
        registered = database.execute(
            "SELECT name,version,run_id,status FROM model_versions"
        ).fetchall()
    write_json(
        ROOT / "docs/evidence/mlflow.json",
        {
            "at": now(),
            "tracking": "state/mlflow.sqlite",
            "artifact_root": "state/mlflow_artifacts",
            "runs": [
                dict(zip(["run_id", "name", "status", "start_ms", "end_ms"], row)) for row in runs
            ],
            "registered": [
                dict(zip(["name", "version", "run_id", "status"], row)) for row in registered
            ],
        },
    )
    write_json(
        ROOT / "docs/evidence/source_fetch_summary.json",
        {
            "successful_fetches": fetches[0],
            "earliest_fetch": str(fetches[1]),
            "latest_fetch": str(fetches[2]),
        },
    )
    syntax = []
    for path in sorted((ROOT / "snowflake").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        syntax.append(str(path.relative_to(ROOT)))
    write_json(
        ROOT / "docs/evidence/manual_syntax.json",
        {
            "status": "PASS",
            "method": "Python AST parsing only; no Snowflake imports/connections or SQL execution",
            "files": syntax,
            "warehouse_status": "UNEXECUTED",
        },
    )
    for name in [
        "source_validation",
        "selection",
        "selection_seal",
        "first_test_evaluation",
        "test_result",
        "final_fit",
        "features",
        "feature_lineage_receipt",
        "analysis",
        "demo_validation",
    ]:
        shutil.copyfile(ROOT / f"state/{name}.json", ROOT / f"docs/evidence/{name}.json")
    shutil.copytree(ROOT / "reports/sql", ROOT / "docs/evidence/sql", dirs_exist_ok=True)
    for name in ["gaps.csv", "rejections.csv", "revisions.csv"]:
        shutil.copyfile(ROOT / f"reports/{name}", ROOT / f"docs/evidence/{name}")
    write_json(
        ROOT / "docs/evidence/final_audit.json",
        {
            "at": now(),
            "status": "PASS",
            "seal_verified": True,
            "counts": after,
            "release": read_json(ROOT / "releases/current.json"),
            "holdout_repair": False,
            "manual_snowflake": "UNEXECUTED",
        },
    )
    print("Final local audit: PASS")


if __name__ == "__main__":
    main()
