"""The executable build/daily dependency graphs, with durable stage receipts."""

import time

import pandas as pd

from .analysis import analyze
from .evaluation import evaluate_outcomes
from .fixtures import generate_fixture
from .forecasting import forecast
from .releases import create_release
from .snapshots import export_demo, published_directory, validate_demo
from .source import ingest, inspect_source
from .storage import validate_source
from .training import backtest, build_dataset, evaluate_test, seal_selection, splits
from .util import now, uid, write_json


def stage(workspace, name, operation):
    receipt_id, started = uid(), time.perf_counter()
    receipt = {"stage": name, "started_at": now(), "receipt_id": receipt_id}
    try:
        result = operation()
        receipt.update(
            {
                "status": "PASS",
                "duration_seconds": time.perf_counter() - started,
                "finished_at": now(),
                "result": result,
            }
        )
        write_json(workspace.path(f"state/stages/{receipt_id}.json"), receipt, immutable=True)
        print(f"{name}: PASS ({receipt['duration_seconds']:.2f}s)", flush=True)
        return result
    except Exception as error:
        receipt.update(
            {
                "status": "FAILED",
                "duration_seconds": time.perf_counter() - started,
                "finished_at": now(),
                "error_type": type(error).__name__,
            }
        )
        write_json(workspace.path(f"state/stages/{receipt_id}.json"), receipt, immutable=True)
        raise


def run(workspace, mode, fixture=False, offline=False, compact=False, origin=None):
    if mode == "build":
        if not workspace.path("state/source_contract.json").exists():
            if fixture:
                stage(workspace, "generate-fixture", lambda: generate_fixture(workspace))
            else:
                stage(workspace, "inspect-source", lambda: inspect_source(workspace))
        if not fixture:
            stage(workspace, "ingest", lambda: ingest(workspace, offline=offline))
        stage(workspace, "validate-source", lambda: validate_source(workspace))
        if not workspace.path("state/selection_seal.json").exists():
            stage(workspace, "build-features", lambda: build_dataset(workspace))
            stage(workspace, "backtest", lambda: backtest(workspace, compact))
        stage(workspace, "seal-selection", lambda: seal_selection(workspace))
        stage(workspace, "evaluate-test", lambda: evaluate_test(workspace))
        stage(workspace, "release", lambda: create_release(workspace))
        _, boundaries, end = splits(workspace)
        for selected in pd.date_range(
            boundaries[-1],
            min(boundaries[-1] + pd.Timedelta(days=7), end),
            inclusive="left",
            freq="D",
        ):
            stage(workspace, "forecast", lambda selected=selected: forecast(workspace, selected))
    elif mode == "daily":
        if origin is None:
            origin = pd.Timestamp.now(tz="UTC").normalize()
        if workspace.settings.availability_mode == "prospective" and not offline:
            cutoff = pd.Timestamp(origin)
            stage(
                workspace,
                "ingest",
                lambda: ingest(
                    workspace,
                    start=cutoff - pd.Timedelta(days=workspace.settings.refresh_overlap_days),
                    end=cutoff,
                    refresh=True,
                ),
            )
        stage(workspace, "forecast", lambda: forecast(workspace, origin))
    else:
        raise ValueError("invalid workflow mode")
    stage(workspace, "evaluate-outcomes", lambda: evaluate_outcomes(workspace))
    stage(workspace, "analyze", lambda: analyze(workspace))
    stage(workspace, "export-demo", lambda: export_demo(workspace))
    return stage(
        workspace,
        "validate-demo",
        lambda: validate_demo(published_directory(workspace.root / "demo")),
    )
