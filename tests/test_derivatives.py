import pytest

from portfolio_lab.derivatives import aggregate_derivatives, parse_single_future
from portfolio_lab.evidence import DataError


def test_zero_settlement_value_does_not_erase_futures_exposure():
    text = """2026 年中期报告 123456
净资产合计 1,000.00
单位：人民币元
权益衍生工具 100.00 - - -
代码 名称 持仓量(买/卖) 合约市值 公允价值变动
ESU6 S&P500 Sep26 2 110.00 10.00
合计 - - - 10.00
减： 可抵销期货暂收款 - - - 10.00
净额 - - - -"""
    spec = dict(
        fund="123456",
        contract="ESU6",
        underlying="S&P 500",
        report_title="2026年中期报告",
        verified_contract_market_value_cny=110,
        verified_quantity=2,
        holding_date="2026-06-30",
        published_date="2026-08-31",
        path="source.pdf",
        pages="1",
        url="https://example.org/report.pdf",
    )
    record = parse_single_future(text, spec)
    split_value = text.replace("2 110.00 10.00", "2 110. 10.00\nPAGE 2\n00")
    assert parse_single_future(split_value, spec) == record
    dax_text = (
        text.replace("权益衍生工具", "权益衍\n生工具")
        .replace("ESU6 S&P500 Sep26 2", "FDAX2609 FDAX2609 2.00")
        .replace("合计 - - -", "合计")
    )
    dax_spec = {**spec, "contract": "FDAX2609", "underlying": "DAX"}
    assert parse_single_future(dax_text, dax_spec)["quantity"] == 2
    assert record["signed_notional_nav_fraction"] == pytest.approx(0.11)
    assert aggregate_derivatives([record], {"123456": 0.5})[
        "sum_disclosed_long_notional_fraction"
    ] == pytest.approx(0.055)
    spec["verified_contract_market_value_cny"] = 120
    with pytest.raises(DataError):
        parse_single_future(text, spec)
