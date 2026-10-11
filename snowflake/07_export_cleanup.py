"""USER-RUN ONLY: small portable evidence export and compute suspension."""

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export-dir", type=Path, required=True)
    args = parser.parse_args()
    from user_session import user_session

    session = user_session()
    try:
        queries = {
            "warehouse_errors.csv": "SELECT * FROM GRIDCAST_PILOT.ANALYTICS.LATEST_ERROR ORDER BY ORIGIN,HORIZON LIMIT 1000",
            "warehouse_forecasts.csv": "SELECT * FROM GRIDCAST_PILOT.ANALYTICS.FORECAST ORDER BY ORIGIN,HORIZON LIMIT 1000",
            "warehouse_horizon_metrics.csv": "SELECT HORIZON,COUNT(*) PAIRED_TARGETS,AVG(ABSOLUTE_ERROR) MAE,100*SUM(ABSOLUTE_ERROR)/NULLIF(SUM(ABS(ACTUAL)),0) WAPE FROM GRIDCAST_PILOT.ANALYTICS.LATEST_ERROR GROUP BY HORIZON ORDER BY HORIZON",
        }
        for name, query in queries.items():
            session.sql(query).to_pandas().to_csv(args.export_dir / name, index=False)
    finally:
        session.sql("ALTER WAREHOUSE GRIDCAST_WH SUSPEND").collect()
        session.close()


if __name__ == "__main__":
    main()
