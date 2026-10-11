import socket

import numpy as np
import pandas as pd
import pytest
import requests
from pydantic import ValidationError

from gridcast.config import ROOT, Settings, Workspace, utc
from gridcast.evaluation import choose_champion, comparison, metrics
from gridcast.features import FEATURES, build_features
from gridcast.forecasting import forecast
from gridcast.scenarios import (
    FakeResponse,
    FakeSession,
    api_row,
    check_leakage,
    count,
    payload,
    toy_release,
    toy_source,
)
from gridcast.snapshots import load_demo, validate_demo
from gridcast.source import EIAClient, SourceError
from gridcast.storage import normalize, publish_window, source_view
from gridcast.training import attach_labels, fit_rows, model_for, verify_seal
from gridcast.util import canonical, contained, file_hash, read_json, redact


@pytest.mark.parametrize(
    "parameters",
    [
        {"page_size": 5001},
        {"threads": 3},
        {"warmup_days": 13},
        {"availability_mode": "invented"},
        {"authority": "CISO"},
        {"core_start": "2024-01-01"},
        {"extra_setting": True},
    ],
)
def test_config_rejects_invalid_before_work(parameters):
    with pytest.raises((ValueError, ValidationError)):
        Settings(**parameters)


def test_sanitizer_removes_nested_echo_and_secret_strings():
    key = "private_test_secret"
    result = redact(
        {
            "request": {"params": {"api_key": key}},
            "nested": [{"api_key": key}],
            "description": f"https://host/?api_key={key}&frequency=hourly",
            "data": key,
        },
        key,
    )
    assert key not in canonical(result).decode()
    assert "request" not in result
    assert result["nested"] == [{}]


def test_pagination_inclusive_bounds_and_sort():
    session = FakeSession(
        [
            FakeResponse(payload([api_row()], total=2)),
            FakeResponse(payload([api_row("2025-09-01T01")], total=2)),
        ]
    )
    pages = EIAClient("private_test_secret", session).window(
        "2025-09-01T00:00:00Z", "2025-09-01T02:00:00Z", page_size=1
    )
    assert len(pages) == 2
    assert [c["params"]["offset"] for c in session.calls] == [0, 1]
    assert session.calls[0]["params"]["end"] == "2025-09-01T01"
    assert session.calls[0]["timeout"] == (10, 45)
    assert session.calls[0]["params"]["sort[0][direction]"] == "asc"


@pytest.mark.parametrize(
    "responses",
    [
        [FakeResponse(payload([], total=2))],
        [
            FakeResponse(payload([api_row()], total=2)),
            FakeResponse(payload([api_row("2025-09-01T01")], total=1)),
        ],
        [FakeResponse(payload([{**api_row(), "respondent": "CISO"}]))],
        [FakeResponse(payload([api_row("2025-09-02T00")]))],
        [FakeResponse(payload([api_row()], total=2)), FakeResponse(payload([api_row()], total=2))],
        [
            FakeResponse(payload([api_row()], total=2)),
            FakeResponse(payload([api_row(value="999")], total=2)),
        ],
    ],
)
def test_contract_failures_discard_window(responses):
    with pytest.raises(SourceError):
        EIAClient("private_test_secret", FakeSession(responses), lambda _: None).window(
            "2025-09-01T00:00:00Z", "2025-09-01T02:00:00Z", page_size=1
        )


def test_timeout_retry_bounded_and_auth_prompt():
    session = FakeSession([requests.Timeout("secret must not escape")] * 4)
    with pytest.raises(SourceError) as error:
        EIAClient("private_test_secret", session, lambda _: None).request()
    assert "secret" not in str(error.value) and len(session.calls) == 4
    session = FakeSession([FakeResponse(status=403)])
    with pytest.raises(SourceError):
        EIAClient("private_test_secret", session, lambda _: None).request()
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "value,valid,quality",
    [
        ("NaN", False, "invalid"),
        ("inf", False, "invalid"),
        ("-1", False, "invalid"),
        (None, False, "invalid"),
        ("0", True, "zero"),
        ("999999", True, "extreme_positive"),
    ],
)
def test_typed_demand_no_silent_filling(value, valid, quality):
    normalized = normalize(api_row(value=value), "megawatthours")
    assert normalized["valid"] is valid and normalized["quality"] == quality
    assert normalized["raw"] == str(value)


def test_unit_mismatch_rejected():
    with pytest.raises(ValueError):
        normalize({**api_row(), "value-units": "megawatts"}, "megawatthours")


def test_receipt_delivery_reversion_and_conflict(tmp_path):
    workspace = Workspace(tmp_path)
    for value, fetched in [
        ("100", "2025-09-02T00:00:00Z"),
        ("100", "2025-09-03T00:00:00Z"),
        ("200", "2025-09-04T00:00:00Z"),
        ("100", "2025-09-05T00:00:00Z"),
    ]:
        publish_window(
            workspace,
            [(0, payload([api_row(value=value)]))],
            "2025-09-01T00:00:00Z",
            "2025-09-01T01:00:00Z",
            "megawatthours",
            fetched_at=fetched,
            kind="SYNTHETIC",
        )
    assert count(workspace, "observation_version") == 2
    assert count(workspace, "observation_receipt") == 4
    assert source_view(workspace).value.iloc[0] == 100
    assert source_view(workspace, "2025-09-04T12:00:00Z").value.iloc[0] == 200
    assert source_view(workspace, "2025-09-01T12:00:00Z").empty
    with pytest.raises(ValueError):
        publish_window(
            workspace,
            [(0, payload([api_row(value="100"), api_row(value="200")]))],
            "2025-09-01T00:00:00Z",
            "2025-09-01T01:00:00Z",
            "megawatthours",
            kind="SYNTHETIC",
        )
    assert count(workspace, "source_fetch") == 4


def test_gappy_lags_use_clock_timestamps_and_population_std():
    source = toy_source()
    origin = utc("2025-10-01T00:00:00Z")
    gap = origin - pd.Timedelta(hours=168) + pd.Timedelta(hours=1)
    source = source[source.observation_time != gap]
    batch = build_features(source, origin, Settings(), lineage=False)
    assert np.isnan(batch.frame.target_lag_168.iloc[0])
    expected = source.set_index("observation_time").loc[
        origin - pd.Timedelta(hours=168) + pd.Timedelta(hours=2), "value"
    ]
    assert batch.frame.target_lag_168.iloc[1] == expected
    anchor = origin - pd.Timedelta(hours=3)
    values = source[
        (source.observation_time > anchor - pd.Timedelta(hours=24))
        & (source.observation_time <= anchor)
    ].value
    assert batch.frame["std_24"].iloc[0] == pytest.approx(np.std(values, ddof=0))
    assert batch.frame.latest_age_hours.iloc[0] == 3
    assert not any(name in FEATURES for name in ["target_lag_1", "target_lag_24", "actual"])


@pytest.mark.parametrize("day", ["2025-03-09", "2025-11-02"])
def test_dst_unique_utc_and_fold(day):
    source = toy_source()
    source.observation_time = source.observation_time + (
        utc(day + "T00:00:00Z") - utc("2025-10-01T00:00:00Z")
    )
    batch = build_features(source, day + "T00:00:00Z", Settings(), lineage=False)
    if day.endswith("03-09"):
        assert batch.frame.local_hour.iloc[5:7].tolist() == [1, 3]
    else:
        assert batch.frame.local_hour.iloc[4:6].tolist() == [1, 1]
        assert batch.frame.dst_fold.iloc[4:6].tolist() == [0, 1]
        assert batch.frame.utc_offset_hours.iloc[4:6].tolist() == [-4, -5]


@pytest.mark.parametrize("mode", ["retrospective", "prospective"])
def test_unavailable_values_mutate_append_delete_reorder_and_revision(mode):
    source = toy_source()
    if mode == "prospective":
        source.loc[source.observation_time >= utc("2025-09-30T22:00:00Z"), "fetched_at"] = utc(
            "2025-10-02T00:00:00Z"
        )
    result = check_leakage(source, Settings(availability_mode=mode))
    assert result["status"] == "PASS" and result["mutated_unavailable_rows"] > 0
    assert result["delayed_pre_cutoff_rows"] > 0


def test_prospective_revision_first_collected_after_cutoff_excluded():
    source = toy_source()
    revision = source[source.observation_time == utc("2025-09-30T21:00:00Z")].copy()
    revision["value"], revision["version_id"], revision["fetched_at"] = (
        9876543.0,
        "after_cutoff_revision",
        utc("2025-10-02T00:00:00Z"),
    )
    settings = Settings(availability_mode="prospective")
    before = build_features(source, "2025-10-01T00:00:00Z", settings, lineage=False)
    after = build_features(
        pd.concat([source, revision]), "2025-10-01T00:00:00Z", settings, lineage=False
    )
    assert before.feature_hash == after.feature_hash and before.snapshot_id == after.snapshot_id


def test_lineage_can_represent_multiple_features_and_horizons():
    batch = build_features(toy_source(), "2025-10-01T00:00:00Z", Settings())
    lineage = pd.DataFrame(batch.lineage)
    assert not lineage.duplicated(["horizon", "feature", "version_id"]).any()
    assert lineage.available_at.max() <= batch.origin
    assert lineage.groupby("version_id").feature.nunique().max() > 1
    assert lineage.groupby("version_id").horizon.nunique().max() == 24
    expanded = sum(len(item["horizons"]) * len(item["inputs"]) for item in batch.compact_lineage)
    assert expanded == len(lineage)


def test_fit_label_boundary_and_validation_whole_origin_purge():
    source = toy_source()
    frames = []
    for origin in pd.date_range("2025-09-20", "2025-10-01", freq="D", inclusive="left", tz="UTC"):
        frame = build_features(source, origin, Settings(), lineage=False).frame
        frame["origin"] = origin
        frame["target"] = origin + pd.to_timedelta(frame.horizon, unit="h")
        frame["candidate_eligible"] = True
        frames.append(frame)
    features = pd.concat(frames)
    cutoff = utc("2025-10-01T00:00:00Z")
    train, receipt = fit_rows(features, source, utc("2025-09-20T00:00:00Z"), cutoff, Settings())
    assert (train.target + pd.Timedelta(hours=3) <= cutoff).all()
    assert receipt["purged_label_rows"] == 3
    validation = attach_labels(features, source, cutoff, 3)
    complete = validation.groupby("origin").actual.count()
    assert complete.loc[utc("2025-09-30T00:00:00Z")] == 21
    assert model_for(Settings(), {"max_leaf_nodes": 15}).early_stopping is False


def test_paired_metrics_and_zero_denominator_selection():
    result = metrics([100, 200], [110, 180], 150)
    assert result["mae"] == 15 and result["wape"] == 10 and result["signed_bias"] == -5
    assert result["peak_count"] == 1 and result["peak_mae"] == 20
    assert metrics([0, 0], [1, 2])["wape"] is None
    paired = pd.DataFrame(
        {
            "actual": [100.0, 200.0],
            "baseline": [110.0, 180.0],
            "candidate": [100.0, 190.0],
            "peak_threshold": [150.0, 150.0],
        }
    )
    comparisons = comparison(paired)
    assert choose_champion(comparisons, 1, Settings())["champion"] == "candidate"
    assert choose_champion(comparisons, 0.89, Settings())["champion"] == "baseline"
    zero = {"baseline": metrics([0], [0]), "candidate": metrics([0], [0])}
    assert choose_champion(zero, 1, Settings())["champion"] == "baseline"


def test_replay_rollback_missing_and_corruption(tmp_path):
    workspace = Workspace(tmp_path)
    directory = toy_release(workspace)
    source = toy_source()
    first = forecast(workspace, "2025-10-01T00:00:00Z", source=source)
    replay = forecast(workspace, "2025-10-01T00:00:00Z", source=source)
    assert replay["inserted_rows"] == 0 and replay["output_hash"] == first["output_hash"]
    assert count(workspace) == 24
    before_features = count(workspace, "feature_snapshot")
    with pytest.raises(RuntimeError):
        forecast(workspace, "2025-10-02T00:00:00Z", source=source, fail_after=12)
    assert count(workspace) == 24 and count(workspace, "feature_snapshot") == before_features
    (directory / "candidate.joblib").write_bytes(b"corruption")
    result = forecast(workspace, "2025-10-02T00:00:00Z", source=source)
    assert result["serving_path"] == "seasonal_fallback" and result["inserted_rows"] == 24
    stale = source[source.observation_time < utc("2025-09-30T10:00:00Z")]
    stale = stale[stale.observation_time != utc("2025-09-24T01:00:00Z")]
    result = forecast(workspace, "2025-10-01T00:00:00Z", source=stale)
    assert result["status"] == "UNAVAILABLE" and result["inserted_rows"] == 0


def test_missing_seal_rejects_evaluation(tmp_path):
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_seal(Workspace(tmp_path))


def test_changed_seal_rejects_evaluation(tmp_path):
    if not (ROOT / "state/selection_seal.json").exists():
        pytest.skip("requires a completed sealed real build")
    import shutil

    from gridcast.config import load_settings

    seal = read_json(ROOT / "state/selection_seal.json")
    for relative in seal["files"]:
        if relative.startswith("code/"):
            continue
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    shutil.copyfile(ROOT / "state/selection_seal.json", tmp_path / "state/selection_seal.json")
    workspace = Workspace(tmp_path, load_settings(ROOT / "config/project.yaml"))
    verify_seal(workspace)
    workspace = Workspace(
        tmp_path, workspace.settings.model_copy(update={"assumed_delay_hours": 4})
    )
    with pytest.raises(ValueError, match="changed selection seal"):
        verify_seal(workspace)
    workspace = Workspace(tmp_path, load_settings(ROOT / "config/project.yaml"))
    (tmp_path / "state/candidate.joblib").write_bytes(b"changed artifact")
    with pytest.raises(ValueError, match="changed selection seal"):
        verify_seal(workspace)


@pytest.mark.parametrize("relative", ["../escape.json", "../../secret", "C:/absolute/secret"])
def test_artifact_containment(relative, tmp_path):
    with pytest.raises(ValueError):
        contained(tmp_path, relative)


def test_snapshot_tampering_and_arithmetic(tmp_path):
    if not (ROOT / "demo/published/current.json").exists():
        pytest.skip("requires a completed snapshot generation")
    import shutil

    demo = load_demo(ROOT / "demo")
    shutil.copytree(demo["directory"], tmp_path / "generation")
    directory = tmp_path / "generation"
    frame = pd.read_csv(directory / "evaluation_by_horizon.csv")
    frame.loc[0, "mae"] += 100
    frame.to_csv(directory / "evaluation_by_horizon.csv", index=False)
    with pytest.raises(ValueError):
        validate_demo(directory)
    manifest = read_json(directory / "manifest.json")
    manifest["files"]["evaluation_by_horizon.csv"] = {
        "bytes": (directory / "evaluation_by_horizon.csv").stat().st_size,
        "sha256": file_hash(directory / "evaluation_by_horizon.csv"),
    }
    (directory / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="arithmetic"):
        validate_demo(directory)


@pytest.mark.parametrize("corruption", ["naive_timestamps", "infinite_actual"])
def test_snapshot_typed_values_even_with_matching_checksum(tmp_path, corruption):
    if not (ROOT / "demo/published/current.json").exists():
        pytest.skip("requires a completed snapshot generation")
    import shutil

    demo = load_demo(ROOT / "demo")
    directory = tmp_path / "generation"
    shutil.copytree(demo["directory"], directory)
    path = directory / "forecast_examples.parquet"
    frame = pd.read_parquet(path)
    if corruption == "naive_timestamps":
        frame["origin"] = frame.origin.dt.tz_localize(None)
    else:
        frame.loc[0, "actual"] = np.inf
    frame.to_parquet(path, index=False)
    manifest = read_json(directory / "manifest.json")
    manifest["files"][path.name] = {"sha256": file_hash(path), "bytes": path.stat().st_size}
    (directory / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError):
        validate_demo(directory)


def test_app_renders_all_views_with_network_blocked(monkeypatch):
    if not (ROOT / "demo/published/current.json").exists():
        pytest.skip("requires completed real snapshot generation")
    from streamlit.testing.v1 import AppTest

    monkeypatch.delenv("EIA_API_KEY", raising=False)
    original_connect = socket.socket.connect

    def guarded_connect(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1", "localhost"}:
            return original_connect(sock, address)
        raise AssertionError("external network forbidden")

    monkeypatch.setattr(
        socket.socket,
        "connect",
        guarded_connect,
    )
    monkeypatch.setattr(
        requests.sessions.Session,
        "request",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("HTTP requests forbidden")),
    )
    monkeypatch.setattr(
        joblib_load_module(),
        "load",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("model loading forbidden")),
    )
    app = AppTest.from_file(str(ROOT / "app/streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Forecast Explorer"
    for view in ["Evaluation", "Reliability & Model Lineage"]:
        app.sidebar.radio[0].set_value(view).run()
        assert not app.exception and app.title[0].value == view
    app.sidebar.radio[0].set_value("Evaluation").run()
    app.slider[0].set_value((1, 12)).run()
    assert not app.exception
    paired = [metric.value for metric in app.metric if metric.label == "Paired targets"]
    assert paired == ["1,104", "1,104"]


def joblib_load_module():
    import joblib

    return joblib


def test_manual_parity_comparison_offline(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "manual_compare", ROOT / "snowflake/04_compare.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    local = pd.DataFrame(
        {
            "origin": ["2025-01-01T00:00:00Z"],
            "horizon": [1],
            "dst_fold": [0],
            "std_24": [np.nan],
            "latest_available_demand": [100.0],
        }
    )
    local.to_csv(tmp_path / "local_feature_parity.csv", index=False)
    local.to_csv(tmp_path / "warehouse_features.csv", index=False)
    assert module.compare(tmp_path)["status"] == "PASS"
    changed = local.copy()
    changed["dst_fold"] = 1
    changed.to_csv(tmp_path / "warehouse_features.csv", index=False)
    with pytest.raises(ValueError, match="dst_fold"):
        module.compare(tmp_path)
