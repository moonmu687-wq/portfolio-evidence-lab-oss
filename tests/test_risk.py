import numpy as np
import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.risk import covariance, funded_shifts, historical_es, max_drawdown, risk_contributions


def test_euler_and_finite_difference():
    cov = np.array([[0.04, 0.006], [0.006, 0.01]])
    w = np.array([0.4, 0.6])
    r = risk_contributions(w, cov)
    assert r["component"].sum() == pytest.approx(r["volatility"])
    eps = 1e-6
    derivative = (np.sqrt((w + [eps, -eps]) @ cov @ (w + [eps, -eps])) - r["volatility"]) / eps
    assert derivative == pytest.approx(r["marginal"][0] - r["marginal"][1], rel=1e-4)
    shift = funded_shifts(w, cov, 0.01)[0]
    assert shift == pytest.approx(
        np.sqrt(np.array([0.41, 0.59]) @ cov @ np.array([0.41, 0.59])) - r["volatility"]
    )


def test_initial_loss_is_a_drawdown():
    assert max_drawdown([-0.20, 0.10]) == pytest.approx(-0.20)


def test_es_uses_fractional_tail_mass():
    # 2.5 worst outcomes: losses 10,9 and half of 8 percentage points.
    r = -np.arange(1, 11) / 100
    assert historical_es(r, 0.75)["cvar"] == pytest.approx((0.10 + 0.09 + 0.5 * 0.08) / 2.5)


def test_no_pairwise_covariance_or_nan():
    with pytest.raises(DataError):
        covariance([[0.1, np.nan], [0.2, 0.1]])
    c, _ = covariance(np.random.default_rng(1).normal(size=(40, 14)))
    assert np.linalg.eigvalsh(c).min() >= 0


def test_cash_zero_risk():
    r = risk_contributions([0, 1], np.diag([0.04, 0]))
    assert r["volatility"] == 0
