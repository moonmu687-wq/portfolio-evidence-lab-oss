"""Read-only Google Sheets ingestion; connector snapshots and direct OAuth reads."""

import os
import re
from datetime import date, datetime, timedelta

import requests

from .evidence import DataError
from .models import Position


def parse_snapshot(bundle):
    values = bundle["portfolio"]["values"]
    if not isinstance(values, list) or not values or not isinstance(values[0], list):
        raise DataError("SSOT schema mismatch")
    header = list(values[0])
    while header and header[-1] in (None, ""):
        header.pop()
    if (
        not all(isinstance(x, str) and x for x in header)
        or len(set(header)) != len(header)
        or not {"code", "market_value", "as_of", "venue", "name"}.issubset(header)
        or set(header) - (set(Position.model_fields) | {"account"})
    ):
        raise DataError("SSOT headers missing, duplicated or unsupported")
    positions = []
    warnings = []
    for row_no, row in enumerate(values[1:], 2):
        if not isinstance(row, list) or any(v not in (None, "") for v in row[len(header) :]):
            raise DataError(f"SSOT row {row_no}: data outside labeled columns")
        if not any(v is not None and v != "" for v in row):
            continue
        d = dict(zip(header, row))
        if any(isinstance(d.get(k), bool) for k in ["as_of", "market_value", "quantity", "cost_basis"]):
            raise DataError("SSOT booleans cannot become dates or amounts")
        if isinstance(d.get("as_of"), (int, float)):
            if not float(d["as_of"]).is_integer():
                raise DataError("SSOT snapshot date must not contain a fractional day")
            d["as_of"] = date(1899, 12, 30) + timedelta(days=d["as_of"])
        code = d.get("code")
        if not isinstance(code, str):
            raise DataError(f"SSOT row {row_no}: code must remain text with leading zeros")
        keep = {k: v for k, v in d.items() if k in Position.model_fields and v not in (None, "")}
        positions.append(Position.model_validate(keep))
        if "待" in str(d.get("notes", "")):
            warnings.append(f"{code}: SSOT备注存在待确认项，结构化已填字段保留原值，未改写真源")
    if not positions:
        raise DataError("SSOT has no usable positions")
    if len({p.code for p in positions}) != len(positions):
        raise DataError("Duplicate product codes: aggregate accounts explicitly before research")
    if len({p.as_of for p in positions}) != 1:
        raise DataError("Mixed position snapshot dates")
    return positions, warnings


def sheet_ranges(metadata, spreadsheet_id):
    """Read declared grid bounds, not a fixed 500-row prefix."""
    if metadata.get("spreadsheetId") != spreadsheet_id:
        raise DataError("Google Sheets identity mismatch")
    sheets = [s["properties"] for s in metadata.get("sheets", [])]
    result = []
    cells = 0
    for name in ["00_Portfolio", "01_Account"]:
        matches = [s for s in sheets if s.get("title") == name]
        if len(matches) != 1 or matches[0].get("sheetType", "GRID") != "GRID":
            raise DataError("Required SSOT grid tab absent/ambiguous")
        grid = matches[0].get("gridProperties", {})
        rows, columns = grid.get("rowCount"), grid.get("columnCount")
        if type(rows) is not int or type(columns) is not int or min(rows, columns) <= 0:
            raise DataError("SSOT grid dimensions missing")
        cells += rows * columns
        if cells > 200_000:
            raise DataError("SSOT grid exceeds bounded read capacity; no partial read accepted")
        label, n = "", columns
        while n:
            n, remainder = divmod(n - 1, 26)
            label = chr(65 + remainder) + label
        result.append(f"'{name}'!A1:{label}{rows}")
    return result


def read_google_sheet(spreadsheet_id: str, token_env="GOOGLE_SHEETS_ACCESS_TOKEN", session=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", spreadsheet_id):
        raise DataError("Google Sheets ID malformed")
    token = os.environ.get(token_env)
    if not token:
        raise DataError(
            f"{token_env} ABSENT; use an authorized connector snapshot or a read-only OAuth token"
        )
    headers = {"Authorization": f"Bearer {token}"}
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
    session = session or requests.Session()

    def get(url, params):
        try:
            response = session.get(url, headers=headers, params=params, timeout=30, allow_redirects=False)
        except requests.RequestException:
            raise DataError("Google Sheets request failed; credentials and response not logged") from None
        if response.status_code != 200:
            raise DataError(f"Google Sheets HTTP {response.status_code}; credentials and response not logged")
        try:
            return response.json()
        except ValueError:
            raise DataError("Google Sheets response is not JSON") from None

    meta_params = {"fields": "spreadsheetId,properties,sheets.properties"}
    metadata = get(base, meta_params)
    ranges = sheet_ranges(metadata, spreadsheet_id)

    def values():
        result = {}
        for key, ran in zip(["portfolio", "account"], ranges):
            payload = get(
                base + "/values/" + ran,
                {
                    "valueRenderOption": "UNFORMATTED_VALUE",
                    "dateTimeRenderOption": "SERIAL_NUMBER",
                    "majorDimension": "ROWS",
                },
            )
            if (
                payload.get("range", "").replace("'", "") != ran.replace("'", "")
                or payload.get("majorDimension") != "ROWS"
            ):
                raise DataError("Google Sheets returned the wrong range/orientation")
            result[key] = payload
        return result

    first = values()
    second = values()
    after = get(base, meta_params)
    if first != second or metadata != after:
        raise DataError("SSOT changed during read; retry a fresh snapshot")
    out = {
        "metadata": metadata,
        **first,
        "retrieved_at": datetime.now().astimezone().isoformat(),
        "source_observation": {
            "provider": "Google Sheets read-only API",
            "ranges": ranges,
            "consistency": "Two complete value reads and bracketing metadata agree; not a transactional guarantee",
        },
    }
    parse_snapshot(out)
    return out
