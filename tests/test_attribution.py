import numpy as np
import pytest

from portfolio_lab.risk import historical_attribution, historical_es, max_drawdown, net_cost_path


def test_tail_and_drawdown_reconcile_including_initial_peak_and_ties():
    x = np.array([[-0.1, -0.2], [0.05, 0.1], [-0.1, -0.2], [0.2, 0.1]])
    w = np.array([0.3, 0.7])
    a = historical_attribution(x, w, x)
    assert sum(a["weekly_cvar95_components"]) == pytest.approx(historical_es(x @ w)["cvar"])
    wealth = np.cumprod(1 + x, axis=0) @ w
    r = np.diff(np.r_[1, wealth]) / np.r_[1, wealth][:-1]
    assert sum(a["buy_hold_max_drawdown_components"]) == pytest.approx(max_drawdown(r))
    assert sum(a["annualized_arithmetic_return_components"]) == pytest.approx((x @ w).mean() * 52)


def test_zero_cost_path_matches_gross_and_cost_reduces_wealth():
    x = np.array([[0.1, -0.1], [-0.1, 0.1], [0.1, 0.1]])
    zero = net_cost_path(x, [0.5, 0.5], [1, 0], 0)
    paid = net_cost_path(x, [0.5, 0.5], [1, 0], 100)
    assert zero["net_compound_return"] == pytest.approx(0.1)
    assert paid["net_compound_return"] < zero["net_compound_return"]
    assert paid["fees_per_initial_capital"] > 0.01
