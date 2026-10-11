"""Synthetic fixtures test engineering only and live in their own workspace."""

import numpy as np
import pandas as pd

from .config import utc
from .storage import connect, publish_window
from .util import digest, now, write_json


def generate_fixture(workspace, gaps=False):
    with connect(workspace) as connection:
        if connection.execute("SELECT count(*) FROM source_fetch").fetchone()[0]:
            raise ValueError("fixture generation requires empty isolated source state")
    settings = workspace.settings
    start = utc(settings.core_start) - pd.Timedelta(days=settings.warmup_days)
    end = utc(settings.core_end) + pd.Timedelta(days=settings.label_padding_days)
    times = pd.date_range(start, end, freq="h", inclusive="left")
    rng = np.random.default_rng(42)
    values = (
        80000 + 14000 * np.sin(2 * np.pi * (times.hour - 9) / 24) + 8000 * (times.dayofweek < 5)
    )
    values = (
        values + 6000 * np.cos(2 * np.pi * times.dayofyear / 366) + rng.normal(0, 700, len(times))
    )
    rows = [
        {
            "period": t.strftime("%Y-%m-%dT%H"),
            "respondent": "PJM",
            "type": "D",
            "value": str(round(float(v), 3)),
            "value-units": "megawatthours",
        }
        for t, v in zip(times, values, strict=True)
        if not (gaps and t.hour == 13 and t.day == 12)
    ]
    payload = {
        "response": {"total": str(len(rows)), "frequency": "hourly", "data": rows},
        "fixture": "SYNTHETIC_NOT_EIA",
    }
    receipt = publish_window(
        workspace, [(0, payload)], start, end, "megawatthours", kind="SYNTHETIC"
    )
    contract = {
        "kind": "SYNTHETIC",
        "unit": "megawatthours",
        "verified_at": now(),
        "interval_mapping": "synthetic UTC interval end",
        "metadata_hash": digest(payload),
        "warning": "not source evidence or real forecasting results",
    }
    write_json(workspace.path("state/source_contract.json"), contract)
    return receipt
