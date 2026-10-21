"""Descriptive CNY market-proxy sensitivities; never an optimizer or causal model."""

import numpy as np
import pandas as pd

from .evidence import DataError


def hac_covariance(design, residual, dates, lags=3):
    """Bartlett sandwich with n/(n-k) correction and actual calendar-week lags.

    Missing weeks contribute no scores; observations separated by a holiday gap
    must not become adjacent weeks. No missing return is imputed.
    """
    score = design * residual[:, None]
    meat = score.T @ score
    lookup = {d: i for i, d in enumerate(dates)}
    for lag in range(1, lags + 1):
        pairs = [
            (i, lookup[d - pd.Timedelta(weeks=lag)])
            for i, d in enumerate(dates)
            if d - pd.Timedelta(weeks=lag) in lookup
        ]
        if pairs:
            a, b = np.asarray(pairs).T
            cross = score[a].T @ score[b]
            meat += (1 - lag / (lags + 1)) * (cross + cross.T)
    bread = np.linalg.inv(design.T @ design)
    n, k = design.shape
    return bread @ meat @ bread * n / (n - k)


def fit_market_model(factors, target, lags=3):
    if not factors.index.equals(target.index) or not isinstance(factors.index, pd.DatetimeIndex):
        raise DataError("Market model requires identical dated observations")
    dates = factors.index
    if dates.has_duplicates or not dates.is_monotonic_increasing or not (dates.dayofweek == 4).all():
        raise DataError("Market model requires unique ordered Friday endpoints")
    f, y = factors.to_numpy(dtype=float), target.to_numpy(dtype=float)
    n, k = f.shape
    if n < max(26, 5 * (k + 1)) or not np.isfinite(f).all() or not np.isfinite(y).all():
        raise DataError("Market model sample insufficient or nonfinite")
    if np.any(f.std(axis=0) < 1e-12) or y.std() < 1e-12:
        raise DataError("Constant market model series")
    z = np.column_stack([np.ones(n), (f - f.mean(axis=0)) / f.std(axis=0)])
    condition = float(np.linalg.cond(z))
    if np.linalg.matrix_rank(z) != k + 1 or condition > 100:
        raise DataError("Market proxies rank deficient or too collinear")
    x = np.column_stack([np.ones(n), f])
    beta = np.linalg.lstsq(x, y, rcond=None)[0]
    residual = y - x @ beta
    se = np.sqrt(np.maximum(np.diag(hac_covariance(x, residual, dates, lags)), 0))
    variance = float(np.var(y, ddof=1))
    explained = beta[1:] * (np.atleast_2d(np.cov(f, rowvar=False)) @ beta[1:])
    residual_fraction = float(np.var(residual, ddof=1) / variance)
    if abs(float(explained.sum()) / variance + residual_fraction - 1) > 1e-8:
        raise DataError("Market model variance decomposition failed")
    return {
        "n": n,
        "start": str(dates[0].date()),
        "end": str(dates[-1].date()),
        "standardized_condition_number": condition,
        "r_squared": 1 - residual_fraction,
        "adjusted_r_squared": 1 - residual_fraction * (n - 1) / (n - k - 1),
        "weekly_intercept": float(beta[0]),
        "intercept_hac_se": float(se[0]),
        "residual_variance_fraction": residual_fraction,
        "sample_annual_volatility": float(np.sqrt(variance * 52)),
        "betas": {
            name: {
                "estimate": float(beta[i + 1]),
                "hac_se": float(se[i + 1]),
                "ci95_normal": [float(beta[i + 1] - 1.96 * se[i + 1]), float(beta[i + 1] + 1.96 * se[i + 1])],
                "variance_fraction": float(explained[i] / variance),
            }
            for i, name in enumerate(factors.columns)
        },
    }


def analyze_market_proxies(product_returns, proxy_returns, candidates):
    common = product_returns.index.intersection(proxy_returns.index).sort_values()
    if len(common) < 40:
        raise DataError("Fewer than 40 common portfolio/market-proxy weekly returns")
    f, r = proxy_returns.loc[common], product_returns.loc[common]
    if set(f.columns) & set(r.columns):
        raise DataError("Proxy and portfolio product identities overlap")
    targets = {str(code): r[code] for code in r.columns}
    targets.update(
        {name: pd.Series(r.to_numpy() @ np.asarray(w), index=common) for name, w in candidates.items()}
    )
    fitted = {}
    split = max(26, int(len(common) * 0.65))
    for name, y in targets.items():
        full = fit_market_model(f, y)
        train = fit_market_model(f.iloc[:split], y.iloc[:split])
        prediction = train["weekly_intercept"] + f.iloc[split:].to_numpy() @ np.array(
            [train["betas"][c]["estimate"] for c in f.columns]
        )
        actual = y.iloc[split:].to_numpy()
        error = float(np.sum((actual - prediction) ** 2))
        baseline = float(np.sum((actual - y.iloc[:split].mean()) ** 2))
        full["holdout"] = {
            "train_end": train["end"],
            "test_start": str(common[split].date()),
            "test_end": str(common[-1].date()),
            "n": len(actual),
            "rmse": float(np.sqrt(error / len(actual))),
            "r_squared_vs_training_mean": 1 - error / baseline if baseline > 1e-20 else None,
            "training_betas": train["betas"],
            "interpretation": "Coefficient stability diagnostic; contemporaneous test factors. Candidate weights use full sample: NOT a strategy backtest or return forecast",
        }
        fitted[name] = full
    return {
        "method": "OLS raw weekly CNY returns with intercept; 3 funded market proxies",
        "uncertainty": "Newey-West Bartlett HAC, 3 calendar-week lags, n/(n-k) correction; approximate normal 95% intervals, not exact small-sample coverage",
        "variance_basis": "Unshrunk sample covariance on the same aligned observations; correlated factor allocations can be negative; sums with residual to one",
        "dates": common.strftime("%Y-%m-%d").tolist(),
        "portfolio_weeks_excluded": product_returns.index.difference(common).strftime("%Y-%m-%d").tolist(),
        "factor_correlation": f.corr().to_dict(),
        "products": {c: fitted[c] for c in r.columns},
        "candidates": {c: fitted[c] for c in candidates},
        "limitations": [
            "Partial associations conditional on the other proxies; no causal, holdings or pure economic factor claim",
            "US and gold CNY proxies contain currency effects; FX, technology, size, value and momentum are not separately identified",
            "Fund tracking, fees and nonsynchronous market closes affect coefficients; ETF execution prices excluded",
            "Short common history and selected proxy set make betas and intervals unstable; excluded markets remain in residual",
            "Intercept is not risk-adjusted alpha: no risk-free series or expected-return model",
            "Diagnostics only: no change to portfolio covariance, candidate optimizer or verified holdings coverage",
        ],
    }
