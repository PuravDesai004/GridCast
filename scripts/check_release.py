"""Read-only public evidence/demo checks and optional local serving-bundle integrity."""

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

from gridcast.releases import resolve_release
from gridcast.snapshots import load_demo
from gridcast.util import contained, file_hash, read_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--public-only", action="store_true", help="Do not require local models/state")
    args = parser.parse_args()
    root = args.root.resolve()
    index = read_json(root / "docs/evidence/index.json")
    for relative, record in index["files"].items():
        path = contained(root, relative)
        if path.stat().st_size != record["bytes"] or file_hash(path) != record["sha256"]:
            raise ValueError(f"historical evidence integrity mismatch: {relative}")
    demo = load_demo(root / "demo")
    result = {
        "status": "PASS",
        "historical_index_files": len(index["files"]),
        "demo_generation": demo["manifest"]["generation_id"],
        "forecast_rows": len(demo["forecasts"]),
        "metric_rows": len(demo["metrics"]),
        "scope": "public evidence/demo" if args.public_only else "public evidence/demo + local bundle",
        "read_only": True,
    }
    if not args.public_only:
        # Avoid Workspace.path(), which creates directories even for missing inputs.
        workspace = SimpleNamespace(root=root, path=lambda name: root / name)
        manifest, _, corrupt = resolve_release(workspace)
        if corrupt:
            raise ValueError("local serving bundle integrity failure")
        result["release_id"] = manifest["release_id"]
        result["model_loaded"] = False
        result["historical_code_scope"] = "artifact integrity; later code changes do not inherit accuracy"
    print(json.dumps(result))


if __name__ == "__main__":
    main()
