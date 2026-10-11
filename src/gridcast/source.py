"""Bounded EIA v2 client; no prepared URLs or raw HTTP exceptions escape this module."""

import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import pandas as pd
import requests

from .config import utc
from .storage import publish_window
from .util import digest, file_hash, now, read_json, redact, write_json

BASE = "https://api.eia.gov/v2/electricity/rto/region-data/"


class SourceError(ValueError):
    pass


class EIAClient:
    def __init__(self, key=None, session=None, sleep=time.sleep, attempts=4):
        self.key = key or os.environ.get("EIA_API_KEY")
        if not self.key:
            raise SourceError("EIA_API_KEY is absent; enter it privately in the launching session")
        self.session = session or requests.Session()
        self.sleep = sleep
        self.attempts = attempts

    def request(self, suffix="", params=None):
        for attempt in range(self.attempts):
            try:
                response = self.session.get(
                    BASE + suffix, params={**(params or {}), "api_key": self.key}, timeout=(10, 45)
                )
            except (requests.Timeout, requests.ConnectionError):
                if attempt + 1 == self.attempts:
                    raise SourceError("EIA network request exhausted bounded retries") from None
                self.sleep(min(2**attempt, 30))
                continue
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt + 1 == self.attempts:
                    raise SourceError(f"EIA HTTP {response.status_code}; retry budget exhausted")
                delay = min(2**attempt, 30)
                retry = response.headers.get("Retry-After")
                if retry:
                    try:
                        delay = float(retry)
                    except ValueError:
                        try:
                            delay = (
                                parsedate_to_datetime(retry) - datetime.now(timezone.utc)
                            ).total_seconds()
                        except (TypeError, ValueError):
                            pass
                self.sleep(max(0, min(delay, 60)))
                continue
            if response.status_code != 200:
                raise SourceError(
                    f"EIA HTTP {response.status_code}; authentication/contract failure"
                )
            try:
                payload = response.json()
            except ValueError:
                raise SourceError("EIA returned invalid JSON") from None
            payload = redact(payload, self.key)
            if "error" in payload or "response" not in payload:
                raise SourceError("EIA API error/invalid response contract")
            return payload
        raise SourceError("unreachable request failure")

    def window(self, start, end, page_size=5000):
        start, end = utc(start), utc(end)
        if end <= start or page_size < 1 or page_size > 5000:
            raise SourceError("invalid source window/page size")
        params = {
            "frequency": "hourly",
            "data[0]": "value",
            "facets[respondent][]": "PJM",
            "facets[type][]": "D",
            "start": start.strftime("%Y-%m-%dT%H"),
            "end": (end - pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H"),
            "length": page_size,
        }
        for index, column in enumerate(["period", "respondent", "type"]):
            params[f"sort[{index}][column]"] = column
            params[f"sort[{index}][direction]"] = "asc"
        pages, total, keys, previous = [], None, {}, None
        offset = 0
        while total is None or offset < total:
            payload = self.request("data/", {**params, "offset": offset})
            response = payload["response"]
            try:
                reported = int(response["total"])
                rows = response["data"]
            except (KeyError, TypeError, ValueError):
                raise SourceError("missing/invalid pagination contract") from None
            if response.get("frequency", "hourly") != "hourly":
                raise SourceError("frequency mismatch")
            if reported < 0 or reported > int((end - start).total_seconds() / 3600):
                raise SourceError("source total exceeds bounded window")
            if total is not None and total != reported:
                raise SourceError("unstable page total; discard whole staged window")
            total = reported
            if len(rows) != min(page_size, total - offset):
                raise SourceError("partial API page; discard whole staged window")
            for row in rows:
                if row.get("respondent") != "PJM" or row.get("type") != "D":
                    raise SourceError("source facet mismatch")
                timestamp = utc(row["period"] + "Z")
                if not start <= timestamp < end:
                    raise SourceError("out-of-bounds API row")
                key = row["period"]
                if key in keys:
                    if keys[key] != digest(row):
                        raise SourceError("same-key source conflict")
                    raise SourceError("duplicate page identity")
                if previous is not None and key <= previous:
                    raise SourceError("source sort contract failed")
                previous = key
                keys[key] = digest(row)
            pages.append((offset, payload))
            offset += len(rows)
            if total == 0:
                break
        if len(keys) != total:
            raise SourceError("incomplete staged window")
        return pages


def inspect_source(workspace, client=None):
    client = client or EIAClient()
    evidence = {
        "metadata": client.request(),
        "respondents": client.request("facet/respondent/"),
        "types": client.request("facet/type/"),
    }
    metadata = evidence["metadata"]["response"]
    frequencies = {v["id"]: v for v in metadata["frequency"]}
    if "hourly" not in frequencies or "UTC" not in str(frequencies["hourly"]):
        raise SourceError("hourly UTC frequency semantics not verified")
    respondents = evidence["respondents"]["response"]["facets"]
    pjm = next((row for row in respondents if row["id"] == "PJM"), None)
    demand = next(
        (row for row in evidence["types"]["response"]["facets"] if row["id"] == "D"), None
    )
    if not pjm or not demand:
        raise SourceError("PJM/demand metadata not verified")
    probe = client.window("2024-01-01T00:00:00Z", "2024-01-01T02:00:00Z")
    rows = probe[0][1]["response"]["data"]
    if [r["period"] for r in rows] != ["2024-01-01T00", "2024-01-01T01"]:
        raise SourceError("inclusive bounds probe failed")
    units = {r["value-units"] for r in rows}
    if units != {"megawatthours"}:
        raise SourceError("expected source energy units not verified")
    evidence["bounds_probe"] = probe
    write_json(workspace.path("docs/evidence/source_metadata.json"), evidence)
    contract = {
        "kind": "REAL_EIA",
        "verified_at": now(),
        "authority": "PJM",
        "respondent": pjm,
        "metric": demand,
        "frequency": frequencies["hourly"],
        "unit": "megawatthours",
        "interval_mapping": "UTC hour-ending period; shift 0 hours",
        "timestamp_basis": "https://www.eia.gov/survey/form/eia_930/instructions.pdf",
        "api_basis": "https://www.eia.gov/opendata/documentation.php",
        "calendar_timezone": "America/New_York",
        "bounds": "inclusive start/end upstream",
        "route": BASE,
        "metadata_hash": digest(evidence),
        "route_start": metadata.get("startPeriod"),
        "route_end": metadata.get("endPeriod"),
    }
    write_json(workspace.path("state/source_contract.json"), contract)
    write_json(workspace.path("docs/evidence/source_contract.json"), contract)
    return contract


def ingest(workspace, start=None, end=None, refresh=False, offline=False, client=None):
    contract = read_json(workspace.path("state/source_contract.json"))
    if contract["kind"] != "REAL_EIA" or "shift 0" not in contract["interval_mapping"]:
        raise SourceError("verified real source contract required")
    settings = workspace.settings
    start = utc(start or settings.core_start) - (
        pd.Timedelta(days=settings.warmup_days) if start is None else pd.Timedelta(0)
    )
    end = utc(end or settings.core_end) + (
        pd.Timedelta(days=settings.label_padding_days) if end is None else pd.Timedelta(0)
    )
    windows = []
    cursor = start
    while cursor < end:
        stop = min((cursor + pd.offsets.MonthBegin(1)).normalize(), end)
        windows.append((cursor, stop))
        cursor = stop
    receipts = []
    for lower, upper in windows:
        fingerprint = digest(
            {"start": str(lower), "end": str(upper), "contract": contract["metadata_hash"]}
        )
        cache_path = workspace.path(f"data/raw/cache/{fingerprint}.json")
        if cache_path.exists() and not refresh:
            cached = read_json(cache_path)
            for checksum in cached["artifacts"]:
                if file_hash(workspace.path(f"data/raw/artifacts/{checksum}.json")) != checksum:
                    raise SourceError("cached artifact failed integrity check")
            receipts.append({**cached, "cache_reused": True})
            continue
        if offline:
            raise SourceError("offline cache window absent")
        client = client or EIAClient()
        pages = client.window(lower, upper, settings.page_size)
        receipt = publish_window(workspace, pages, lower, upper, contract["unit"])
        write_json(cache_path, receipt)
        receipts.append(receipt)
        print(f"collected {lower.date()} .. {upper.date()} ({receipt['rows']} rows)", flush=True)
    result = {
        "at": now(),
        "windows": len(receipts),
        "rows": sum(r["rows"] for r in receipts),
        "cache_reused_windows": sum(r.get("cache_reused", False) for r in receipts),
        "receipts": receipts,
    }
    write_json(workspace.path("state/ingestion.json"), result)
    return result
