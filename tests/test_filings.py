import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.filings import parse_full_equity_text
from portfolio_lab.normalize import parse_sector_totals


def test_multimarket_table_reconciles_and_preserves_listing_identity(tmp_path):
    path = tmp_path / "report.txt"
    path.write_text(
        """2026 年中期报告 123456
净资产合计 1,000.00
所有权益投资明细
BRK/B US 美国 1 100.00 10.00
285A JP 日本 2 200.00 20.00
148 HK 中国香港 3 300.00 30.00
000660 KS 韩国 1 100.00 10.00
报告期内权益投资组合的重大变动
""",
        "utf8",
    )
    rows, qa = parse_full_equity_text(path, "123456", 700, "1", layout="global")
    assert [h.security for h in rows] == ["US:BRK.B", "JP:285A", "HK:00148", "KR:000660"]
    assert qa["equity_nav_coverage"] == pytest.approx(0.7)
    with pytest.raises(DataError):
        parse_full_equity_text(path, "123456", 800, "1", layout="global")
    with pytest.raises(DataError):
        parse_full_equity_text(path, "123456", 700, "1", layout="us")


def test_index_enhanced_requires_both_sleeves_and_combined_total(tmp_path):
    path = tmp_path / "split.txt"
    text = """2026年中期报告 018178
净资产合计 1,000.00
7.3.1 期末指数投资按公允价值占基金资产净值比例大小排序的所有股票投资明细
1 688256 寒武纪 2 600.00 60.00
7.3.2 期末积极投资按公允价值占基金资产净值比例大小排序的所有股票投资明细
1 688503 聚和材料 3 300.00 30.00
7.4 报告期内股票投资组合的重大变动
"""
    path.write_text(text, "utf8")
    rows, qa = parse_full_equity_text(path, "018178", 900, "1", layout="cn_split")
    assert [h.security for h in rows] == ["CN:688256", "CN:688503"]
    assert qa["equity_nav_coverage"] == pytest.approx(0.9)
    with pytest.raises(DataError, match="incomplete table"):
        parse_full_equity_text(path, "018178", 900, "1", layout="cn")
    path.write_text(text.replace("7.3.1", "7.3.9"), "utf8")
    with pytest.raises(DataError, match="sleeve boundaries"):
        parse_full_equity_text(path, "018178", 900, "1", layout="cn_split")


def test_index_and_active_industries_reconcile_before_combining():
    text = """报告期末按行业分类的境内股票投资组合
指数投资
C 制造业 600.00 60.00
合计 600.00 60.00
积极投资
C 制造业 200.00 20.00
M 科学研究和技术服务业 100.00 10.00
合计 300.00 30.00
所有股票投资明细
"""
    source = dict(
        layout="cn_split", fund="018178", holding_date="2026-06-30", path="report.pdf", equity_total=900
    )
    rows = parse_sector_totals(text, source, 1000)
    assert {r["sector"]: r["weight"] for r in rows} == pytest.approx(
        {"制造业": 0.8, "科学研究和技术服务业": 0.1}
    )
    with pytest.raises(DataError, match="do not reconcile"):
        parse_sector_totals(text.replace("200.00 20.00", "100.00 10.00"), source, 1000)


def test_wrapped_industry_keeps_full_label_even_when_tail_would_reconcile():
    text = """报告期末按行业分类的境内股票投资组合
B 采矿业 - -
C 制造业 800.00 80.00
H 住宿和餐饮业 - -
I 信息传输、 软件和信息技术服务
业 100.00 10.00
S 综合 - -
合计 900.00 90.00
所有股票投资明细
"""
    source = dict(layout="cn", fund="014642", holding_date="2026-06-30", path="report.pdf", equity_total=900)
    rows = parse_sector_totals(text, source, 1000)
    assert rows[1]["sector"] == "信息传输、软件和信息技术服务业"
    with pytest.raises(DataError, match="Truncated industry"):
        parse_sector_totals(text.replace("I 信息传输、 软件和信息技术服务\n", ""), source, 1000)
