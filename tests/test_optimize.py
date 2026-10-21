import numpy as np
import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.models import Constraints
from portfolio_lab.optimize import cost_estimates, solve_candidate, turnover


def test_constrained_solution_and_known_two_asset_case():
    cov = np.diag([0.04, 0.01])
    w0 = np.array([0.5, 0.5])
    w, _ = solve_candidate(cov, w0, ["A", "B"], Constraints())
    assert w == pytest.approx([0.2, 0.8], abs=1e-4)
    w, _ = solve_candidate(cov, w0, ["A", "B"], Constraints(max_weights={"B": 0.65}, max_turnover=0.1))
    assert turnover(w0, w) <= 0.100001
    assert w[1] <= 0.65


def test_infeasible_constraints_fail():
    with pytest.raises(DataError):
        solve_candidate(np.eye(2), [0.5, 0.5], ["A", "B"], Constraints(max_weights={"A": 0.2, "B": 0.2}))


def test_cost_on_both_trade_legs():
    cost = cost_estimates([0.8, 0.2], [0.5, 0.5], 10000, [100])
    assert cost["one_way_turnover"] == pytest.approx(0.3)
    assert cost["sensitivity"][0]["cost_cny"] == pytest.approx(60)
    assert cost["actual_cost_cny"] is None


def test_group_cap_and_volatility_constraints_actually_bind():
    cov = np.diag([0.04, 0.01, 0.02])
    current = np.ones(3) / 3
    constraints = Constraints(groups={"low": ["B", "C"]}, group_caps={"low": 0.6}, max_volatility=0.11)
    w, _ = solve_candidate(cov, current, ["A", "B", "C"], constraints)
    assert w[1] + w[2] <= 0.600001
    assert np.sqrt(w @ cov @ w) <= 0.110001
    with pytest.raises(DataError):
        solve_candidate(cov, current, ["A", "B", "C"], Constraints(max_volatility=0.001))


def test_invalid_overwritten_minimum_and_duplicate_group_rejected():
    with pytest.raises(ValueError):
        Constraints(min_weights={"A": -0.1}, max_weights={"A": 0.5})
    with pytest.raises(ValueError):
        Constraints(groups={"x": ["A", "A"]}, group_caps={"x": 0.5})
