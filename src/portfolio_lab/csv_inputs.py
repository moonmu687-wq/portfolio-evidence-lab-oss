"""Local CSV adapters. Values cross the same contracts as other data sources."""

import csv
import math
import re
from datetime import date
from pathlib import Path

import pandas as pd

from .evidence import DataError, sha256
from .models import Position
from .ssot import parse_snapshot


def _rows(path, required, allowed):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        if not required.issubset(header) or len(header) != len(set(header)) or set(header) - allowed:
            raise DataError("CSV headers are missing, duplicated or unsupported")
        rows = []
        for line, row in enumerate(reader, 2):
            if not row or not any(cell.strip() for cell in row):
                continue
            if len(row) != len(header):
                raise DataError(f"CSV row {line}: column count differs from header")
            rows.append([cell.strip() for cell in row])
    if not rows:
        raise DataError("CSV contains no data rows")
    return header, rows


def portfolio_csv(path: Path):
    required = {"code", "name", "as_of", "venue", "market_value"}
    header, rows = _rows(path, required, set(Position.model_fields))
    bundle = {
        "data_kind": "user-supplied",
        "portfolio": {"values": [header, *rows]},
        "source_observation": {"provider": "Local portfolio CSV", "sha256": sha256(path)},
    }
    try:
        parse_snapshot(bundle)
    except ValueError:
        raise DataError("Portfolio CSV failed position validation; check dates, codes and amounts") from None
    return bundle


def load_csv_nav(path: Path, codes: list[str]):
    columns = {"code", "date", "adjusted_nav", "currency", "adjustment", "source_id"}
    header, rows = _rows(path, columns, columns)
    observations = []
    for line, values in enumerate(rows, 2):
        row = dict(zip(header, values))
        try:
            valid = (
                re.fullmatch(r"\d{6}", row["code"])
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"])
                and date.fromisoformat(row["date"])
                and row["currency"] == "CNY"
                and row["adjustment"] == "total_return"
                and row["source_id"]
            )
            nav = float(row["adjusted_nav"])
            if not valid or not math.isfinite(nav) or nav <= 0:
                raise ValueError
        except ValueError:
            raise DataError(f"NAV CSV row {line}: invalid identity, date, value or return basis") from None
        observations.append(
            {"code": row["code"], "date": row["date"], "adjusted_nav": nav, "source_id": row["source_id"]}
        )
    frame = pd.DataFrame(observations)
    if set(frame.code) != set(codes):
        raise DataError("NAV CSV product identities do not match portfolio")
    if frame.duplicated(["code", "date"]).any():
        raise DataError("NAV CSV has duplicate product/date observations")
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values(["date", "code"]), [path]
