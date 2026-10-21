from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.market_proxies import load_proxies, parse_dividend, verify_proxy


def test_distribution_requires_identity_units_and_publication_date():
    text = "基金主代码510310 本次分红方案（单位：人民币元/10份基金份额）0.24 除息日2025年11月21日 公告送出日期：2025年11月19日"
    parsed = parse_dividend(text, "510310")
    assert parsed["cash_per_share_cny"] == pytest.approx(0.024)
    with pytest.raises(DataError, match="identity"):
        parse_dividend(text, "510300")
    with pytest.raises(DataError, match="amount/unit"):
        parse_dividend(text.replace("/10份", "/1份"), "510310")
    with pytest.raises(DataError, match="after"):
        parse_dividend(text.replace("11月19日", "11月22日"), "510310")


def test_dividend_alignment_does_not_hide_other_nav_or_return_errors():
    dates = pd.date_range("2025-01-01", periods=45)
    units = np.full(45, 10.0)
    units[20:] = 9.9
    issuer = pd.DataFrame({"code": "510310", "date": dates, "unit_nav": units, "adjusted_nav": 10.0})
    vendor = issuer.copy()
    details = {"actions": [{"date": str(dates[20].date()), "description": "分红：每份派现金0.1元"}]}
    dividends = [{"ex_date": str(dates[20].date()), "cash_per_share_cny": 0.1}]
    issuer.loc[20:, "adjusted_nav"] = 10.001  # Only the cash day has a convention difference.
    verify_proxy(issuer, vendor, details, dividends, "510310")
    with pytest.raises(DataError, match="distributions"):
        verify_proxy(issuer, vendor, details, [], "510310")
    issuer.loc[25:, "adjusted_nav"] = 10.002
    with pytest.raises(DataError, match="beyond verified cash"):
        verify_proxy(issuer, vendor, details, dividends, "510310")
    issuer.loc[0, "unit_nav"] = 11
    with pytest.raises(DataError, match="raw unit NAVs"):
        verify_proxy(issuer, vendor, details, dividends, "510310")


def test_real_proxy_sources_and_actions():
    root = Path(__file__).resolve().parents[1]
    catalog = root / "private/market_proxies.json"
    if not catalog.exists():
        pytest.skip("Private issuer evidence unavailable")
    nav, qa, paths = load_proxies(root, catalog, "2025-09-12", "2026-09-21")
    assert all(p.is_file() for p in paths)
    assert set(nav.code) == set(qa)
    assert all(v["matched_dates"] >= 200 and v["maximum_return_difference"] < 2e-6 for v in qa.values())
    assert [x["cash_per_share_cny"] for x in qa["CN_EQUITY"]["dividends"]] == [0.022, 0.024, 0.075]
    assert qa["CN_EQUITY"]["issuer_chart_return_difference_before_convention_alignment"] > 2e-6
    assert len(qa["GOLD_CNY"]["share_actions"]) == 1
