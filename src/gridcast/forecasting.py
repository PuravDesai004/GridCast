"""Exactly 24 predictions or zero; features, lineage and success share one transaction."""

import joblib
import pandas as pd
from threadpoolctl import threadpool_limits

from .features import FEATURES, baseline, build_features, clip_predictions, frame_records, gates
from .releases import resolve_release
from .storage import connect, source_view
from .util import canonical, digest, now, uid, write_json


def forecast(workspace, origin, release_id=None, fail_after=None, source=None):
    # Resolve once. Baseline fallback is independent of model deserialization.
    release, directory, corrupt = resolve_release(workspace, release_id)
    settings = workspace.settings
    if source is None:
        source = (
            pd.read_parquet(workspace.path("data/frozen_source.parquet"))
            if settings.availability_mode == "retrospective"
            else source_view(workspace, origin)
        )
    batch = build_features(source, origin, settings)
    logical_id = digest(
        {
            "authority": settings.authority,
            "metric": settings.metric,
            "origin": str(batch.origin),
            "release": release["release_id"],
            "snapshot": batch.snapshot_id,
            "mode": settings.availability_mode,
        }
    )
    attempt_id = uid()
    requested = release["champion"]
    serving, reason = requested, []
    predictions = None
    clipping = 0
    if requested == "candidate":
        reason = gates(batch.frame, settings)
        if corrupt:
            reason.append("CORRUPT_BUNDLE")
        if not reason:
            try:
                model = joblib.load(directory / "candidate.joblib")
                with threadpool_limits(limits=settings.threads):
                    predictions, clipping = clip_predictions(model.predict(batch.frame[FEATURES]))
            except Exception:
                reason.append("MODEL_FAILURE")
        if reason:
            serving = "seasonal_fallback"
    elif corrupt:
        reason.append("CORRUPT_BUNDLE")
        serving = "seasonal_fallback"
    if predictions is None:
        try:
            predictions = baseline(batch.frame)
        except ValueError:
            reason.append("MISSING_BASELINE_LAG")
            serving = "UNAVAILABLE"
    status = "UNAVAILABLE" if predictions is None else "SUCCESS"
    rows = []
    if predictions is not None:
        for horizon, prediction in enumerate(predictions, 1):
            rows.append(
                {
                    "logical_id": logical_id,
                    "authority": settings.authority,
                    "metric": settings.metric,
                    "origin": batch.origin,
                    "target": batch.origin + pd.Timedelta(hours=horizon),
                    "horizon": horizon,
                    "release_id": release["release_id"],
                    "snapshot_id": batch.snapshot_id,
                    "prediction": float(prediction),
                    "unit": "megawatthours",
                    "mode": settings.availability_mode,
                    "requested_model": requested,
                    "serving_path": serving,
                }
            )
    output_hash = digest(
        [{k: str(v) if isinstance(v, pd.Timestamp) else v for k, v in row.items()} for row in rows]
        if rows
        else {"status": "UNAVAILABLE", "serving": serving}
    )
    inserted = 0
    with connect(workspace) as connection:
        previous = connection.execute(
            "SELECT output_hash,status FROM forecast_batch WHERE logical_id=?", [logical_id]
        ).fetchone()
        if previous:
            if previous != (output_hash, status):
                connection.execute(
                    "INSERT INTO forecast_attempt VALUES (?,?,?,?,?,?,?)",
                    [
                        attempt_id,
                        logical_id,
                        now(),
                        "NONDETERMINISM",
                        "conflicting output checksum",
                        0,
                        "NOT_REQUIRED",
                    ],
                )
                raise ValueError("forecast replay nondeterminism detected")
            connection.execute(
                "INSERT INTO forecast_attempt VALUES (?,?,?,?,?,?,?)",
                [attempt_id, logical_id, now(), "REPLAY", "equal output checksum", 0, "PENDING"],
            )
        else:
            connection.execute("BEGIN")
            try:
                feature_rows = [
                    {
                        "snapshot_id": batch.snapshot_id,
                        "horizon": h + 1,
                        "origin": batch.origin,
                        "target": batch.origin + pd.Timedelta(hours=h + 1),
                        "mode": batch.mode,
                        "feature_hash": batch.feature_hash,
                        "eligible_hash": batch.eligible_hash,
                        "features": canonical(record).decode(),
                    }
                    for h, record in enumerate(frame_records(batch.frame))
                ]
                connection.register("staged_features", pd.DataFrame(feature_rows))
                connection.execute(
                    "INSERT INTO feature_snapshot SELECT * FROM staged_features ON CONFLICT DO NOTHING"
                )
                if batch.lineage:
                    lineage_frame = pd.DataFrame(batch.lineage)
                    lineage_frame.insert(0, "snapshot_id", batch.snapshot_id)
                    connection.register("staged_lineage", lineage_frame)
                    connection.execute(
                        "INSERT INTO feature_lineage SELECT * FROM staged_lineage ON CONFLICT DO NOTHING"
                    )
                for row in rows:
                    connection.execute(
                        "INSERT INTO forecast VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        list(row.values()),
                    )
                    inserted += 1
                    if fail_after and inserted == fail_after:
                        raise RuntimeError("synthetic interrupted transaction")
                age = batch.frame.latest_age_hours.iloc[0]
                connection.execute(
                    "INSERT INTO forecast_batch VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        logical_id,
                        release["release_id"],
                        batch.snapshot_id,
                        batch.origin,
                        batch.mode,
                        requested,
                        serving,
                        output_hash,
                        status,
                        float(age) if pd.notna(age) else None,
                        now(),
                    ],
                )
                connection.execute(
                    "INSERT INTO forecast_attempt VALUES (?,?,?,?,?,?,?)",
                    [attempt_id, logical_id, now(), status, ",".join(reason), inserted, "PENDING"],
                )
                connection.execute("COMMIT")
            except Exception as error:
                connection.execute("ROLLBACK")
                connection.execute(
                    "INSERT INTO forecast_attempt VALUES (?,?,?,?,?,?,?)",
                    [
                        attempt_id,
                        logical_id,
                        now(),
                        "FAILED",
                        type(error).__name__,
                        0,
                        "NOT_REQUIRED",
                    ],
                )
                raise
    receipt = {
        "at": now(),
        "attempt_id": attempt_id,
        "logical_id": logical_id,
        "origin": str(batch.origin),
        "snapshot_id": batch.snapshot_id,
        "feature_hash": batch.feature_hash,
        "eligible_hash": batch.eligible_hash,
        "release_id": release["release_id"],
        "requested_model": requested,
        "serving_path": serving,
        "status": status,
        "replay": previous is not None,
        "inserted_rows": inserted,
        "output_hash": output_hash,
        "clipped_targets": clipping,
        "gate_reasons": reason,
    }
    write_json(
        workspace.path(f"state/forecast_receipts/{attempt_id}.json"), receipt, immutable=True
    )
    return receipt
