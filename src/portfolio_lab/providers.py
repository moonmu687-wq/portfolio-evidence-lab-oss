"""Strict provider parsing. Success envelopes are not completeness certificates."""

import re
from pathlib import Path

import pandas as pd

from .evidence import DataError, read_json
from .models import Holding


def wind_tables(path: Path):
    envelope = read_json(path)
    if envelope.get("ok") is False or envelope.get("isError"):
        raise DataError(f"Wind failed: {path.name}")
    import json

    try:
        inner = json.loads(envelope["content"][0]["text"])
    except (ValueError, KeyError, IndexError) as exc:
        raise DataError(f"Wind missing/unstructured result: {path.name}") from exc
    if inner.get("error"):
        raise DataError(f"Wind backend error: {path.name}")
    tables = inner.get("data", {}).get("data", [])
    if not tables:
        raise DataError(f"No data tables: {path.name}")
    return tables


def nav_file(path: Path, code: str, start: str, end: str):
    all_rows = []
    for table in wind_tables(path):
        cols = table["columns"]
        names = [c["name"] for c in cols]
        nav = [i for i, n in enumerate(names) if "复权" in n and "净值" in n]
        dates = [i for i, c in enumerate(cols) if c["type"] == "date" and "成立" not in c["name"]]
        codes = [i for i, n in enumerate(names) if n == "Wind代码"]
        if len(nav) != 1 or len(dates) != 1 or len(codes) != 1:
            raise DataError(f"Unexpected NAV schema: {path.name}: {names}")
        currency_cols = [i for i, n in enumerate(names) if n == "单位净值币种"]
        cny_verified = "人民币" in names[nav[0]] or (
            len(currency_cols) == 1
            and all(row[currency_cols[0]] in ("人民币", "人民币元", "CNY") for row in table["rows"])
        )
        if not cny_verified or cols[nav[0]].get("unit") != "元":
            raise DataError(f"NAV currency/unit unverified: {path.name}")
        if len(table["rows"]) >= 100:
            raise DataError(f"Potential 100-row truncation: {path.name}; split interval")
        for row in table["rows"]:
            if str(row[codes[0]]).split(".")[0] != code:
                raise DataError(f"Wrong security in response: {path.name}")
            day = str(row[dates[0]])[:10]
            value = row[nav[0]]
            if not start <= day <= end:
                raise DataError(f"Out-of-window NAV: {path.name}: {day}")
            if value is None or not isinstance(value, (int, float)) or value <= 0:
                raise DataError(f"Invalid NAV: {path.name}")
            all_rows.append({"code": code, "date": day, "adjusted_nav": float(value), "source_id": path.name})
    return all_rows


def load_nav(root: Path, codes: list[str]):
    rows = []
    files = []
    for code in codes:
        exact = sorted(root.glob(f"{code}-exact-nav-*.json"))
        paths = exact or sorted(root.glob(f"{code}-nav-*.json"))
        paths = [p for p in paths if not p.name.endswith(".request.json")]
        if not paths:
            raise DataError(f"No NAV evidence for {code}")
        for path in paths:
            request = read_json(Path(str(path) + ".request.json"))
            bounds = re.findall(r"\d{4}-\d{2}-\d{2}", request["query"]["question"])
            if len(bounds) != 2:
                raise DataError(f"Unrecognized request window {path.name}")
            rows.extend(nav_file(path, code, *bounds))
            files.extend([path, Path(str(path) + ".request.json")])
    frame = pd.DataFrame(rows)
    if frame.empty or frame.duplicated(["code", "date"]).any():
        raise DataError("Missing or duplicate NAV observations")
    if not pd.Series(frame.adjusted_nav).map(lambda x: float("-inf") < x < float("inf")).all():
        raise DataError("Non-finite NAV")
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values(["date", "code"]), files


def holding_file(path: Path, code: str, holding_date: str):
    records = []
    for table in wind_tables(path):
        cols = table["columns"]
        names = [c["name"] for c in cols]
        ids = [i for i, n in enumerate(names) if "股票代码" in n]
        labels = [i for i, n in enumerate(names) if "股票名称" in n or "重仓股票名称" in n]
        weights = [i for i, n in enumerate(names) if ("占基金净资产比例" in n or "占基金资产净值比" in n)]
        if len(ids) != 1 or len(labels) != 1 or len(weights) != 1:
            raise DataError(f"Holdings schema mismatch: {path.name}")
        if cols[weights[0]].get("unit") != "%":
            raise DataError("Holdings weight denominator/unit unverified")
        for row in table["rows"]:
            if "Wind代码" in names and str(row[names.index("Wind代码")]).split(".")[0] != code:
                raise DataError(f"Wrong fund in holdings response: {path.name}")
            security = row[ids[0]]
            if not security or row[weights[0]] is None:
                continue
            records.append(
                Holding(
                    fund=code,
                    security=security,
                    name=row[labels[0]],
                    weight=row[weights[0]] / 100,
                    holding_date=holding_date,
                    source_id=path.name,
                    scope="top10" if len(table["rows"]) <= 10 else "partial",
                )
            )
    if not records:
        raise DataError(f"No stock holding rows: {path.name}")
    return records
