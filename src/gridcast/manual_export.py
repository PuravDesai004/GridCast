"""Local portable inputs for the user-run Snowflake pilot; no warehouse access."""

import importlib.metadata

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .config import utc
from .features import FEATURES, build_features
from .storage import connect
from .util import file_hash, now, read_json, write_json


def revision_fixture(settings):
    """Clearly synthetic collector chronology with a B receipt followed by an A reversion."""
    times = pd.date_range("2025-01-01", "2025-01-21", inclusive="left", freq="h", tz="UTC")
    source = pd.DataFrame({"observation_time": times})
    source["value"] = 80000.0 + 5000.0 * np.sin(np.arange(len(times)) * 2 * np.pi / 24)
    source["authority"], source["metric"], source["unit"] = "PJM", "D", "megawatthours"
    source["version_id"] = [f"SYNTHETIC_A_{i}" for i in range(len(source))]
    source["valid"], source["quality"] = True, "OK"
    source["raw_value"] = source.value.astype(str)
    source["first_seen"] = source.observation_time + pd.Timedelta(hours=3)
    receipts = source[["version_id", "first_seen"]].rename(columns={"first_seen": "fetched_at"})
    revised = source[source.observation_time == pd.Timestamp("2025-01-18T20:00Z")].copy()
    original_id = revised.version_id.iloc[0]
    revised["version_id"] = "SYNTHETIC_B_REVISION"
    revised["value"] += 1000
    revised["raw_value"] = revised.value.astype(str)
    revised["first_seen"] = pd.Timestamp("2025-01-18T23:30Z")
    source = pd.concat([source, revised], ignore_index=True)
    receipts = pd.concat(
        [
            receipts,
            pd.DataFrame(
                {
                    "version_id": ["SYNTHETIC_B_REVISION", original_id],
                    "fetched_at": pd.to_datetime(
                        ["2025-01-18T23:30Z", "2025-01-19T23:00Z"], utc=True
                    ),
                }
            ),
        ],
        ignore_index=True,
    )
    receipts = receipts.sort_values("fetched_at").reset_index(drop=True)
    receipts["delivery_order"] = np.arange(1, len(receipts) + 1)
    receipts["fetch_id"] = [f"SYNTHETIC_FETCH_{i}" for i in receipts.delivery_order]
    receipts["artifact_id"], receipts["page_offset"], receipts["row_number"] = "SYNTHETIC", 0, 0
    delivered = source.merge(receipts, on="version_id")
    return source, receipts, delivered


def export_snowflake(workspace):
    directory = workspace.path("reports/snowflake/export_manifest.json").parent
    with connect(workspace) as connection:
        versions = connection.execute(
            "SELECT * FROM observation_version ORDER BY observation_time,version_id"
        ).df()
        receipts = connection.execute(
            "SELECT r.*,f.fetched_at,f.delivery_order FROM observation_receipt r JOIN source_fetch f USING(fetch_id) WHERE successful ORDER BY delivery_order,version_id"
        ).df()
    for frame, name in [(versions, "observation_versions"), (receipts, "observation_receipts")]:
        for column in ["observation_time", "first_seen", "fetched_at"]:
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], utc=True).dt.strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                )
        frame.to_parquet(directory / f"{name}.parquet", index=False)
    # Bounded first 14 days including a complete UTC lag warmup; user loads sample first.
    lower = utc(workspace.settings.core_start) - pd.Timedelta(days=workspace.settings.warmup_days)
    sample = versions[
        pd.to_datetime(versions.observation_time, utc=True) < lower + pd.Timedelta(days=14)
    ]
    sample.to_parquet(directory / "sample_versions.parquet", index=False)
    source = pd.read_parquet(workspace.path("data/frozen_source.parquet"))
    origins = [
        "2024-03-10T00:00:00Z",
        "2024-11-03T00:00:00Z",
        "2025-08-10T00:00:00Z",
        "2025-03-10T00:00:00Z",
        "2025-11-02T00:00:00Z",
    ]
    rows = []
    for origin in origins:
        batch = build_features(source, origin, workspace.settings, lineage=False)
        frame = batch.frame.copy()
        frame["origin"] = batch.origin.isoformat()
        frame["horizon"] = frame.horizon.astype(int)
        rows.append(frame)
    features = pd.concat(rows, ignore_index=True)
    features.to_csv(directory / "local_feature_parity.csv", index=False)
    fixture_versions, fixture_receipts, delivered = revision_fixture(workspace.settings)
    for frame, name in [
        (fixture_versions, "fixture_versions"),
        (fixture_receipts, "fixture_receipts"),
    ]:
        for column in ["observation_time", "first_seen", "fetched_at"]:
            if column in frame:
                frame[column] = pd.to_datetime(frame[column], utc=True).dt.strftime(
                    "%Y-%m-%dT%H:%M:%S.%fZ"
                )
        frame.to_parquet(directory / f"{name}.parquet", index=False)
    prospective = workspace.settings.model_copy(update={"availability_mode": "prospective"})
    fixture_rows = []
    for origin in ["2025-01-19T00:00:00Z", "2025-01-20T00:00:00Z"]:
        batch = build_features(delivered, origin, prospective, lineage=False)
        frame = batch.frame.copy()
        frame["origin"] = batch.origin.isoformat()
        fixture_rows.append(frame)
    pd.concat(fixture_rows, ignore_index=True).to_csv(
        directory / "local_fixture_parity.csv", index=False
    )
    trusted_model = workspace.path("state/candidate.joblib")
    fit = read_json(workspace.path("state/final_fit.json"))
    if file_hash(trusted_model) != fit["model_checksum"]:
        raise ValueError("trusted trained candidate integrity failed")
    model = joblib.load(trusted_model)
    with threadpool_limits(limits=workspace.settings.threads):
        predictions = model.predict(features[FEATURES])
    pd.DataFrame(
        {
            "origin": features.origin,
            "horizon": features.horizon,
            "prediction": np.maximum(predictions, 0),
        }
    ).to_csv(directory / "local_predictions.csv", index=False)
    receipt = {
        "at": now(),
        "status": "LOCAL_EXPORT_ONLY_SNOWFLAKE_UNEXECUTED",
        "unit": "megawatthours",
        "version_rows": len(versions),
        "receipt_rows": len(receipts),
        "sample_rows": len(sample),
        "parity_origins": origins,
        "parity_rows": len(features),
        "model_checksum": fit["model_checksum"],
        "model_dependencies": {
            name: importlib.metadata.version(name)
            for name in ["scikit-learn", "numpy", "scipy", "pandas", "cloudpickle"]
        },
        "snapshot_cutoff": str(pd.to_datetime(receipts.fetched_at, utc=True).max()),
        "release_id": read_json(workspace.path("releases/current.json"))["release_id"],
        "synthetic_fixture": "Separate A-B-A prospective chronology; not real EIA evidence",
        "candidate_registry_version_local": fit["mlflow"]["registry_version"],
        "files": {
            p.name: {"sha256": file_hash(p), "rows": None}
            for p in directory.iterdir()
            if p.is_file() and p.name != "export_manifest.json"
        },
    }
    write_json(directory / "export_manifest.json", receipt)
    return receipt
