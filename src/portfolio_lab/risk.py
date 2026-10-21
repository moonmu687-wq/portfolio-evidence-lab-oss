"""Risk formulas, additive contributions and uncertainty, independent of rendering."""

import numpy as np
from sklearn.covariance import LedoitWolf

from .evidence import DataError


def covariance(returns, periods=52):
    x = np.asarray(returns, dtype=float)
    if x.ndim != 2 or len(x) < 2 or not np.isfinite(x).all():
        raise DataError("Covariance requires finite complete observations")
    model = LedoitWolf().fit(x)
    cov = model.covariance_ * periods
    if np.linalg.eigvalsh(cov).min() < -1e-10:
        raise DataError("Covariance is not PSD")
    return cov, float(model.shrinkage_)


def validate_weights(weights, n):
    w = np.asarray(weights, dtype=float)
    if w.shape != (n,) or not np.isfinite(w).all() or abs(w.sum() - 1) > 1e-7 or w.min() < -1e-8:
        raise DataError("Weights must be finite, long-only and sum to one")
    return w


def risk_contributions(weights, cov):
    w = validate_weights(weights, len(cov))
    variance = float(w @ cov @ w)
    vol = float(np.sqrt(max(variance, 0)))
    if vol <= 1e-12:
        return {
            "volatility": vol,
            "marginal": np.zeros(len(w)),
            "component": np.zeros(len(w)),
            "share": np.zeros(len(w)),
        }
    marginal = cov @ w / vol
    component = w * marginal
    if not np.isclose(component.sum(), vol, rtol=1e-8):
        raise DataError("Euler risk contributions fail reconciliation")
    return {"volatility": vol, "marginal": marginal, "component": component, "share": component / vol}


def max_drawdown(r):
    wealth = np.r_[1.0, np.cumprod(1 + np.asarray(r))]
    return float(np.min(wealth / np.maximum.accumulate(wealth) - 1))


def historical_es(r, alpha=0.95):
    """Integral of empirical loss quantile, fractional boundary mass; no annualization."""
    losses = np.sort(-np.asarray(r, dtype=float))[::-1]
    mass = len(losses) * (1 - alpha)
    k = int(np.floor(mass))
    fraction = mass - k
    es = (losses[:k].sum() + (losses[k] * fraction if fraction > 1e-12 else 0)) / mass
    return {
        "cvar": float(es),
        "tail_equivalent_observations": float(mass),
        "reliable_tail_sample": mass >= 10,
        "alpha": alpha,
        "horizon": "one week",
    }


def metrics(returns, weights, cov, path_returns=None):
    x = np.asarray(returns, dtype=float)
    w = validate_weights(weights, x.shape[1])
    r = x @ w
    path = x if path_returns is None else np.asarray(path_returns, dtype=float)
    path_r = path @ w
    buy_hold = np.cumprod(1 + path, axis=0) @ w
    bh_returns = np.diff(np.r_[1.0, buy_hold]) / np.r_[1.0, buy_hold][:-1]
    rc = risk_contributions(w, cov)
    return {
        "annual_volatility": rc["volatility"],
        "sample_annual_volatility": float(r.std(ddof=1) * np.sqrt(52)),
        "observed_period_compound_return": float(np.prod(1 + path_r) - 1),
        "annualized_arithmetic_mean_historical": float(r.mean() * 52),
        "observed_endpoint_rebalanced_max_drawdown": max_drawdown(path_r),
        "buy_hold_max_drawdown": max_drawdown(bh_returns),
        "buy_hold_compound_return": float(buy_hold[-1] - 1),
        "weekly_cvar95": historical_es(r),
        "weekly_cvar90": historical_es(r, 0.90),
        "product_hhi": float(w @ w),
        "effective_product_count": float(1 / (w @ w)),
        "historical_path_label": "counterfactual rebalanced at observed endpoints; missing calendar intervals bridged only for paths, never covariance; not account performance",
    }


def funded_shifts(weights, cov, step=0.01):
    w = np.asarray(weights)
    current = risk_contributions(w, cov)["volatility"]
    out = []
    for i in range(len(w)):
        if w[i] >= 1 - step:
            out.append(None)
            continue
        changed = w * (1 - step / (1 - w[i]))
        changed[i] = w[i] + step
        out.append(float(risk_contributions(changed, cov)["volatility"] - current))
    return out


def block_bootstrap(returns, w0, w1, samples=500, seed=0, block=4):
    x = np.asarray(returns)
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(samples):
        starts = rng.integers(0, len(x), size=int(np.ceil(len(x) / block)))
        idx = np.concatenate([(s + np.arange(block)) % len(x) for s in starts])[: len(x)]
        xb = x[idx]
        values.append(float((xb @ w1).std(ddof=1) - (xb @ w0).std(ddof=1)) * np.sqrt(52))
    return {
        "annual_vol_difference_95_interval": np.quantile(values, [0.025, 0.975]).tolist(),
        "probability_lower_vol_descriptive": float(np.mean(np.array(values) < 0)),
        "samples": samples,
        "block_weeks": block,
        "selection_bias": "weights fixed after fitting; not proof of future superiority",
    }


def historical_attribution(returns, weights, path_returns, alpha=0.95):
    """Additive empirical ES and buy-hold peak-to-trough loss, never forecasts."""
    x = np.asarray(returns, dtype=float)
    w = validate_weights(weights, x.shape[1])
    losses = -(x @ w)
    mass = len(x) * (1 - alpha)
    tail = np.zeros(len(x))
    remaining = mass
    for loss in np.unique(losses)[::-1]:
        idx = np.flatnonzero(losses == loss)
        assigned = min(remaining, len(idx))
        tail[idx] = assigned / len(idx)
        remaining -= assigned
        if remaining <= 1e-12:
            break
    es_components = -(tail @ x) * w / mass
    levels = np.vstack([np.ones(x.shape[1]), np.cumprod(1 + np.asarray(path_returns), axis=0)])
    wealth = levels @ w
    trough = int(np.argmin(wealth / np.maximum.accumulate(wealth) - 1))
    peak = int(np.argmax(wealth[: trough + 1]))
    dd_components = w * (levels[trough] - levels[peak]) / wealth[peak]
    return {
        "weekly_cvar95_components": es_components.tolist(),
        "annualized_arithmetic_return_components": (x.mean(axis=0) * 52 * w).tolist(),
        "buy_hold_max_drawdown_components": dd_components.tolist(),
        "drawdown_peak_endpoint_index": peak,
        "drawdown_trough_endpoint_index": trough,
        "label": "fixed initial buy-hold drawdown; arithmetic historical return; empirical tail attribution",
    }


def net_cost_path(path_returns, weights, current, bps):
    """Proportional all-in fee scenario; rebalance after each observed endpoint except last."""
    x = np.asarray(path_returns)
    w = validate_weights(weights, x.shape[1])
    rate = bps / 10000
    initial = np.abs(w - np.asarray(current)).sum() * rate
    wealth = 1 - initial
    fees = initial
    for i, row in enumerate(x):
        growth = 1 + float(row @ w)
        wealth *= growth
        if i < len(x) - 1:
            drift = w * (1 + row) / growth
            fee = rate * np.abs(w - drift).sum()
            fees += wealth * fee
            wealth *= 1 - fee
    return {
        "bps_per_traded_notional": bps,
        "net_compound_return": float(wealth - 1),
        "fees_per_initial_capital": float(fees),
        "label": "proportional fee scenario with endpoint rebalancing; excludes lots, minimum fees and execution basis",
    }
