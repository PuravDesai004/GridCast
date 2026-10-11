import argparse
import os
import shutil
import sys
from pathlib import Path

import yaml

from .config import ROOT, Workspace, load_settings, utc
from .util import environment_receipt, redact

COMMANDS = [
    "generate-fixture",
    "inspect-source",
    "ingest",
    "validate-source",
    "build-features",
    "backtest",
    "seal-selection",
    "evaluate-test",
    "release",
    "rollback",
    "forecast",
    "evaluate-outcomes",
    "analyze",
    "export-demo",
    "validate-demo",
    "verify-scenarios",
    "run",
    "environment",
    "export-snowflake",
]


def parser():
    result = argparse.ArgumentParser(
        prog="python -m gridcast", description="Native local GridCast stages"
    )
    result.add_argument("command", choices=COMMANDS)
    result.add_argument("--root", type=Path, default=ROOT, help="isolated state/output workspace")
    result.add_argument("--config", type=Path, default=ROOT / "config/project.yaml")
    result.add_argument(
        "--splits", type=Path, help="split specification for a new isolated workspace"
    )
    result.add_argument("--mode", choices=["build", "daily"], default="build")
    result.add_argument("--origin", help="00:00 UTC timestamp, e.g. 2025-10-01T00:00:00Z")
    result.add_argument("--start", help="source half-open start UTC")
    result.add_argument("--end", help="source half-open end UTC")
    result.add_argument(
        "--release-id", help="explicit validated release; default resolves current once"
    )
    result.add_argument(
        "--fixture", action="store_true", help="synthetic only; use an isolated --root"
    )
    result.add_argument(
        "--offline", action="store_true", help="no API requests; verified cache only"
    )
    result.add_argument(
        "--refresh", action="store_true", help="refetch specified window; append deliveries"
    )
    result.add_argument(
        "--compact", action="store_true", help="one candidate configuration for fixture CI"
    )
    result.add_argument(
        "--policy",
        choices=["retrospective_frozen", "prospective_first_seen", "prospective_latest_revision"],
    )
    result.add_argument(
        "--fail-after", type=int, choices=[12], help="synthetic fault injection only"
    )
    return result


def execute(args):
    # All input/config validation precedes workspace/network/database mutation.
    settings = load_settings(args.config)
    for value in (args.origin, args.start, args.end):
        if value:
            utc(value)
    if args.origin and utc(args.origin) != utc(args.origin).normalize():
        raise ValueError("origin must be UTC midnight")
    if args.start and args.end and utc(args.end) <= utc(args.start):
        raise ValueError("end must follow start")
    if args.command == "forecast" and not args.origin:
        raise ValueError("forecast requires --origin")
    if args.fixture and args.root.resolve() == ROOT:
        raise ValueError("synthetic execution requires isolated --root")
    if args.command == "generate-fixture" and args.root.resolve() == ROOT:
        raise ValueError("fixture generation cannot use the real project workspace")
    if args.splits:
        split_document = yaml.safe_load(args.splits.read_text(encoding="utf-8"))
        boundaries = [
            utc(split_document["train_start"]),
            *[utc(v) for v in split_document["validation_boundaries"]],
            utc(split_document["test_end"]),
        ]
        if len(boundaries) != 6 or sorted(boundaries) != boundaries or len(set(boundaries)) != 6:
            raise ValueError("invalid split configuration")
    if args.command == "run" and args.mode == "daily" and args.fixture:
        raise ValueError("daily workflow consumes an existing release; no fixture generation")
    workspace = Workspace(args.root, settings)
    if workspace.root != ROOT and not workspace.path("config/project.yaml").exists():
        workspace.path("config/project.yaml").write_text(
            yaml.safe_dump(settings.model_dump()), encoding="utf-8"
        )
        shutil.copyfile(
            args.splits or ROOT / "config/splits.yaml", workspace.path("config/splits.yaml")
        )
        shutil.copyfile(
            ROOT / "config/feature_contract.yaml", workspace.path("config/feature_contract.yaml")
        )
    elif (
        args.splits
        and (workspace.root / "config/splits.yaml").read_bytes() != args.splits.read_bytes()
    ):
        raise ValueError("existing workspace split configuration differs")
    os.environ["OMP_NUM_THREADS"] = str(settings.threads)
    os.environ["OPENBLAS_NUM_THREADS"] = str(settings.threads)
    os.environ["MKL_NUM_THREADS"] = str(settings.threads)
    os.environ["MLFLOW_DISABLE_AGENT_HINT"] = "1"
    from .analysis import analyze
    from .evaluation import evaluate_outcomes
    from .fixtures import generate_fixture
    from .forecasting import forecast
    from .releases import create_release, rollback
    from .snapshots import export_demo, published_directory, validate_demo
    from .source import ingest, inspect_source
    from .storage import validate_source
    from .training import backtest, build_dataset, evaluate_test, seal_selection
    from .workflow import run, stage

    operations = {
        "environment": lambda: environment_receipt(),
        "generate-fixture": lambda: generate_fixture(workspace),
        "inspect-source": lambda: inspect_source(workspace),
        "ingest": lambda: ingest(workspace, args.start, args.end, args.refresh, args.offline),
        "validate-source": lambda: validate_source(workspace),
        "build-features": lambda: build_dataset(workspace),
        "backtest": lambda: backtest(workspace, args.compact),
        "seal-selection": lambda: seal_selection(workspace),
        "evaluate-test": lambda: evaluate_test(workspace),
        "release": lambda: create_release(workspace),
        "rollback": lambda: rollback(workspace, args.release_id),
        "forecast": lambda: forecast(workspace, args.origin, args.release_id, args.fail_after),
        "evaluate-outcomes": lambda: evaluate_outcomes(workspace, args.origin, args.policy),
        "analyze": lambda: analyze(workspace),
        "export-demo": lambda: export_demo(workspace),
        "validate-demo": lambda: validate_demo(published_directory(workspace.root / "demo")),
        "run": lambda: run(
            workspace, args.mode, args.fixture, args.offline, args.compact, args.origin
        ),
    }
    if args.command == "verify-scenarios":
        from .scenarios import verify_scenarios

        return stage(workspace, args.command, lambda: verify_scenarios(workspace))
    if args.command == "export-snowflake":
        from .manual_export import export_snowflake

        return stage(workspace, args.command, lambda: export_snowflake(workspace))
    return stage(workspace, args.command, operations[args.command])


def main():
    try:
        result = execute(parser().parse_args())
        print(
            redact(
                {
                    k: v
                    for k, v in result.items()
                    if k
                    in {
                        "status",
                        "release_id",
                        "rows",
                        "paired_targets",
                        "origin",
                        "inserted_rows",
                        "replay",
                        "serving_path",
                        "generation",
                        "feature_rows",
                        "windows",
                    }
                }
            )
        )
        return 0
    except Exception as error:
        # Never print traceback/request objects containing credentials.
        print(f"GridCast failed: {type(error).__name__}: {redact(str(error))}", file=sys.stderr)
        return 1
