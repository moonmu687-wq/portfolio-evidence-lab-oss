"""Look-through conserves mass and retains unknown residuals at each fund node."""

from collections import defaultdict
from datetime import date
from itertools import combinations

import numpy as np
import pandas as pd

from .evidence import DataError


def complete_equity_overlaps(codes, holdings):
    """Exact direct-equity overlap only for two complete, same-date stock tables.

    This neither renormalizes stocks to 100% NAV nor claims that the residual
    assets, derivatives or shared factor risks are absent.
    """
    by_fund = defaultdict(list)
    for h in holdings:
        if h.fund in codes and h.kind == "equity":
            by_fund[h.fund].append(h)
    complete = {
        f: rows
        for f, rows in by_fund.items()
        if rows and all(h.scope == "full_equity" for h in rows) and len({h.holding_date for h in rows}) == 1
    }
    results = []
    for a, b in combinations(codes, 2):
        if a not in complete or b not in complete:
            continue
        if complete[a][0].holding_date != complete[b][0].holding_date:
            continue
        wa = {h.security: h.weight for h in complete[a]}
        wb = {h.security: h.weight for h in complete[b]}
        shared = sorted(k for k in wa.keys() & wb.keys() if min(wa[k], wb[k]) > 0)
        results.append(
            {
                "a": a,
                "b": b,
                "holding_date": str(complete[a][0].holding_date),
                "equity_overlap_nav_fraction": sum(min(wa[k], wb[k]) for k in shared),
                "shared_security_count": len(shared),
                "shared_securities": shared,
                "scope": "Complete direct equity tables only; excludes non-equity and derivative exposure",
            }
        )
    return results


def build_exposure(codes, holdings, as_of: date, max_age_days=120):
    by_fund = defaultdict(list)
    for h in holdings:
        if h.holding_date > as_of or (h.published_date and h.published_date > as_of):
            raise DataError(f"Look-ahead holding: {h.source_id}")
        by_fund[h.fund].append(h)
    flags = []
    registry = {}
    for fund, items in by_fund.items():
        if len({h.holding_date for h in items}) != 1:
            raise DataError(f"Mixed disclosure dates within {fund}")
        if len({h.security for h in items}) != len(items):
            raise DataError(f"Duplicate securities within {fund}")
        if sum(h.weight for h in items) > 1.0001:
            raise DataError(
                f"Gross holding weights >100% in {fund}; leverage needs explicit balance-sheet model"
            )
        for h in items:
            if h.security in registry:
                prior = registry[h.security]
                for attr in ["region", "currency", "sector"]:
                    if getattr(h, attr) and getattr(prior, attr) and getattr(h, attr) != getattr(prior, attr):
                        raise DataError(f"Conflicting security classification: {h.security}/{attr}")
            registry[h.security] = h

    def traverse(fund, path):
        if fund in path:
            raise DataError(f"Fund look-through cycle: {' -> '.join(path + [fund])}")
        result = defaultdict(float)
        items = by_fund.get(fund, [])
        total = 0.0
        for h in items:
            total += h.weight
            if (as_of - h.holding_date).days > max_age_days:
                flags.append(f"{fund}: disclosure stale ({h.holding_date})")
            if h.published_date is None:
                flags.append(f"{fund}: publication date unverified; unsuitable for point-in-time backtest")
            if h.kind == "fund" and h.security in by_fund:
                for security, weight in traverse(h.security, path + [fund]).items():
                    result[security] += h.weight * weight
            elif h.kind == "fund":
                result["UNRESOLVED_FUND:" + h.security] += h.weight
            else:
                result[h.security] += h.weight
        residual = max(0, 1 - total)
        result["UNKNOWN:" + fund] += residual
        return result

    records = {code: traverse(code, []) for code in codes}
    matrix = pd.DataFrame.from_dict(records, orient="index").reindex(index=codes).fillna(0.0)
    if not np.allclose(matrix.sum(axis=1), 1.0, atol=1e-4):
        raise DataError("Look-through mass does not reconcile")
    known = [s for s in matrix if not s.startswith(("UNKNOWN:", "UNRESOLVED_FUND:"))]
    coverage = matrix[known].sum(axis=1)
    lower = pd.DataFrame(0.0, index=codes, columns=codes)
    upper = lower.copy()
    for a in codes:
        for b in codes:
            lo = float(np.minimum(matrix.loc[a, known], matrix.loc[b, known]).sum())
            lower.loc[a, b] = lo
            upper.loc[a, b] = min(1.0, lo + (1 - coverage[a]) + (1 - coverage[b]))
    return matrix, coverage, lower, upper, registry, sorted(set(flags))


def aggregate_exposure(matrix, weights, registry):
    if not isinstance(weights, (pd.Series, dict)):
        raise DataError("Exposure aggregation requires weights labeled by fund code")
    weights = pd.Series(weights, dtype=float)
    if not weights.index.is_unique or set(weights.index) != set(matrix.index):
        raise DataError("Exposure weight identities do not match matrix")
    total = matrix.mul(weights.reindex(matrix.index), axis=0).sum(axis=0)
    dimensions = {}
    for attr in ["sector", "region", "currency", "kind"]:
        groups = defaultdict(float)
        for sec, weight in total.items():
            h = registry.get(sec)
            label = getattr(h, attr, None) if h else None
            groups[label or "UNKNOWN"] += float(weight)
        dimensions[attr] = dict(sorted(groups.items(), key=lambda x: -x[1]))
    markets = defaultdict(float)
    for sec, weight in total.items():
        prefix = sec.split(":")[0]
        markets[prefix if prefix in {"CN", "HK", "US", "DE", "JP", "KR", "TW"} else "UNKNOWN"] += float(
            weight
        )
    dimensions["listing_market"] = dict(sorted(markets.items(), key=lambda x: -x[1]))
    known = total[[not s.startswith(("UNKNOWN:", "UNRESOLVED_FUND:")) for s in total.index]]
    return {
        "security_exposure": total.sort_values(ascending=False).to_dict(),
        "dimensions": dimensions,
        "resolved_nav_fraction": float(known.sum()),
        "known_security_hhi_lower_bound": float(known @ known),
        "coverage_label": "identified NAV share; residual is not assumed cash; reporting dates are historical",
    }
