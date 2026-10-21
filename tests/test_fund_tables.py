from copy import deepcopy
from datetime import date

import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.exposure import build_exposure
from portfolio_lab.fund_tables import parse_fund_investments
from portfolio_lab.official_fsfund import parse_nav


def test_ranked_funds_preserve_unresolved_mass_and_reject_wrong_denominator():
    source = {
        "fund": "123456",
        "report_title": "2026年中期报告",
        "holding_date": "2026-06-30",
        "published_date": "2026-08-31",
        "path": "source.pdf",
        "pages": "1-2",
        "url": "https://example.org/f.pdf",
        "reviewed_rows": [
            {
                "security": f"FUND:{i}",
                "name": f"Fund{i}",
                "name_parts": [f"Fund{i}"],
                "identity_source": "https://example.org/id",
            }
            for i in range(1, 11)
        ],
    }
    text = "2026年中期报告 123456\n净资产合计 100,000.00\n基金投资 20,000.00 20.00\n前十名基金投资明细 人民币元\n"
    text += "\n".join(f"{i} Fund{i}\n1,000\n.\n00 1.00" for i in range(1, 11)) + "\n7.11附注"
    rows, qa = parse_fund_investments(text, source)
    assert qa["disclosed_top10_nav_fraction"] == pytest.approx(0.1)
    assert qa["other_fund_nav_fraction"] == pytest.approx(0.1)
    assert all(h.kind == "fund" and h.scope == "top10" for h in rows)
    matrix, coverage, *_ = build_exposure(["123456"], rows, date(2026, 9, 21))
    assert coverage.loc["123456"] == 0
    assert matrix.loc["123456"].sum() == pytest.approx(1)
    assert matrix.filter(like="UNRESOLVED_FUND:").loc["123456"].sum() == pytest.approx(0.1)
    with pytest.raises(DataError):
        parse_fund_investments(text.replace("净资产合计 100,000.00", "净资产合计 50,000.00"), source)
    bad = deepcopy(source)
    bad["reviewed_rows"][0]["name_parts"] = ["Wrong fund"]
    with pytest.raises(DataError):
        parse_fund_investments(text, bad)


def test_hwabao_uses_inception_return_not_rounded_window_or_accumulated_nav():
    row = {
        "fundCode": "501312",
        "navDate": "20260921",
        "nav": 1.5,
        "totalNetValue": 1.6,
        "setupInc": 0.65,
        "dayInc": 0.2,
    }
    payload = {"code": "0000", "data": [row]}
    assert parse_nav(payload, "501312").adjusted_nav.iloc[0] == pytest.approx(1.65)
    with pytest.raises(DataError):
        parse_nav(payload, "000001")
    with pytest.raises(DataError):
        parse_nav({"code": "0000", "data": [row, row]}, "501312")
