"""Small deterministic artifact and receipt primitives. No credentials are persisted."""

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value, immutable=False):
    path = Path(path)
    content = canonical(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        if path.read_bytes() != content:
            raise ValueError(f"immutable artifact conflict: {path.name}")
        return
    temporary = path.with_name(f".{path.name}.{uid()}.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def redact(value, secret=None):
    """Drop request echoes and replace keys even inside arbitrary strings."""
    secret = secret or os.environ.get("EIA_API_KEY", "")
    if isinstance(value, dict):
        return {
            k: redact(v, secret)
            for k, v in value.items()
            if k.lower() not in {"request", "api_key", "apikey", "authorization"}
        }
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    if isinstance(value, str):
        if secret:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)(api_key|apikey)(=|%3[dD])[^&\s\"']+", r"\1=[REDACTED]", value)
    return value


def versions():
    names = [
        "requests",
        "pandas",
        "numpy",
        "pyarrow",
        "duckdb",
        "PyYAML",
        "pydantic",
        "tzdata",
        "scikit-learn",
        "mlflow",
        "joblib",
        "streamlit",
        "plotly",
        "pytest",
        "ruff",
    ]
    return {name: importlib.metadata.version(name) for name in names}


def environment_receipt():
    return {
        "at": now(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": versions(),
        "eia_key_present": bool(os.environ.get("EIA_API_KEY")),
        "threads": 2,
    }


def contained(root, relative):
    root = Path(root).resolve()
    # Manifests move between Windows and Linux; apply both platforms' path rules.
    portable = PureWindowsPath(relative)
    if Path(relative).is_absolute() or portable.drive or portable.root:
        raise ValueError("artifact path escapes its generation")
    path = root.joinpath(*portable.parts).resolve()
    if not path.is_relative_to(root):
        raise ValueError("artifact path escapes its generation")
    return path
