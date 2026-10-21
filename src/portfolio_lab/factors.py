"""Statistical factors are kept separate from economic factor and holdings classifications."""

import numpy as np


def statistical_factors(returns, weights, count=3):
    x = np.asarray(returns, dtype=float)
    z = x - x.mean(axis=0)
    _, singular, v = np.linalg.svd(z, full_matrices=False)
    k = min(count, len(v))
    eigen = singular**2 / (len(x) - 1)
    load = v[:k].T
    for i in range(k):
        anchor = np.argmax(np.abs(load[:, i]))
        if load[anchor, i] < 0:
            load[:, i] *= -1
    return {
        "type": "PCA of centered weekly product returns, covariance basis",
        "explained_variance_ratio": (eigen[:k] / eigen.sum()).tolist(),
        "loadings": load.tolist(),
        "portfolio_projection": (np.asarray(weights) @ load).tolist(),
        "economic_factor_betas": None,
        "limitation": "PCA is sample-dependent and is not market/size/value/momentum or currency beta",
    }
