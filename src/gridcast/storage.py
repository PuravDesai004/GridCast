"""Typed history: content identity and delivery chronology are separate."""

import math

import duckdb
import pandas as pd

from .config import utc
from .util import digest, now, uid, write_json

SCHEMA = """
CREATE SEQUENCE IF NOT EXISTS delivery_sequence START 1;
CREATE TABLE IF NOT EXISTS source_artifact (
 artifact_id VARCHAR PRIMARY KEY, path VARCHAR, sanitizer VARCHAR, row_count BIGINT);
CREATE TABLE IF NOT EXISTS source_fetch (
 fetch_id VARCHAR PRIMARY KEY, fetched_at TIMESTAMPTZ, request_hash VARCHAR,
 start_time TIMESTAMPTZ, end_time TIMESTAMPTZ, kind VARCHAR, successful BOOLEAN);
ALTER TABLE source_fetch ADD COLUMN IF NOT EXISTS delivery_order BIGINT DEFAULT nextval('delivery_sequence');
CREATE TABLE IF NOT EXISTS observation_version (
 version_id VARCHAR PRIMARY KEY, authority VARCHAR, metric VARCHAR,
 observation_time TIMESTAMPTZ, raw_value VARCHAR, value DOUBLE, unit VARCHAR,
 first_seen TIMESTAMPTZ, valid BOOLEAN, quality VARCHAR);
CREATE TABLE IF NOT EXISTS observation_receipt (
 fetch_id VARCHAR, version_id VARCHAR, artifact_id VARCHAR, page_offset BIGINT,
 row_number BIGINT, PRIMARY KEY(fetch_id,version_id));
CREATE OR REPLACE VIEW observation_current AS
 SELECT * EXCLUDE(rn) FROM (
 SELECT v.*, f.fetched_at, f.fetch_id,
 row_number() OVER (PARTITION BY authority,metric,observation_time
 ORDER BY f.fetched_at DESC,f.delivery_order DESC) rn
 FROM observation_version v JOIN observation_receipt r USING(version_id)
 JOIN source_fetch f USING(fetch_id) WHERE valid AND successful) WHERE rn=1;
CREATE TABLE IF NOT EXISTS feature_snapshot (
 snapshot_id VARCHAR, horizon INTEGER, origin TIMESTAMPTZ, target TIMESTAMPTZ,
 mode VARCHAR, feature_hash VARCHAR, eligible_hash VARCHAR, features VARCHAR,
 PRIMARY KEY(snapshot_id,horizon));
CREATE TABLE IF NOT EXISTS feature_lineage (
 snapshot_id VARCHAR, horizon INTEGER, feature VARCHAR, version_id VARCHAR,
 observation_time TIMESTAMPTZ, available_at TIMESTAMPTZ,
 PRIMARY KEY(snapshot_id,horizon,feature,version_id));
CREATE TABLE IF NOT EXISTS forecast_batch (
 logical_id VARCHAR PRIMARY KEY, release_id VARCHAR, snapshot_id VARCHAR,
 origin TIMESTAMPTZ, mode VARCHAR, requested_model VARCHAR, serving_path VARCHAR,
 output_hash VARCHAR, status VARCHAR, source_age DOUBLE, committed_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS forecast (
 logical_id VARCHAR, authority VARCHAR, metric VARCHAR, origin TIMESTAMPTZ,
 target TIMESTAMPTZ, horizon INTEGER, release_id VARCHAR, snapshot_id VARCHAR,
 prediction DOUBLE, unit VARCHAR, mode VARCHAR, requested_model VARCHAR,
 serving_path VARCHAR, PRIMARY KEY(logical_id,horizon));
CREATE TABLE IF NOT EXISTS forecast_attempt (
 attempt_id VARCHAR PRIMARY KEY, logical_id VARCHAR, attempted_at TIMESTAMPTZ,
 status VARCHAR, reason VARCHAR, inserted_rows BIGINT, export_status VARCHAR);
CREATE TABLE IF NOT EXISTS forecast_error (
 logical_id VARCHAR, horizon INTEGER, actual_version VARCHAR, policy VARCHAR,
 actual DOUBLE, signed_error DOUBLE, absolute_error DOUBLE,
 evaluated_at TIMESTAMPTZ, PRIMARY KEY(logical_id,horizon,actual_version,policy));
"""


def connect(workspace):
    connection = duckdb.connect(str(workspace.db))
    connection.execute(f"SET threads={workspace.settings.threads}")
    connection.execute("SET TimeZone='UTC'")
    connection.execute(SCHEMA)
    return connection


def normalize(row, unit, authority="PJM", metric="D"):
    if row.get("respondent") != authority or row.get("type") != metric:
        raise ValueError("source facet mismatch")
    timestamp = utc(row["period"] + "Z")
    if timestamp != timestamp.floor("h"):
        raise ValueError("source timestamp not hourly")
    if row.get("value-units") != unit:
        raise ValueError("source unit mismatch")
    raw = str(row.get("value", ""))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = math.nan
    valid = math.isfinite(value) and value >= 0
    quality = (
        "invalid"
        if not valid
        else "zero"
        if value == 0
        else ("extreme_positive" if value > 300000 else "valid")
    )
    identity = {
        "authority": authority,
        "metric": metric,
        "time": timestamp.isoformat(),
        "raw": raw,
        "unit": unit,
    }
    return {
        "version_id": digest(identity),
        **identity,
        "value": value if valid else None,
        "valid": valid,
        "quality": quality,
    }


def publish_window(workspace, pages, start, end, unit, fetched_at=None, kind="REAL_EIA"):
    """Only publish an already complete, contract-validated window in one transaction."""
    from .util import file_hash

    fetched_at = fetched_at or now()
    fetch_id = uid()
    records = []
    seen = {}
    artifacts = []
    for offset, payload in pages:
        rows = payload["response"]["data"]
        artifact_id = digest(payload)
        artifact_path = workspace.path(f"data/raw/artifacts/{artifact_id}.json")
        write_json(artifact_path, payload, immutable=True)
        assert file_hash(artifact_path) == artifact_id
        artifacts.append(
            (artifact_id, str(artifact_path.relative_to(workspace.root)), "redact_v1", len(rows))
        )
        for number, row in enumerate(rows):
            record = normalize(row, unit)
            timestamp = utc(record["time"])
            if not utc(start) <= timestamp < utc(end):
                raise ValueError("source outside half-open window")
            if record["time"] in seen:
                if seen[record["time"]] != record["version_id"]:
                    raise ValueError("same-key source conflict within staged window")
                raise ValueError("duplicate source identity within staged window")
            seen[record["time"]] = record["version_id"]
            records.append((record, artifact_id, offset, number))
    with connect(workspace) as connection:
        connection.execute("BEGIN")
        try:
            connection.executemany(
                "INSERT INTO source_artifact VALUES (?,?,?,?) ON CONFLICT DO NOTHING", artifacts
            )
            connection.execute(
                "INSERT INTO source_fetch (fetch_id,fetched_at,request_hash,start_time,end_time,kind,successful) VALUES (?,?,?,?,?,?,true)",
                [
                    fetch_id,
                    fetched_at,
                    digest({"start": start, "end": end, "authority": "PJM", "metric": "D"}),
                    start,
                    end,
                    kind,
                ],
            )
            if records:
                version_rows = [
                    [
                        record["version_id"],
                        "PJM",
                        "D",
                        utc(record["time"]),
                        record["raw"],
                        record["value"],
                        unit,
                        utc(fetched_at),
                        record["valid"],
                        record["quality"],
                    ]
                    for record, _, _, _ in records
                ]
                delivery_rows = [
                    [fetch_id, record["version_id"], artifact_id, offset, number]
                    for record, artifact_id, offset, number in records
                ]
                connection.register(
                    "staged_versions",
                    pd.DataFrame(
                        version_rows,
                        columns=[
                            "version_id",
                            "authority",
                            "metric",
                            "observation_time",
                            "raw_value",
                            "value",
                            "unit",
                            "first_seen",
                            "valid",
                            "quality",
                        ],
                    ),
                )
                connection.register(
                    "staged_receipts",
                    pd.DataFrame(
                        delivery_rows,
                        columns=[
                            "fetch_id",
                            "version_id",
                            "artifact_id",
                            "page_offset",
                            "row_number",
                        ],
                    ),
                )
                connection.execute(
                    "INSERT INTO observation_version SELECT * FROM staged_versions ON CONFLICT DO NOTHING"
                )
                connection.execute("INSERT INTO observation_receipt SELECT * FROM staged_receipts")
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    receipt = {
        "fetch_id": fetch_id,
        "fetched_at": fetched_at,
        "start": str(start),
        "end": str(end),
        "kind": kind,
        "rows": len(records),
        "artifacts": [a[0] for a in artifacts],
        "sanitizer": "redact_v1",
        "checksum_scope": "persisted_sanitized_content",
    }
    write_json(workspace.path(f"data/raw/receipts/{fetch_id}.json"), receipt, immutable=True)
    return receipt


def source_view(workspace, cutoff=None, first=False):
    with connect(workspace) as connection:
        if cutoff is None:
            frame = connection.execute(
                "SELECT * FROM observation_current ORDER BY observation_time"
            ).df()
        else:
            direction = "ASC" if first else "DESC"
            frame = connection.execute(
                f"""
             SELECT * EXCLUDE(rn) FROM (
             SELECT v.*,f.fetched_at,f.fetch_id,
             row_number() OVER (PARTITION BY authority,metric,observation_time
               ORDER BY f.fetched_at {direction},f.delivery_order {direction}) rn
             FROM observation_version v JOIN observation_receipt r USING(version_id)
             JOIN source_fetch f USING(fetch_id) WHERE valid AND successful AND fetched_at<=?)
             WHERE rn=1 ORDER BY observation_time""",
                [cutoff],
            ).df()
    frame["observation_time"] = pd.to_datetime(frame["observation_time"], utc=True)
    return frame


def validate_source(workspace):
    from .util import file_hash, read_json

    frame = source_view(workspace)
    if frame.empty:
        raise ValueError("no valid source observations")
    settings = workspace.settings
    start = utc(settings.core_start) - pd.Timedelta(days=settings.warmup_days)
    end = utc(settings.core_end) + pd.Timedelta(days=settings.label_padding_days)
    grid = pd.date_range(start, end, freq="h", inclusive="left")
    gaps = grid.difference(pd.DatetimeIndex(frame.observation_time))
    with connect(workspace) as connection:
        artifacts = connection.execute("SELECT artifact_id,path FROM source_artifact").fetchall()
        for checksum, relative in artifacts:
            if file_hash(workspace.root / relative) != checksum:
                raise ValueError("source artifact checksum failed")
        counts = connection.execute(
            "SELECT count(*),count(*) FILTER(WHERE NOT valid),"
            "count(*) FILTER(WHERE quality='zero'),"
            "count(*) FILTER(WHERE quality='extreme_positive') "
            "FROM observation_version"
        ).fetchone()
        revisions = connection.execute(
            "SELECT count(*) FROM (SELECT observation_time FROM "
            "observation_version GROUP BY observation_time "
            "HAVING count(*)>1)"
        ).fetchone()[0]
        kind = connection.execute("SELECT DISTINCT kind FROM source_fetch").fetchall()
        connection.execute(
            "COPY (SELECT * FROM observation_version WHERE quality != 'valid') "
            "TO ? (HEADER, DELIMITER ',')",
            [str(workspace.path("reports/rejections.csv"))],
        )
    core = frame[
        (frame.observation_time >= utc(settings.core_start))
        & (frame.observation_time < utc(settings.core_end))
    ]
    report = {
        "at": now(),
        "kind": [k[0] for k in kind],
        "source_rows_current": len(frame),
        "core_observations": len(core),
        "padding_observations": len(frame) - len(core),
        "versions": counts[0],
        "rejected_versions": counts[1],
        "zero_versions": counts[2],
        "extreme_versions": counts[3],
        "revision_identities": revisions,
        "gap_count": len(gaps),
        "start": str(start),
        "end_exclusive": str(end),
        "unit": sorted(frame.unit.unique()),
        "core_start": settings.core_start,
        "core_end": settings.core_end,
        "snapshot_hash": digest(
            frame[["observation_time", "version_id"]].astype(str).to_dict("records")
        ),
    }
    pd.DataFrame({"missing_interval_end": gaps}).to_csv(
        workspace.path("reports/gaps.csv"), index=False
    )
    sealed = workspace.path("state/selection_seal.json").exists()
    write_json(
        workspace.path(
            "state/source_current_validation.json" if sealed else "state/source_validation.json"
        ),
        report,
    )
    if not sealed:
        frame.to_parquet(workspace.path("data/frozen_source.parquet"), index=False)
    contract = read_json(workspace.path("state/source_contract.json"))
    if contract["kind"] not in report["kind"] or len(report["kind"]) != 1:
        raise ValueError("real and fixture source state must be isolated")
    return report
