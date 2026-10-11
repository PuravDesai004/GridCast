"""USER-RUN ONLY: execute timestamp-joined warehouse features from typed observations."""

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

FEATURES = [
    "horizon",
    "local_hour",
    "weekday",
    "month",
    "weekend",
    "utc_offset_hours",
    "dst_fold",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    "target_lag_168",
    "target_lag_336",
    "latest_available_demand",
    "latest_age_hours",
    "mean_24",
    "std_24",
    "min_24",
    "max_24",
    "count_24",
    "mean_168",
    "std_168",
    "min_168",
    "max_168",
    "count_168",
    "change_24",
]


def feature_sql(origin, mode, snapshot_cutoff, fixture=False):
    # Parse ISO values before interpolation; no arbitrary SQL parameters enter the statement.
    origin = datetime.fromisoformat(origin.replace("Z", "+00:00")).isoformat()
    snapshot_cutoff = datetime.fromisoformat(snapshot_cutoff.replace("Z", "+00:00")).isoformat()
    if mode not in {"retrospective", "prospective"}:
        raise ValueError("invalid availability mode")
    receipt_cutoff = snapshot_cutoff if mode == "retrospective" else origin
    available = "DATEADD(hour,3,OBSERVATION_TIME)" if mode == "retrospective" else "FETCHED_AT"
    schema = "RAW_FIXTURE" if fixture else "RAW"
    aggregates = ",".join(
        f"{operation}(IFF(e.OBSERVATION_TIME>DATEADD(hour,-{length},a.anchor),e.VALUE,NULL)) AS {name}_{length}"
        for length in (24, 168)
        for operation, name in [
            ("AVG", "mean"),
            ("STDDEV_POP", "std"),
            ("MIN", "min"),
            ("MAX", "max"),
            ("COUNT", "count"),
        ]
    )
    return f"""WITH versions AS (
      SELECT v.*,r.FETCHED_AT FROM GRIDCAST_PILOT.{schema}.OBSERVATION_VERSION v
      JOIN GRIDCAST_PILOT.{schema}.OBSERVATION_RECEIPT r USING(VERSION_ID)
      WHERE VALID AND AUTHORITY='PJM' AND METRIC='D' AND UNIT='megawatthours'
       AND r.FETCHED_AT<=TO_TIMESTAMP_TZ('{receipt_cutoff}')
      QUALIFY ROW_NUMBER() OVER(PARTITION BY AUTHORITY,METRIC,OBSERVATION_TIME
        ORDER BY FETCHED_AT DESC,DELIVERY_ORDER DESC)=1),
    eligible AS (SELECT *,{available} AVAILABLE_AT FROM versions
      WHERE {available}<=TO_TIMESTAMP_TZ('{origin}') AND OBSERVATION_TIME<=TO_TIMESTAMP_TZ('{origin}')),
    anchor AS (SELECT MAX(OBSERVATION_TIME) anchor FROM eligible),
    stats AS (SELECT a.anchor,{aggregates} FROM anchor a LEFT JOIN eligible e
      ON e.OBSERVATION_TIME>DATEADD(hour,-168,a.anchor) AND e.OBSERVATION_TIME<=a.anchor GROUP BY a.anchor),
    horizons AS (SELECT SEQ4()+1 horizon FROM TABLE(GENERATOR(ROWCOUNT=>24))),
    targets AS (SELECT horizon,DATEADD(hour,horizon,TO_TIMESTAMP_TZ('{origin}')) target FROM horizons),
    calendar AS (SELECT *,CONVERT_TIMEZONE('America/New_York',target) local_target FROM targets)
    SELECT t.horizon,DATE_PART(hour,t.local_target) local_hour,DAYOFWEEKISO(t.local_target)-1 weekday,
      DATE_PART(month,t.local_target) month,IFF(DAYOFWEEKISO(t.local_target)>=6,1,0) weekend,
      (DATE_PART(timezone_hour,t.local_target)*60+DATE_PART(timezone_minute,t.local_target))/60.0 utc_offset_hours,
      IFF(DATE_PART(month,t.local_target)=11 AND DATE_PART(day,t.local_target)<=7
          AND DAYOFWEEKISO(t.local_target)=7 AND DATE_PART(hour,t.local_target)=1
          AND DATE_PART(timezone_hour,t.local_target)=-5,1,0) dst_fold,
      SIN(2*PI()*DATE_PART(hour,t.local_target)/24) hour_sin,
      COS(2*PI()*DATE_PART(hour,t.local_target)/24) hour_cos,
      SIN(2*PI()*(DAYOFWEEKISO(t.local_target)-1)/7) weekday_sin,
      COS(2*PI()*(DAYOFWEEKISO(t.local_target)-1)/7) weekday_cos,
      l168.VALUE target_lag_168,l336.VALUE target_lag_336,a.VALUE latest_available_demand,
      DATEDIFF(second,s.anchor,TO_TIMESTAMP_TZ('{origin}'))/3600.0 latest_age_hours,
      s.mean_24,s.std_24,s.min_24,s.max_24,s.count_24,
      s.mean_168,s.std_168,s.min_168,s.max_168,s.count_168,a.VALUE-c.VALUE change_24
    FROM calendar t CROSS JOIN stats s LEFT JOIN eligible a ON a.OBSERVATION_TIME=s.anchor
    LEFT JOIN eligible c ON c.OBSERVATION_TIME=DATEADD(hour,-24,s.anchor)
    LEFT JOIN eligible l168 ON l168.OBSERVATION_TIME=DATEADD(hour,-168,t.target)
    LEFT JOIN eligible l336 ON l336.OBSERVATION_TIME=DATEADD(hour,-336,t.target)
    ORDER BY horizon"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path, required=True)
    parser.add_argument(
        "--snapshot-cutoff",
        required=True,
        help="last local successful fetch UTC from export receipts",
    )
    parser.add_argument("--mode", choices=["retrospective", "prospective"], default="retrospective")
    parser.add_argument("--fixture", action="store_true", help="separate synthetic revision schema")
    args = parser.parse_args()
    local = pd.read_csv(
        args.export_dir
        / ("local_fixture_parity.csv" if args.fixture else "local_feature_parity.csv")
    )
    if args.fixture and args.mode != "prospective":
        raise ValueError("synthetic revision parity requires prospective mode")
    from user_session import user_session

    session = user_session()
    try:
        results = []
        for origin in local.origin.unique():
            frame = session.sql(
                feature_sql(origin, args.mode, args.snapshot_cutoff, args.fixture)
            ).to_pandas()
            frame.columns = frame.columns.str.lower()
            frame["origin"] = origin
            results.append(frame)
        features = pd.concat(results, ignore_index=True)
        suffix = "fixture_features" if args.fixture else "features"
        features[["origin", *FEATURES]].to_csv(
            args.export_dir / f"warehouse_{suffix}.csv", index=False
        )
        session.create_dataframe(features[["origin", *FEATURES]]).write.mode(
            "overwrite"
        ).save_as_table(
            "GRIDCAST_PILOT.FEATURES." + ("FIXTURE_PARITY" if args.fixture else "PARITY_FEATURES")
        )
    finally:
        session.sql("ALTER WAREHOUSE GRIDCAST_WH SUSPEND").collect()
        session.close()


if __name__ == "__main__":
    main()
