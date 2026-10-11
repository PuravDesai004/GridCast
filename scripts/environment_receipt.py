"""Read-only environment checks; save bounded, secret-free evidence."""

import ctypes
import importlib
import importlib.metadata
import shutil
import subprocess
from pathlib import Path

from gridcast.util import environment_receipt, write_json

root = Path(__file__).resolve().parents[1]
packages = {
    "requests": "requests",
    "pandas": "pandas",
    "numpy": "numpy",
    "pyarrow": "pyarrow",
    "duckdb": "duckdb",
    "PyYAML": "yaml",
    "pydantic": "pydantic",
    "tzdata": "tzdata",
    "scikit-learn": "sklearn",
    "mlflow": "mlflow",
    "joblib": "joblib",
    "streamlit": "streamlit",
    "plotly": "plotly",
    "pytest": "pytest",
    "ruff": "ruff",
}
for module in packages.values():
    importlib.import_module(module)
receipt = environment_receipt()
receipt["import_checks"] = {name: "PASS" for name in packages}
receipt["disk_free_bytes"] = shutil.disk_usage(root).free
if hasattr(ctypes, "windll"):

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page", ctypes.c_ulonglong),
            ("available_page", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        receipt["ram_total_bytes"], receipt["ram_available_bytes"] = (
            status.total_physical,
            status.available_physical,
        )
check = subprocess.run(
    [receipt["executable"], "-m", "pip", "check"], capture_output=True, text=True
)
receipt["pip_check"] = {"exit_code": check.returncode, "stdout": check.stdout.strip()}
assert check.returncode == 0
freeze = subprocess.run(
    [receipt["executable"], "-m", "pip", "freeze"], capture_output=True, text=True, check=True
).stdout
freeze = (
    "\n".join(line for line in freeze.splitlines() if not line.startswith(("-e ", "gridcast")))
    + "\n"
)
(root / "requirements/local.windows-py314.lock.txt").write_text(freeze, encoding="utf-8")
portable = (
    "\n".join(
        line + '; sys_platform == "win32"' if line.lower().startswith("pywin32==") else line
        for line in freeze.splitlines()
    )
    + "\n"
)
(root / "requirements/local.lock.txt").write_text(portable, encoding="utf-8")
receipt["lock_scope"] = "resolved on Windows x64 Python 3.14; Linux CI prepared, not executed"
try:
    receipt["setuptools"] = importlib.metadata.version("setuptools")
except importlib.metadata.PackageNotFoundError:
    receipt["setuptools"] = "isolated pip build dependency; not installed in runtime"
write_json(root / "docs/evidence/environment.json", receipt)
print(
    {
        "imports": "PASS",
        "pip_check": "PASS",
        "python": receipt["python"],
        "ram_available_bytes": receipt.get("ram_available_bytes"),
        "disk_free_bytes": receipt["disk_free_bytes"],
    }
)
