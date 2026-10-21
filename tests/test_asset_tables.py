from datetime import date

import pytest

from portfolio_lab.asset_tables import parse_physical_gold, parse_ranked_equities
from portfolio_lab.evidence import DataError
from portfolio_lab.exposure import build_exposure
from portfolio_lab.models import Holding


def test_split_equity_rows_preserve_names_and_do_not_parse_decimal_as_rank():
    text = """§7 所有股票投资
明细
1 00981 中芯国际 100 1,000
.00 10.00
PAGE 2
报告
第2页 共3页
2 01810 小米集团－
Ｗ 200 2,000.0
0 20.00
报告期内股票投资组合的重大变动"""
    rows = parse_ranked_equities(text, "hk_ranked")
    assert rows == [("HK:00981", "中芯国际", 1000, 10), ("HK:01810", "小米集团－Ｗ", 2000, 20)]
    with pytest.raises(DataError):
        parse_ranked_equities(text.replace("2 01810", "3 01810"), "hk_ranked")


def test_german_ticker_wraps_across_page_but_company_number_is_not_rank():
    text = """§7 所有权益投资明细
1 BAYER 拜耳 BAYN 德国 德国 100 1,000.00 10.00
PAGE 2
报告
第 2 页 共 3 页
AG-REG 股份 GY
2 SCOUT
24 SE Scout2
4 股份 G24 GY 德国 德国 100 2,000.00 20.00
报告期内权益投资组合的重大变动"""
    rows = parse_ranked_equities(text, "de_ranked")
    assert [x[0] for x in rows] == ["DE:BAYN", "DE:G24"]
    assert sum(x[2] for x in rows) == 3000


def test_gold_recursive_nav_mass_and_total_reconciliation():
    source = dict(
        fund="TARGET",
        report_code="123456",
        report_title="2026年中期报告",
        path="gold.pdf",
        pages="1",
        url="https://example.org/gold.pdf",
        holding_date="2026-06-30",
        published_date="2026-08-31",
    )
    text = """2026年中期报告 123456
净资产合计 10,000.00
贵金属投资 9,000.00
贵金属投资明细
1 Au99.99 Au99.99 100.00 9,000.
00 90.00
7.9 权证明细"""
    rows, qa = parse_physical_gold(text, source)
    feeder = Holding(
        fund="FEEDER",
        security="TARGET",
        name="Target fund",
        weight=0.8,
        holding_date=date(2026, 6, 30),
        published_date=date(2026, 8, 31),
        source_id="parent.json",
        kind="fund",
        scope="feeder",
    )
    matrix, coverage, *_ = build_exposure(["FEEDER"], [feeder] + rows, date(2026, 9, 21))
    assert coverage.iloc[0] == pytest.approx(0.72)
    assert matrix.loc["FEEDER", "SGE:Au99.99"] == pytest.approx(0.72)
    assert matrix.sum(axis=1).iloc[0] == pytest.approx(1)
    assert qa["reconciled"] and rows[0].kind == "gold" and rows[0].scope == "full_gold"
    with pytest.raises(DataError):
        parse_physical_gold(text.replace("贵金属投资 9,000.00", "贵金属投资 9,100.00"), source)
