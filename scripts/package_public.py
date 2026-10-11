"""Package compact existing receipts and one real dashboard generation; no new metrics."""

import ast
import shutil
from collections import Counter

from gridcast.config import ROOT
from gridcast.snapshots import load_demo
from gridcast.util import file_hash, now, read_json, write_json


def main():
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / "state/fixture-release-check"
    stages = [read_json(path) for path in sorted((fixture / "state/stages").glob("*.json"))]
    write_json(
        evidence / "clean_fixture.json",
        {
            "status": "PASS" if all(stage["status"] == "PASS" for stage in stages) else "FAILED",
            "kind": "SYNTHETIC",
            "isolated_root": "state/fixture-release-check",
            "command": "python -m gridcast run --mode build --fixture --compact --offline --root state/fixture-release-check --config config/fixture.yaml --splits config/fixture_splits.yaml",
            "stages": [
                {
                    key: stage[key]
                    for key in ["stage", "status", "duration_seconds", "started_at", "finished_at"]
                }
                for stage in stages
            ],
            "source": read_json(fixture / "state/source_validation.json"),
            "test_kind": "SYNTHETIC_ENGINEERING_ONLY",
            "demo_validation": read_json(fixture / "state/demo_validation.json"),
            "recovery": {
                key: read_json(fixture / "docs/evidence/recovery.json")[key]
                for key in ["passed", "pending"]
            },
        },
    )
    members = read_json(ROOT / "state/split_membership.json")
    write_json(
        evidence / "membership_summary.json",
        {
            "scheduled_origins": len(members),
            "by_split": dict(Counter(row["split"] for row in members)),
            "quality_excluded": [
                {key: row[key] for key in ["origin", "split", "gates", "baseline_eligible"]}
                for row in members
                if row["gates"]
            ],
            "full_membership_local": "state/split_membership.json",
            "sha256": file_hash(ROOT / "state/split_membership.json"),
        },
    )
    demo = load_demo(ROOT / "demo")
    pointer = read_json(ROOT / "demo/published/current.json")
    generation = pointer["generation_id"]
    ignore_path = ROOT / ".gitignore"
    ignore = (
        ignore_path.read_text(encoding="utf-8")
        .split("# Current reviewed demo generation")[0]
        .rstrip()
    )
    ignore_path.write_text(
        ignore
        + f"\n# Current reviewed demo generation\n!demo/published/generations/{generation}/\n!demo/published/generations/{generation}/**\n",
        encoding="utf-8",
    )
    write_json(
        evidence / "published_demo.json",
        {
            "at": now(),
            "pointer": pointer,
            "files": demo["manifest"]["files"],
            "release_id": demo["manifest"]["release_id"],
            "kind": demo["manifest"]["kind"],
            "rows": len(demo["forecasts"]),
            "metric_rows": len(demo["metrics"]),
        },
    )
    for name in [
        "selection",
        "selection_seal",
        "first_test_evaluation",
        "test_result",
        "source_validation",
        "final_fit",
        "demo_validation",
        "analysis",
        "features",
        "feature_lineage_receipt",
        "registry_alias_mirror",
    ]:
        shutil.copyfile(ROOT / f"state/{name}.json", evidence / f"{name}.json")
    syntax = []
    for path in sorted((ROOT / "snowflake").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"))
        syntax.append(str(path.relative_to(ROOT)))
    write_json(
        evidence / "manual_syntax.json",
        {
            "status": "PASS",
            "method": "AST parse only, no imports/connections/warehouse SQL",
            "files": syntax,
            "warehouse_status": "UNEXECUTED",
        },
    )
    files = sorted(
        path for path in evidence.rglob("*") if path.is_file() and path.name != "index.json"
    )
    write_json(
        evidence / "index.json",
        {
            "at": now(),
            "files": {
                str(path.relative_to(ROOT)): {
                    "sha256": file_hash(path),
                    "bytes": path.stat().st_size,
                }
                for path in files
            },
        },
    )
    print("Public evidence packaged and real generation validated")


if __name__ == "__main__":
    main()
