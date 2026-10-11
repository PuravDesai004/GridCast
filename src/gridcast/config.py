from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[2]


def utc(value):
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must include UTC offset")
    return timestamp.tz_convert("UTC")


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project: Literal["gridcast"] = "gridcast"
    authority: Literal["PJM"] = "PJM"
    metric: Literal["D"] = "D"
    frequency: Literal["hourly"] = "hourly"
    source_route: Literal["electricity/rto/region-data"] = "electricity/rto/region-data"
    calendar_timezone: Literal["America/New_York"] = "America/New_York"
    availability_mode: Literal["retrospective", "prospective"] = "retrospective"
    assumed_delay_hours: int = Field(default=3, ge=0, le=24)
    core_start: str = "2024-01-01T00:00:00Z"
    core_end: str = "2026-01-01T00:00:00Z"
    warmup_days: int = Field(default=14, ge=14, le=30)
    label_padding_days: int = Field(default=2, ge=1, le=7)
    refresh_overlap_days: int = Field(default=7, ge=7, le=30)
    page_size: int = Field(default=5000, ge=1, le=5000)
    threads: int = Field(default=2, ge=1, le=2)
    seed: int = 42
    maximum_iterations: int = Field(default=150, ge=1, le=150)
    minimum_relative_wape_improvement: float = Field(default=0.02, ge=0, le=1)
    maximum_peak_mae_ratio: float = Field(default=1.05, ge=1, le=2)
    minimum_paired_origin_coverage: float = Field(default=0.90, ge=0.90, le=1)
    anchor_max_age: int = Field(default=6, ge=1, le=6)
    recent_min_count: int = Field(default=22, ge=22, le=24)
    weekly_min_count: int = Field(default=160, ge=160, le=168)
    week_lag_min_count: int = Field(default=22, ge=22, le=24)
    prediction_policy: Literal["nonnegative_clip_v1"] = "nonnegative_clip_v1"

    @model_validator(mode="after")
    def boundaries(self):
        start, end = utc(self.core_start), utc(self.core_end)
        if end <= start or start != start.normalize() or end != end.normalize():
            raise ValueError("core bounds must be increasing UTC midnights")
        ZoneInfo(self.calendar_timezone)
        return self


def load_settings(path=None):
    return Settings.model_validate(
        yaml.safe_load(Path(path or ROOT / "config/project.yaml").read_text(encoding="utf-8"))
    )


class Workspace:
    def __init__(self, root=ROOT, settings=None):
        self.root = Path(root).resolve()
        self.settings = settings or load_settings()

    def path(self, name):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db(self):
        return self.path("data/db/gridcast.duckdb")
