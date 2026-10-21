import numpy as np
import pandas as pd
import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.market_model import analyze_market_proxies, fit_market_model, hac_covariance


def sample():
    rng = np.random.default_rng(1709)
    dates = pd.date_range("2024-01-05", periods=80, freq="W-FRI")
    f = pd.DataFrame(rng.normal(0, 0.02, (80, 3)), index=dates, columns=list("ABC"))
    return f, pd.Series(0.001 + f.to_numpy() @ np.array([1.2, -0.3, 0.7]), index=dates)


def test_known_betas_and_variance_reconcile():
    f, y = sample()
    m = fit_market_model(f, y)
    assert [v["estimate"] for v in m["betas"].values()] == pytest.approx([1.2, -0.3, 0.7])
    assert m["weekly_intercept"] == pytest.approx(0.001)
    assert m["r_squared"] == pytest.approx(1)
    assert sum(v["variance_fraction"] for v in m["betas"].values()) + m[
        "residual_variance_fraction"
    ] == pytest.approx(1)


def test_hac_uses_calendar_gaps_and_matches_explicit_double_sum():
    f, y = sample()
    f = f.drop(f.index[[7, 8, 31]])
    x = np.column_stack([np.ones(len(f)), f.to_numpy()])
    residual = np.sin(np.arange(len(f))) * 0.01
    score = x * residual[:, None]
    meat = np.zeros((4, 4))
    for i, a in enumerate(f.index):
        for j, b in enumerate(f.index):
            lag = abs((a - b).days) / 7
            if lag <= 3:
                meat += (1 - lag / 4) * np.outer(score[i], score[j])
    bread = np.linalg.inv(x.T @ x)
    expected = bread @ meat @ bread * len(f) / (len(f) - 4)
    actual = hac_covariance(x, residual, f.index)
    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-14)
    compressed = hac_covariance(x, residual, pd.date_range(f.index[0], periods=len(f), freq="W-FRI"))
    assert not np.allclose(actual, compressed, rtol=1e-4, atol=1e-12)


def test_reject_collinearity_and_misalignment():
    f, y = sample()
    f["B"] = 2 * f.A
    with pytest.raises(DataError, match="collinear"):
        fit_market_model(f, y)
    with pytest.raises(DataError, match="identical"):
        fit_market_model(f, y.iloc[1:])


def test_holdout_training_does_not_see_later_target_changes():
    f, y = sample()
    products = pd.DataFrame({"product": y})
    first = analyze_market_proxies(products, f, {"Current": [1]})
    products.iloc[60:] += 0.05
    second = analyze_market_proxies(products, f, {"Current": [1]})
    a = first["candidates"]["Current"]
    b = second["candidates"]["Current"]
    assert a["holdout"]["training_betas"] == b["holdout"]["training_betas"]
    assert b["holdout"]["rmse"] > a["holdout"]["rmse"]
    assert b["r_squared"] < a["r_squared"]
