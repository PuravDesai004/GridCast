"""USER-RUN ONLY: bounded sample/full upload with validation and duplicate-safe MERGEs."""

import argparse
import json
from pathlib import Path

import pandas as pd

VERSION_COLUMNS = {
    "version_id": "VARCHAR",
    "authority": "VARCHAR",
    "metric": "VARCHAR",
    "observation_time": "TIMESTAMP_TZ",
    "raw_value": "VARCHAR",
    "value": "DOUBLE",
    "unit": "VARCHAR",
    "first_seen": "TIMESTAMP_TZ",
    "valid": "BOOLEAN",
    "quality": "VARCHAR",
}
RECEIPT_COLUMNS = {
    "fetch_id": "VARCHAR",
    "version_id": "VARCHAR",
    "artifact_id": "VARCHAR",
    "page_offset": "BIGINT",
    "row_number": "BIGINT",
    "fetched_at": "TIMESTAMP_TZ",
    "delivery_order": "BIGINT",
}


def load(session, directory, name, schema, table, columns, keys):
    import hashlib

    manifest = json.loads((directory / "export_manifest.json").read_text())
    path = directory / f"{name}.parquet"
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][path.name]["sha256"]:
        raise ValueError("local export integrity failed before upload")
    local = pd.read_parquet(path)
    if local.duplicated(keys).any():
        raise ValueError("local input contains duplicate identities")
    stage = f"@GRIDCAST_PILOT.RAW.INPUT_STAGE/{name}"
    session.file.put(str(path.resolve()), stage, auto_compress=False, overwrite=True)
    staging = f"GRIDCAST_PILOT.{schema}.{table}_LOAD"
    destination = f"GRIDCAST_PILOT.{schema}.{table}"
    session.sql(f"CREATE OR REPLACE TEMPORARY TABLE {staging}(PAYLOAD VARIANT)").collect()
    session.sql(
        f"COPY INTO {staging} FROM (SELECT $1 FROM {stage}) FILE_FORMAT=(FORMAT_NAME='GRIDCAST_PILOT.RAW.PARQUET_FMT') FORCE=TRUE"
    ).collect()
    expressions = ",".join(
        f"PAYLOAD:{key}::{dtype} AS {key.upper()}" for key, dtype in columns.items()
    )
    incoming = f"(SELECT {expressions} FROM {staging})"
    key_sql = ",".join(key.upper() for key in keys)
    if session.sql(f"SELECT COUNT(*) FROM {incoming}").collect()[0][0] != len(local):
        raise ValueError("uploaded row count differs from local export")
    if session.sql(
        f"SELECT {key_sql} FROM {incoming} GROUP BY {key_sql} HAVING COUNT(*)>1"
    ).collect():
        raise ValueError("uploaded duplicate identities")
    if table == "OBSERVATION_VERSION":
        bad = "AUTHORITY<>'PJM' OR METRIC<>'D' OR UNIT<>'megawatthours' OR OBSERVATION_TIME IS NULL OR (VALID AND (VALUE IS NULL OR VALUE<0 OR VALUE IN ('inf'::DOUBLE,'-inf'::DOUBLE,'nan'::DOUBLE)))"
        if session.sql(f"SELECT COUNT(*) FROM {incoming} WHERE {bad}").collect()[0][0]:
            raise ValueError("source identity/time/value validation failed")
    else:
        if session.sql(
            f"SELECT COUNT(*) FROM {incoming} WHERE FETCHED_AT IS NULL OR DELIVERY_ORDER IS NULL"
        ).collect()[0][0]:
            raise ValueError("receipt chronology missing")
        if session.sql(
            f"SELECT COUNT(*) FROM {incoming} s LEFT JOIN GRIDCAST_PILOT.{schema}.OBSERVATION_VERSION v USING(VERSION_ID) WHERE v.VERSION_ID IS NULL"
        ).collect()[0][0]:
            raise ValueError("receipt refers to unknown observation version")
    on = " AND ".join(f"t.{key.upper()}=s.{key.upper()}" for key in keys)
    differences = " OR ".join(
        f"NOT EQUAL_NULL(t.{key.upper()},s.{key.upper()})" for key in columns if key not in keys
    )
    if session.sql(
        f"SELECT COUNT(*) FROM {destination} t JOIN {incoming} s ON {on} WHERE {differences}"
    ).collect()[0][0]:
        raise ValueError("immutable identity conflict; preserve destination and investigate")
    before = session.sql(f"SELECT COUNT(*) FROM {destination}").collect()[0][0]
    statement = f"MERGE INTO {destination} t USING {incoming} s ON {on} WHEN NOT MATCHED THEN INSERT ALL BY NAME"
    session.sql(statement).collect()
    after = session.sql(f"SELECT COUNT(*) FROM {destination}").collect()[0][0]
    session.sql(statement).collect()
    replay = session.sql(f"SELECT COUNT(*) FROM {destination}").collect()[0][0]
    if replay != after:
        raise ValueError("MERGE replay inserted duplicates")
    return {
        "table": destination,
        "input_rows": len(local),
        "before": before,
        "after": after,
        "replay": replay,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument(
        "--full", action="store_true", help="only after accepting the sample receipt"
    )
    parser.add_argument("--fixture", action="store_true", help="separate synthetic revision data")
    args = parser.parse_args()
    from user_session import user_session

    session = user_session()
    try:
        schema = "RAW_FIXTURE" if args.fixture else "RAW"
        version_name = (
            "fixture_versions"
            if args.fixture
            else ("observation_versions" if args.full else "sample_versions")
        )
        results = [
            load(
                session,
                args.export_dir,
                version_name,
                schema,
                "OBSERVATION_VERSION",
                VERSION_COLUMNS,
                ["version_id"],
            )
        ]
        if args.full or args.fixture:
            results.append(
                load(
                    session,
                    args.export_dir,
                    "fixture_receipts" if args.fixture else "observation_receipts",
                    schema,
                    "OBSERVATION_RECEIPT",
                    RECEIPT_COLUMNS,
                    ["fetch_id", "version_id"],
                )
            )
        (
            args.export_dir
            / ("warehouse_fixture_load.json" if args.fixture else "warehouse_load.json")
        ).write_text(json.dumps(results, indent=2))
    finally:
        session.sql("ALTER WAREHOUSE GRIDCAST_WH SUSPEND").collect()
        session.close()


if __name__ == "__main__":
    main()
