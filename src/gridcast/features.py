"""One shared training/inference builder. Target actuals never enter this interface."""

from dataclasses import dataclass
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import utc
from .util import digest

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
SCHEMA = {name: "float64" for name in FEATURES}


def frame_records(frame):
    # Normalize all absent source inputs to JSON null for deterministic checksums.
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


@dataclass
class FeatureBatch:
    frame: pd.DataFrame
    lineage: list
    snapshot_id: str
    feature_hash: str
    eligible_hash: str
    origin: pd.Timestamp
    mode: str
    compact_lineage: list


def build_features(source, origin, settings, lineage=True):
    origin = utc(origin)
    if origin != origin.normalize():
        raise ValueError("forecast origin must be 00:00 UTC")
    source = source.copy()
    if source.empty:
        source = pd.DataFrame(
            columns=["observation_time", "value", "unit", "version_id", "fetched_at"]
        )
    source["observation_time"] = pd.to_datetime(source.observation_time, utc=True)
    if settings.availability_mode == "retrospective":
        source["available_at"] = source.observation_time + pd.Timedelta(
            hours=settings.assumed_delay_hours
        )
    else:
        source["available_at"] = pd.to_datetime(source.fetched_at, utc=True)
    source = source[(source.available_at <= origin) & (source.observation_time <= origin)]
    if "valid" in source:
        source = source[source.valid]
    if not source.empty:
        if source.unit.nunique() != 1 or source.unit.iloc[0] != "megawatthours":
            raise ValueError("feature source unit contract failed")
        source = source.sort_values(
            ["observation_time", "available_at", "fetch_id"]
            if "fetch_id" in source
            else ["observation_time", "available_at"]
        )
        source = source.drop_duplicates("observation_time", keep="last")
    lookup = source.set_index("observation_time")
    anchor = lookup.index.max() if not lookup.empty else None
    common, inputs = {}, {}

    def take(times):
        return lookup.reindex(pd.DatetimeIndex(times))

    if anchor is not None:
        common["latest_available_demand"] = float(lookup.loc[anchor, "value"])
        common["latest_age_hours"] = (origin - anchor).total_seconds() / 3600
        inputs["latest_available_demand"] = take([anchor])
        inputs["latest_age_hours"] = take([anchor])
        for length in (24, 168):
            window = take(pd.date_range(anchor - pd.Timedelta(hours=length - 1), anchor, freq="h"))
            values = window.value.dropna().astype(float)
            for name, result in [
                ("mean", values.mean()),
                ("std", values.std(ddof=0)),
                ("min", values.min()),
                ("max", values.max()),
                ("count", len(values)),
            ]:
                feature = f"{name}_{length}"
                common[feature] = float(result)
                # Coverage includes the membership of every present observation.
                inputs[feature] = window.dropna(subset=["version_id"])
        change = take([anchor, anchor - pd.Timedelta(hours=24)])
        common["change_24"] = float(change.value.iloc[0] - change.value.iloc[1])
        inputs["change_24"] = change.dropna(subset=["version_id"])
    else:
        for name in FEATURES[13:]:
            common[name] = 0.0 if name.startswith("count_") else np.nan
    rows, lineage_rows, eligible, compact = [], [], {}, []
    for feature, observations in inputs.items():
        members = []
        for timestamp, item in observations.iterrows():
            eligible[item.version_id] = {
                "version_id": item.version_id,
                "time": timestamp.isoformat(),
                "available_at": item.available_at.isoformat(),
            }
            members.append(eligible[item.version_id])
        compact.append({"horizons": list(range(1, 25)), "feature": feature, "inputs": members})
    for horizon in range(1, 25):
        target = origin + pd.Timedelta(hours=horizon)
        local = target.to_pydatetime().astimezone(ZoneInfo(settings.calendar_timezone))
        row = {
            "horizon": horizon,
            "local_hour": local.hour,
            "weekday": local.weekday(),
            "month": local.month,
            "weekend": int(local.weekday() >= 5),
            "utc_offset_hours": local.utcoffset().total_seconds() / 3600,
            "dst_fold": local.fold,
            "hour_sin": np.sin(2 * np.pi * local.hour / 24),
            "hour_cos": np.cos(2 * np.pi * local.hour / 24),
            "weekday_sin": np.sin(2 * np.pi * local.weekday() / 7),
            "weekday_cos": np.cos(2 * np.pi * local.weekday() / 7),
            **common,
        }
        horizon_inputs = dict(inputs) if lineage else {}
        for lag in (168, 336):
            lag_row = take([target - pd.Timedelta(hours=lag)])
            row[f"target_lag_{lag}"] = float(lag_row.value.iloc[0])
            horizon_inputs[f"target_lag_{lag}"] = lag_row.dropna(subset=["version_id"])
            compact.append(
                {
                    "horizons": [horizon],
                    "feature": f"target_lag_{lag}",
                    "inputs": [
                        {
                            "version_id": item.version_id,
                            "time": timestamp.isoformat(),
                            "available_at": item.available_at.isoformat(),
                        }
                        for timestamp, item in lag_row.dropna(subset=["version_id"]).iterrows()
                    ],
                }
            )
        rows.append(row)
        for feature, observations in horizon_inputs.items():
            for timestamp, item in observations.iterrows():
                eligible[item.version_id] = {
                    "version_id": item.version_id,
                    "time": timestamp.isoformat(),
                    "available_at": item.available_at.isoformat(),
                }
                if lineage:
                    lineage_rows.append(
                        {
                            "horizon": horizon,
                            "feature": feature,
                            "version_id": item.version_id,
                            "observation_time": timestamp,
                            "available_at": item.available_at,
                        }
                    )
    frame = pd.DataFrame(rows)[FEATURES].astype("float64")
    feature_hash = digest(frame_records(frame))
    eligible_hash = digest(sorted(eligible.values(), key=lambda item: item["version_id"]))
    snapshot_id = digest(
        {
            "origin": origin.isoformat(),
            "mode": settings.availability_mode,
            "delay": settings.assumed_delay_hours,
            "schema": SCHEMA,
            "feature_hash": feature_hash,
            "eligible_hash": eligible_hash,
        }
    )
    return FeatureBatch(
        frame,
        lineage_rows,
        snapshot_id,
        feature_hash,
        eligible_hash,
        origin,
        settings.availability_mode,
        compact,
    )


def gates(frame, settings):
    first = frame.iloc[0]
    failures = []
    if not np.isfinite(first.latest_age_hours) or first.latest_age_hours > settings.anchor_max_age:
        failures.append("STALE_ANCHOR")
    if first.count_24 < settings.recent_min_count:
        failures.append("RECENT_COVERAGE")
    if first.count_168 < settings.weekly_min_count:
        failures.append("WEEKLY_COVERAGE")
    if frame.target_lag_168.notna().sum() < settings.week_lag_min_count:
        failures.append("WEEK_LAG_COVERAGE")
    return failures


def baseline(frame):
    values = frame.target_lag_168.to_numpy(dtype=float)
    if len(values) != 24 or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("UNAVAILABLE: baseline needs all 24 eligible week lags")
    return values


def clip_predictions(values):
    values = np.asarray(values, dtype=float)
    if len(values) != 24 or not np.isfinite(values).all():
        raise ValueError("invalid prediction batch")
    return np.maximum(values, 0), int((values < 0).sum())
