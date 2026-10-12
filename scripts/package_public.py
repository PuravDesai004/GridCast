"""Package an exact Git source tree without rewriting evidence, locks, or demo files."""

import argparse
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Git commit/ref to package")
    parser.add_argument("--output", type=Path, default=root / "state/gridcast-public-source.zip")
    args = parser.parse_args()
    tree = subprocess.check_output(
        ["git", "rev-parse", "--verify", f"{args.ref}^{{tree}}"], cwd=root, text=True
    ).strip()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError("choose a new output path; existing archives are not overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "archive", "--format=zip", "--output", str(output), tree], cwd=root, check=True
    )
    print(f"Packaged Git tree {tree}; {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
