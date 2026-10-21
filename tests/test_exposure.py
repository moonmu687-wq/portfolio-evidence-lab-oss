from datetime import date

import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.exposure import build_exposure
from portfolio_lab.models import Holding


def test_portfolio_exposure_aligns_by_fund_identity_not_row_order():
    import pandas as pd

    from portfolio_lab.exposure import aggregate_exposure

    matrix = pd.DataFrame({"CN:000001": [1.0, 0.0], "UNKNOWN:B": [0.0, 1.0]}, index=["A", "B"])
    weights = pd.Series([0.8, 0.2], index=["B", "A"])
    result = aggregate_exposure(matrix, weights, {})
    assert result["resolved_nav_fraction"] == pytest.approx(0.2)


def h(fund, security, weight, **kwargs):
    return Holding(
        fund=fund,
        security=security,
        name=security,
        weight=weight,
        holding_date=date(2026, 6, 30),
        source_id="synthetic-test",
        scope="partial",
        **kwargs,
    )


def test_feeder_multiplies_and_unknown_is_not_cash():
    m, c, lo, hi, _, _ = build_exposure(
        ["A", "C"], [h("A", "B", 0.9, kind="fund"), h("B", "X", 0.8), h("C", "X", 0.5)], date(2026, 9, 21)
    )
    assert m.loc["A", "X"] == pytest.approx(0.72)
    assert m.loc["A"].sum() == pytest.approx(1)
    assert c["A"] == pytest.approx(0.72)
    assert lo.loc["A", "C"] == pytest.approx(0.5)
    assert hi.loc["A", "C"] >= lo.loc["A", "C"]


def test_partial_cannot_be_normalized_to_100_percent():
    _, c, lo, _, _, _ = build_exposure(["A", "B"], [h("A", "X", 0.2), h("B", "X", 0.4)], date(2026, 9, 21))
    assert c["A"] == 0.2
    assert lo.loc["A", "B"] == 0.2


def test_cycle_and_lookahead_rejected():
    with pytest.raises(DataError, match="cycle"):
        build_exposure(["A"], [h("A", "B", 1, kind="fund"), h("B", "A", 1, kind="fund")], date(2026, 9, 21))
    with pytest.raises(DataError, match="Look-ahead"):
        build_exposure(["A"], [h("A", "X", 0.4, published_date=date(2026, 10, 1))], date(2026, 9, 21))


def test_duplicate_and_gross_exposure_rejected():
    with pytest.raises(DataError, match="Duplicate"):
        build_exposure(["A"], [h("A", "X", 0.2), h("A", "X", 0.2)], date(2026, 9, 21))
    with pytest.raises(DataError, match="100%"):
        build_exposure(["A"], [h("A", "X", 0.8), h("A", "Y", 0.3)], date(2026, 9, 21))


def test_exact_stock_overlap_requires_complete_same_date_tables():
    from portfolio_lab.exposure import complete_equity_overlaps

    a = h("A", "X", 0.6).model_copy(update={"scope": "full_equity"})
    b = h("B", "X", 0.3).model_copy(update={"scope": "full_equity"})
    c = h("C", "Y", 0.7).model_copy(update={"scope": "full_equity"})
    partial = h("D", "Z", 0.2)
    result = complete_equity_overlaps(["A", "B", "C", "D"], [a, b, c, partial])
    assert len(result) == 3
    assert result[0]["equity_overlap_nav_fraction"] == pytest.approx(0.3)
    assert result[1]["shared_security_count"] == 0
    later = b.model_copy(update={"holding_date": date(2026, 7, 31)})
    assert complete_equity_overlaps(["A", "B"], [a, later]) == []
