"""Read final evidence and execute bounded local integrity/lint/dependency gates."""

import subprocess
import sys
import xml.etree.ElementTree as ET

from gridcast.config import ROOT, Workspace, load_settings
from gridcast.snapshots import load_demo
from gridcast.training import verify_seal
from gridcast.util import now, write_json


def main():
    outcomes = []
    for arguments in [
        ["-m", "ruff", "check", "src", "app", "tests", "scripts", "snowflake"],
        ["-m", "pip", "check"],
    ]:
        result = subprocess.run(
            [sys.executable, *arguments], cwd=ROOT, text=True, capture_output=True, check=False
        )
        outcomes.append(
            {
                "command": "python " + " ".join(arguments),
                "exit_code": result.returncode,
                "output": result.stdout.strip(),
            }
        )
        if result.returncode:
            raise RuntimeError("local lint/dependency gate failed")
    suite = ET.parse(ROOT / "docs/evidence/pytest-final.xml").getroot().find("testsuite")
    pytest = {key: suite.attrib[key] for key in ["tests", "failures", "errors", "skipped", "time"]}
    if any(int(pytest[key]) for key in ["failures", "errors", "skipped"]):
        raise ValueError("final local suite must have no failure/error/skip")
    workspace = Workspace(ROOT, load_settings(ROOT / "config/project.yaml"))
    seal = verify_seal(workspace)
    demo = load_demo(ROOT / "demo")
    write_json(
        ROOT / "docs/evidence/checks.json",
        {
            "at": now(),
            "status": "PASS",
            "commands": outcomes,
            "pytest": pytest,
            "pytest_command": "python -m pytest -q --junitxml=docs/evidence/pytest-final.xml",
            "seal_hash": seal["seal_hash"],
            "demo_generation": demo["manifest"]["generation_id"],
            "hosted_ci": "PENDING_NOT_EXECUTED",
            "linux_dependency_install": "PENDING_NOT_EXECUTED",
            "snowflake": "UNEXECUTED",
        },
    )
    print("Release evidence checks: PASS", pytest)


if __name__ == "__main__":
    main()
