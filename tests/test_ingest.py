import json

import numpy as np
import pandas as pd
import pytest

from portfolio_lab.evidence import DataError, input_manifest, verify_manifest
from portfolio_lab.providers import nav_file
from portfolio_lab.returns import weekly_panel
from portfolio_lab.ssot import parse_snapshot


def response(tmp_path, rows):
    table = {
        "columns": [
            {"name": "Wind代码", "type": "string"},
            {"name": "人民币复权单位净值", "type": "number", "unit": "元"},
            {"name": "日期", "type": "date"},
        ],
        "rows": rows,
    }
    path = tmp_path / "raw.json"
    path.write_text(
        json.dumps({"content": [{"text": json.dumps({"data": {"data": [table]}, "error": None})}]}), "utf-8"
    )
    return path


def test_truncation_and_wrong_code_rejected(tmp_path):
    p = response(tmp_path, [["000001.OF", 1, "2026-01-01"]] * 100)
    with pytest.raises(DataError, match="truncation"):
        nav_file(p, "000001", "2026-01-01", "2026-01-02")
    p = response(tmp_path, [["000002.OF", 1, "2026-01-01"]])
    with pytest.raises(DataError, match="Wrong security"):
        nav_file(p, "000001", "2026-01-01", "2026-01-02")


def test_sheet_leading_zeros_and_unknowns():
    d = {
        "portfolio": {
            "values": [
                ["as_of", "venue", "code", "name", "market_value"],
                [46286, "场外", "000001", "test", 100],
            ]
        }
    }
    p, _ = parse_snapshot(d)
    assert str(p[0].as_of) == "2026-09-21"
    assert p[0].quantity is None
    d["portfolio"]["values"][1][2] = 1
    with pytest.raises(DataError):
        parse_snapshot(d)


def test_missing_week_does_not_create_zero_or_multiweek_covariance():
    dates = pd.date_range("2025-01-03", periods=45, freq="W-FRI")
    nav = pd.DataFrame({"code": "A", "date": dates, "adjusted_nav": np.arange(45) + 100})
    nav = nav.drop(index=10)
    returns, *_ = weekly_panel(nav, ["A"], dates[0], dates[-1], 0, 40)
    assert dates[10] not in returns.index
    assert dates[11] not in returns.index
    assert len(returns) == 42


def test_manifest_detects_tampering(tmp_path):
    p = tmp_path / "x"
    p.write_text("first")
    m = input_manifest([p], tmp_path)
    verify_manifest(m, tmp_path)
    p.write_text("second")
    with pytest.raises(DataError):
        verify_manifest(m, tmp_path)


def test_calendar_accepts_date_objects_and_microsecond_nav():
    dates = pd.date_range("2025-01-03", periods=45, freq="W-FRI").as_unit("us")
    nav = pd.DataFrame({"code": "A", "date": dates, "adjusted_nav": np.arange(45) + 100})
    returns, *_ = weekly_panel(nav, ["A"], dates[0].date(), dates[-1].date(), 0, 40)
    assert len(returns) == 44


def test_archived_evidence_survives_new_source_snapshot(tmp_path):
    from portfolio_lab.evidence import archive_inputs, materialize

    p = tmp_path / "original.json"
    p.write_text("old")
    records = archive_inputs(input_manifest([p], tmp_path), tmp_path)
    p.write_text("new")
    with pytest.raises(DataError):
        verify_manifest(records, tmp_path)
    verify_manifest(records, tmp_path, archived=True)
    dest = tmp_path / "replayed"
    materialize({"inputs": records, "code": []}, tmp_path, dest)
    assert (dest / "original.json").read_text() == "old"


def test_invalid_json_update_preserves_last_good_file(tmp_path):
    from portfolio_lab.evidence import read_json, write_json

    path = tmp_path / "latest.json"
    write_json(path, {"value": 1})
    with pytest.raises(ValueError):
        write_json(path, {"value": float("nan")})
    assert read_json(path) == {"value": 1}
