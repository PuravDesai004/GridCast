"""Executed, isolated synthetic fault injections with before/after evidence."""

import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from .config import Settings, Workspace, utc
from .evaluation import evaluate_outcomes
from .features import FEATURES, SCHEMA, baseline, build_features
from .forecasting import forecast
from .releases import promote, rollback
from .snapshots import export_demo
from .source import EIAClient, SourceError
from .storage import connect, publish_window, source_view
from .util import digest, file_hash, now, write_json


class FakeResponse:
    def __init__(self, payload=None, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params, timeout):
        self.calls.append(
            {"params": {k: v for k, v in params.items() if k != "api_key"}, "timeout": timeout}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def api_row(time="2025-09-01T00", value="100"):
    return {
        "period": time,
        "respondent": "PJM",
        "type": "D",
        "value": value,
        "value-units": "megawatthours",
    }


def payload(rows, total=None):
    return {
        "response": {
            "frequency": "hourly",
            "data": rows,
            "total": str(len(rows) if total is None else total),
        }
    }


def toy_source():
    times = pd.date_range("2025-09-01", "2025-10-04", freq="h", inclusive="left", tz="UTC")
    frame = pd.DataFrame(
        {
            "observation_time": times,
            "value": 80000 + 10000 * np.sin(times.hour * 2 * np.pi / 24),
            "authority": "PJM",
            "metric": "D",
            "unit": "megawatthours",
            "valid": True,
            "fetched_at": utc("2025-09-30T20:00:00Z"),
            "fetch_id": "fixture",
        }
    )
    frame["version_id"] = [
        digest({"time": str(t), "value": float(v)})
        for t, v in zip(frame.observation_time, frame.value, strict=True)
    ]
    return frame


def toy_release(workspace, kind="candidate", release_id="synthetic_candidate"):
    directory = workspace.path(f"releases/bundles/{release_id}/manifest.json").parent
    (directory / "model_card.md").write_text(
        "SYNTHETIC engineering scenario, not model performance evidence.", encoding="utf-8"
    )
    if kind == "candidate":
        batch = build_features(
            toy_source(), "2025-10-01T00:00:00Z", workspace.settings, lineage=False
        )
        model = HistGradientBoostingRegressor(max_iter=5, early_stopping=False, random_state=42)
        with threadpool_limits(limits=2):
            model.fit(
                pd.concat([batch.frame] * 3, ignore_index=True), np.tile(baseline(batch.frame), 3)
            )
        joblib.dump(model, directory / "candidate.joblib")
    manifest = {
        "release_id": release_id,
        "features": FEATURES,
        "dtypes": SCHEMA,
        "champion": kind,
        "policy": "nonnegative_clip_v1",
        "baseline_policy": "week_lag_v1",
        "kind": "SYNTHETIC",
        "registry_version": None,
        "source_snapshot": "synthetic",
        "checksums": {p.name: file_hash(p) for p in directory.iterdir() if p.is_file()},
    }
    write_json(directory / "manifest.json", manifest)
    promote(workspace, release_id)
    return directory


def count(workspace, table="forecast"):
    with connect(workspace) as connection:
        return connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def check_leakage(source, settings, origin="2025-10-01T00:00:00Z"):
    origin = utc(origin)
    original = build_features(source, origin, settings, lineage=False)
    changed = source.copy()
    if settings.availability_mode == "retrospective":
        unavailable = (
            changed.observation_time + pd.Timedelta(hours=settings.assumed_delay_hours) > origin
        )
    else:
        unavailable = (pd.to_datetime(changed.fetched_at, utc=True) > origin) | (
            changed.observation_time > origin
        )
    changed.loc[unavailable, "value"] = 987654321.0
    changed.loc[unavailable, "version_id"] = "mutated_unavailable"
    unavailable_rows = changed[unavailable]
    # Delete half, append a future observation, and reorder every remaining row.
    changed = changed.drop(unavailable_rows.iloc[::2].index)
    appended = source.iloc[[-1]].copy()
    appended["observation_time"], appended["fetched_at"] = (
        origin + pd.Timedelta(days=30),
        origin + pd.Timedelta(days=30),
    )
    appended["value"], appended["version_id"] = 123456789.0, "future_append"
    changed = pd.concat([changed, appended], ignore_index=True).sample(frac=1, random_state=43)
    after = build_features(changed, origin, settings, lineage=False)
    assert original.feature_hash == after.feature_hash
    assert original.eligible_hash == after.eligible_hash
    assert original.snapshot_id == after.snapshot_id
    assert np.array_equal(baseline(original.frame), baseline(after.frame))
    model = HistGradientBoostingRegressor(max_iter=5, early_stopping=False, random_state=42)
    with threadpool_limits(limits=2):
        model.fit(pd.concat([original.frame] * 3), np.tile(baseline(original.frame), 3))
        before_predictions = model.predict(original.frame)
        after_predictions = model.predict(after.frame)
    assert np.array_equal(before_predictions, after_predictions)
    return {
        "origin": str(origin),
        "mode": settings.availability_mode,
        "status": "PASS",
        "mutated_unavailable_rows": int(unavailable.sum()),
        "delayed_pre_cutoff_rows": int((unavailable & (source.observation_time <= origin)).sum()),
        "features_checksum": original.feature_hash,
        "eligible_checksum": original.eligible_hash,
        "candidate_prediction_checksum": digest(before_predictions.tolist()),
        "full_source_content_changed": True,
        "model": "synthetic engineering test estimator",
    }


def verify_scenarios(workspace):
    records = []

    def record(name, expected, actual, before=None, after=None, identities=None):
        assert actual == expected, f"scenario {name}: expected {expected}; observed {actual}"
        records.append(
            {
                "scenario": name,
                "expected": expected,
                "actual": actual,
                "status": "PASS",
                "before": before,
                "after": after,
                "affected_identities": identities,
                "command": "python -m gridcast verify-scenarios",
                "synthetic_fault_injection": True,
            }
        )

    sleeps = []
    session = FakeSession(
        [FakeResponse(status=429, headers={"Retry-After": "2"}), FakeResponse(payload([]))]
    )
    EIAClient("synthetic_key", session, sleeps.append).request()
    record("HTTP_429_retry", [2.0, 2], [sleeps[0], len(session.calls)])
    session = FakeSession([FakeResponse(status=429)] * 4)
    try:
        EIAClient("synthetic_key", session, lambda _: None).request()
        raise AssertionError("retry exhaustion accepted")
    except SourceError:
        record("HTTP_429_bounded_exhaustion", 4, len(session.calls))
    session = FakeSession([FakeResponse(payload([api_row()], total=2))])
    try:
        EIAClient("synthetic_key", session, lambda _: None).window(
            "2025-09-01T00:00:00Z", "2025-09-01T02:00:00Z"
        )
        raise AssertionError("partial page accepted")
    except SourceError:
        record("partial_API_window", "REJECTED_WITHOUT_PUBLICATION", "REJECTED_WITHOUT_PUBLICATION")
    with tempfile.TemporaryDirectory(
        dir=workspace.path("state/scenarios/placeholder").parent
    ) as temporary:
        isolated = Workspace(Path(temporary), Settings())
        source = toy_source()
        toy_release(isolated)
        first = forecast(isolated, "2025-10-01T00:00:00Z", source=source)
        before = count(isolated)
        second = forecast(isolated, "2025-10-01T00:00:00Z", source=source)
        record(
            "identical_forecast_replay",
            [0, 24, first["output_hash"]],
            [second["inserted_rows"], count(isolated), second["output_hash"]],
            before=before,
            after=count(isolated),
            identities=[first["logical_id"]],
        )
        changed = source.copy()
        changed.loc[
            changed.observation_time == utc("2025-09-30T21:00:00Z"), ["value", "version_id"]
        ] = [91000.0, "changed_revision"]
        revised = forecast(isolated, "2025-10-01T00:00:00Z", source=changed)
        record(
            "changed_source_revision",
            [True, 24, 48],
            [
                revised["logical_id"] != first["logical_id"],
                revised["inserted_rows"],
                count(isolated),
            ],
            before=before,
            after=count(isolated),
            identities=[first["logical_id"], revised["logical_id"]],
        )
        before = count(isolated)
        try:
            forecast(isolated, "2025-10-02T00:00:00Z", source=source, fail_after=12)
            raise AssertionError("transaction fault did not fire")
        except RuntimeError:
            record(
                "interrupted_forecast_transaction",
                before,
                count(isolated),
                before=before,
                after=count(isolated),
            )
        with connect(isolated) as connection:
            failed = connection.execute(
                "SELECT count(*) FROM forecast_attempt WHERE status='FAILED'"
            ).fetchone()[0]
        record("failed_attempt_after_rollback", 1, failed)
        stale = source[source.observation_time < utc("2025-09-30T10:00:00Z")]
        result = forecast(isolated, "2025-10-01T00:00:00Z", source=stale)
        record(
            "stale_anchor",
            "seasonal_fallback",
            result["serving_path"],
            identities=[result["logical_id"]],
        )
        missing_one = source[source.observation_time != utc("2025-09-24T01:00:00Z")]
        result = forecast(isolated, "2025-10-01T00:00:00Z", source=missing_one)
        record("missing_single_lag_tolerated", "candidate", result["serving_path"])
        missing = stale[stale.observation_time != utc("2025-09-24T01:00:00Z")]
        before = count(isolated)
        result = forecast(isolated, "2025-10-01T00:00:00Z", source=missing)
        record(
            "missing_lag_unavailable",
            ["UNAVAILABLE", 0, before],
            [result["status"], result["inserted_rows"], count(isolated)],
            before=before,
            after=count(isolated),
        )
        directory = isolated.root / "releases/bundles/synthetic_candidate"
        (directory / "candidate.joblib").write_bytes(b"corrupted")
        result = forecast(isolated, "2025-10-03T00:00:00Z", source=source)
        record("corrupted_model_bundle", "seasonal_fallback", result["serving_path"])
        toy_release(isolated, "baseline", "synthetic_baseline")
        pointer_hash = file_hash(isolated.root / "releases/current.json")
        try:
            promote(isolated, "synthetic_candidate")
            raise AssertionError("corrupt promotion accepted")
        except ValueError:
            record(
                "failed_promotion_preserves_pointer",
                pointer_hash,
                file_hash(isolated.root / "releases/current.json"),
                before=pointer_hash,
                after=pointer_hash,
            )
        toy_release(isolated, "baseline", "synthetic_baseline_2")
        result = rollback(isolated, "synthetic_baseline")
        record("release_pointer_rollback", "synthetic_baseline", result["release_id"])
        # Receipt chronology including repeated content and reverted values.
        revision_workspace = Workspace(
            Path(temporary) / "versions", Settings(availability_mode="prospective")
        )
        single_time = "2025-09-01T00"
        times = [
            "2025-09-02T00:00:00Z",
            "2025-09-03T00:00:00Z",
            "2025-09-04T00:00:00Z",
            "2025-09-05T00:00:00Z",
        ]
        for value, fetched in zip(["100", "100", "200", "100"], times, strict=True):
            publish_window(
                revision_workspace,
                [(0, payload([api_row(single_time, value)]))],
                "2025-09-01T00:00:00Z",
                "2025-09-01T01:00:00Z",
                "megawatthours",
                fetched_at=fetched,
                kind="SYNTHETIC",
            )
        record(
            "revision_A_B_A",
            [2, 4, 100.0, 200.0],
            [
                count(revision_workspace, "observation_version"),
                count(revision_workspace, "source_fetch"),
                float(source_view(revision_workspace).value.iloc[0]),
                float(source_view(revision_workspace, "2025-09-04T12:00:00Z").value.iloc[0]),
            ],
        )
        before = count(revision_workspace, "observation_version")
        try:
            publish_window(
                revision_workspace,
                [(0, payload([api_row(single_time, "100"), api_row(single_time, "999")]))],
                "2025-09-01T00:00:00Z",
                "2025-09-01T01:00:00Z",
                "megawatthours",
                kind="SYNTHETIC",
            )
            raise AssertionError("same key conflict accepted")
        except ValueError:
            record(
                "same_key_source_conflict",
                before,
                count(revision_workspace, "observation_version"),
                before=before,
                after=count(revision_workspace, "observation_version"),
            )
        # Actual revisions preserve previous error vintages and forecast values.
        outcome_workspace = Workspace(
            Path(temporary) / "outcomes", Settings(availability_mode="prospective")
        )
        toy_release(outcome_workspace, "baseline", "outcome_baseline")
        forecast_receipt = forecast(outcome_workspace, "2025-10-01T00:00:00Z", source=source)
        prediction_hash = forecast_receipt["output_hash"]
        for value, fetched in [("100", "2025-10-03T00:00:00Z"), ("200", "2025-10-04T00:00:00Z")]:
            publish_window(
                outcome_workspace,
                [(0, payload([api_row("2025-10-01T01", value)]))],
                "2025-10-01T01:00:00Z",
                "2025-10-01T02:00:00Z",
                "megawatthours",
                fetched_at=fetched,
                kind="SYNTHETIC",
            )
            evaluate_outcomes(outcome_workspace, fetched)
        with connect(outcome_workspace) as connection:
            unchanged = connection.execute("SELECT output_hash FROM forecast_batch").fetchone()[0]
        record(
            "revised_actual_error_vintages",
            [2, prediction_hash],
            [count(outcome_workspace, "forecast_error"), unchanged],
        )
        # Export fault operates on a copy of actual completed local pipeline artifacts.
        if (workspace.root / "data/test_predictions.parquet").exists():
            for relative in [
                "data/test_predictions.parquet",
                "state/evaluation_by_horizon.csv",
                "state/peak_error.csv",
                "state/analysis.json",
                "state/source_validation.json",
                "state/selection.json",
                "state/test_result.json",
                "state/final_fit.json",
            ]:
                isolated.path(relative).write_bytes((workspace.root / relative).read_bytes())
            export_demo(isolated)
            before = file_hash(isolated.root / "demo/published/current.json")
            db_before = count(isolated)
            try:
                export_demo(isolated, fail=True)
                raise AssertionError("export fault accepted")
            except RuntimeError:
                record(
                    "snapshot_export_failure",
                    [before, db_before],
                    [file_hash(isolated.root / "demo/published/current.json"), count(isolated)],
                    before=before,
                    after=before,
                )
            export_demo(isolated)
            record("export_retry_without_forecast_duplication", db_before, count(isolated))
        else:
            records.append(
                {
                    "scenario": "snapshot_export_failure",
                    "status": "PENDING",
                    "reason": "run build/export before verifying all scenarios",
                }
            )
    retrospective = check_leakage(toy_source(), Settings())
    prospective_source = toy_source()
    prospective_source.loc[
        prospective_source.observation_time >= utc("2025-09-30T22:00:00Z"), "fetched_at"
    ] = utc("2025-10-02T00:00:00Z")
    prospective = check_leakage(prospective_source, Settings(availability_mode="prospective"))
    write_json(
        workspace.path("docs/evidence/leakage.json"),
        {"kind": "SYNTHETIC_ENGINEERING", "checks": [retrospective, prospective]},
    )
    result = {
        "at": now(),
        "kind": "SYNTHETIC_ENGINEERING",
        "records": records,
        "passed": sum(r["status"] == "PASS" for r in records),
        "pending": sum(r["status"] != "PASS" for r in records),
    }
    write_json(workspace.path("docs/evidence/recovery.json"), result)
    return result
