"""Authoritative atomic pointer and immutable, checksum-validated bundles."""

import shutil

from .features import FEATURES, SCHEMA
from .training import verify_seal
from .util import contained, digest, file_hash, now, read_json, write_json


def validate_bundle(workspace, release_id, strict=True):
    directory = contained(workspace.root / "releases/bundles", release_id)
    manifest = read_json(directory / "manifest.json")
    if (
        manifest["release_id"] != release_id
        or manifest["features"] != FEATURES
        or manifest["dtypes"] != SCHEMA
    ):
        raise ValueError("release feature schema/identity mismatch")
    if manifest["policy"] != "nonnegative_clip_v1" or manifest["baseline_policy"] != "week_lag_v1":
        raise ValueError("unsupported release policy")
    corrupt = []
    for relative, checksum in manifest["checksums"].items():
        path = contained(directory, relative)
        if not path.exists() or file_hash(path) != checksum:
            corrupt.append(relative)
    if strict and corrupt:
        raise ValueError("release bundle integrity failure")
    return manifest, directory, corrupt


def resolve_release(workspace, release_id=None):
    pointer = read_json(workspace.path("releases/current.json")) if release_id is None else None
    release_id = release_id or pointer["release_id"]
    manifest, directory, corrupt = validate_bundle(workspace, release_id, strict=False)
    if pointer and file_hash(directory / "manifest.json") != pointer["manifest_checksum"]:
        raise ValueError("authoritative release pointer checksum mismatch")
    return manifest, directory, corrupt


def promote(workspace, release_id, action="release"):
    manifest, directory, _ = validate_bundle(workspace, release_id)
    pointer_path = workspace.path("releases/current.json")
    old = read_json(pointer_path) if pointer_path.exists() else None
    pointer = {
        "release_id": release_id,
        "manifest_checksum": file_hash(directory / "manifest.json"),
        "selected_at": now(),
        "previous_release_id": old["release_id"] if old else None,
    }
    write_json(
        workspace.path(f"releases/history/{digest(pointer)}.json"),
        {"action": action, **pointer},
        immutable=True,
    )
    write_json(pointer_path, pointer)
    if manifest["champion"] == "candidate" and manifest.get("registry_version"):
        try:
            from mlflow import MlflowClient

            from .training import tracking

            tracking(workspace)
            MlflowClient().set_registered_model_alias(
                "GridCast_PJM_Candidate", "champion", manifest["registry_version"]
            )
            mirror = {"at": now(), "status": "RECONCILED", "release_id": release_id}
        except Exception as error:
            mirror = {
                "at": now(),
                "status": "PENDING",
                "release_id": release_id,
                "error_type": type(error).__name__,
            }
        write_json(workspace.path("state/registry_alias_mirror.json"), mirror)
    return pointer


def create_release(workspace):
    seal = verify_seal(workspace)
    test = read_json(workspace.path("state/test_result.json"))
    fit = read_json(workspace.path("state/final_fit.json"))
    identity = {
        "seal_hash": seal["seal_hash"],
        "champion": seal["champion"],
        "model_checksum": fit["model_checksum"],
    }
    release_id = digest(identity)[:24]
    directory = workspace.path(f"releases/bundles/{release_id}/manifest.json").parent
    if (directory / "manifest.json").exists():
        return promote(workspace, release_id)
    card = (
        f"# GridCast model card\n\nSource: {read_json(workspace.path('state/source_contract.json'))['kind']} PJM D; "
        "megawatthours, UTC interval ends. Retrospective availability assumes a three-hour delay; "
        "historical publication vintages were not reconstructed.\n\n"
        f"Champion: **{seal['champion']}**. Final fitting ends at {fit['fit_cutoff']}. "
        f"Training examples: {fit['rows']}; final training peak threshold: {fit['peak_threshold']} megawatthours.\n\n"
        f"Selection and validation: `{workspace.path('state/selection.json')}`. "
        f"Frozen test: `{workspace.path('state/test_result.json')}` ({test['paired_targets']} matched targets, "
        f"{test['paired_origins']}/{test['scheduled_origins']} origins).\n\n"
        "Features use known calendars, 168/336-clock-hour lags, a cutoff-eligible anchor, trailing "
        "24/168-hour population statistics and coverage, and 24-hour anchor change. "
        "One global histogram gradient boosting candidate; no random internal validation.\n\n"
        "Candidate gates: anchor age <=6h, >=22/24 recent, >=160/168 weekly, >=22/24 week lags. "
        "Fallback requires all 24 week lags; otherwise UNAVAILABLE with no numeric forecasts. "
        "Predictions are clipped at zero under nonnegative_clip_v1 in evaluation and serving.\n\n"
        "Intended use: portfolio planning/error inspection. No dispatch, realized savings, "
        "production SLA, prospective accuracy, or warehouse integration claims. "
        "No weather features or uncertainty intervals; unusually hot/cold weeks can defeat weekly lags.\n"
    )
    (directory / "model_card.md").write_text(card, encoding="utf-8")
    workspace.path("docs/model_card.md").write_text(card, encoding="utf-8")
    write_json(directory / "selection.json", read_json(workspace.path("state/selection.json")))
    write_json(directory / "test_result.json", test)
    write_json(directory / "seal.json", seal)
    if seal["champion"] == "candidate":
        shutil.copyfile(workspace.path("state/candidate.joblib"), directory / "candidate.joblib")
    checksums = {path.name: file_hash(path) for path in directory.iterdir() if path.is_file()}
    manifest = {
        "release_id": release_id,
        **identity,
        "created_at": now(),
        "features": FEATURES,
        "dtypes": SCHEMA,
        "policy": "nonnegative_clip_v1",
        "baseline_policy": "week_lag_v1",
        "registry_version": fit["mlflow"]["registry_version"]
        if seal["champion"] == "candidate"
        else None,
        "trained_candidate_registry_version": fit["mlflow"]["registry_version"],
        "model_uri": fit["mlflow"]["model_uri"],
        "fit_cutoff": fit["fit_cutoff"],
        "source_snapshot": read_json(workspace.path("state/source_validation.json"))[
            "snapshot_hash"
        ],
        "availability_mode": workspace.settings.availability_mode,
        "checksums": checksums,
        "peak_threshold": fit["peak_threshold"],
        "execution_origin": "LOCAL",
        "kind": read_json(workspace.path("state/source_contract.json"))["kind"],
    }
    write_json(directory / "manifest.json", manifest, immutable=True)
    return promote(workspace, release_id)


def rollback(workspace, release_id=None):
    current = read_json(workspace.path("releases/current.json"))
    release_id = release_id or current.get("previous_release_id")
    if not release_id:
        raise ValueError("no previous release; specify a validated release ID")
    return promote(workspace, release_id, action="rollback")
