"""Deterministic long-only research candidates with explicit cost and feasibility checks."""

import numpy as np
from scipy.optimize import minimize

from .evidence import DataError
from .risk import risk_contributions


def turnover(current, candidate):
    return float(np.abs(np.asarray(candidate) - current).sum() / 2)


def cost_estimates(current, candidate, total_value, bps_scenarios, venues=None):
    delta = np.asarray(candidate) - current
    gross = float(np.abs(delta).sum())
    results = []
    for bps in bps_scenarios:
        fee = gross * bps / 10000
        results.append(
            {"all_in_bps_per_traded_notional": bps, "cost_fraction": fee, "cost_cny": fee * total_value}
        )
    return {
        "one_way_turnover": gross / 2,
        "gross_traded_notional_cny": gross * total_value,
        "actual_cost_cny": None,
        "reason_actual_unknown": "commission, spread, redemption age, lots and order limits unknown",
        "sensitivity": results,
        "changed_products": int((np.abs(delta) > 1e-5).sum()),
        "five_yuan_per_changed_listed_product_scenario": None
        if venues is None
        else float(sum(5 for d, v in zip(delta, venues) if abs(d) > 1e-5 and v == "场内")),
        "ongoing_fees": "already embedded in NAV history; not subtracted a second time",
    }


def solve_candidate(cov, current, codes, constraints, kind="minimum_variance", cost_bps=0, means=None):
    n = len(codes)
    unknown = (
        set(constraints.min_weights)
        | set(constraints.max_weights)
        | {c for group in constraints.groups.values() for c in group}
    ) - set(codes)
    if unknown:
        raise DataError(f"Constraint contains unknown products: {sorted(unknown)}")
    bounds = [(constraints.min_weights.get(c, 0), constraints.max_weights.get(c, 1)) for c in codes]
    if sum(a for a, b in bounds) > 1 + 1e-9 or sum(b for a, b in bounds) < 1 - 1e-9:
        raise DataError("Infeasible weight bounds")
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    if constraints.max_turnover is not None:
        cons.append({"type": "ineq", "fun": lambda w: constraints.max_turnover - turnover(current, w)})
    if constraints.max_volatility is not None:
        cons.append({"type": "ineq", "fun": lambda w: constraints.max_volatility**2 - w @ cov @ w})
    for group, cap in constraints.group_caps.items():
        idx = [codes.index(c) for c in constraints.groups[group]]
        cons.append({"type": "ineq", "fun": lambda w, idx=idx, cap=cap: cap - w[idx].sum()})

    def objective(w):
        variance = float(w @ cov @ w)
        trading = cost_bps / 10000 * np.abs(w - current).sum()
        if kind == "minimum_variance":
            return variance + trading
        if kind == "risk_balance":
            share = risk_contributions(w, cov)["share"]
            return float(np.square(share - 1 / n).sum()) + trading
        if kind == "historical_return_frontier":
            if means is None:
                raise DataError("Historical-return candidate needs explicitly labeled historical means")
            return float(3 * variance - np.asarray(means) @ w + trading)
        raise DataError(f"Unknown objective {kind}")

    starts = [np.asarray(current), np.ones(n) / n]
    results = []
    for start in starts:
        result = minimize(
            objective,
            start,
            bounds=bounds,
            constraints=cons,
            method="SLSQP",
            options={"ftol": 1e-11, "maxiter": 2000},
        )
        if not result.success:
            continue
        w = result.x
        feasible = all(abs(c["fun"](w)) < 1e-6 if c["type"] == "eq" else c["fun"](w) >= -1e-7 for c in cons)
        if feasible and all(a - 1e-7 <= wi <= b + 1e-7 for wi, (a, b) in zip(w, bounds)):
            results.append(result)
    if not results:
        raise DataError(f"No feasible converged solution: {kind}")
    best = min(results, key=lambda r: r.fun)
    w = best.x
    return w, {
        "objective": kind,
        "objective_value": float(best.fun),
        "solver": "SLSQP multistart",
        "success": True,
        "constraints": constraints.model_dump(),
        "cost_bps_assumed": cost_bps,
        "personal_constraints": "none unless explicitly set in configuration",
        "model_domain": "long-only, sum weights = 1, current product universe",
        "forecast_status": "no expected-return forecast; historical frontier is exploratory only",
    }


def leave_one_out(cov, current, codes, cost_bps=0):
    """Refit with each product prohibited, measuring independent efficient-set value."""
    from .models import Constraints

    full, _ = solve_candidate(cov, current, codes, Constraints(), cost_bps=cost_bps)
    base = risk_contributions(full, cov)["volatility"]
    result = []
    for i, code in enumerate(codes):
        w, _ = solve_candidate(cov, current, codes, Constraints(max_weights={code: 0}), cost_bps=cost_bps)
        result.append(
            {
                "code": code,
                "min_vol_without": risk_contributions(w, cov)["volatility"],
                "increase_vs_all_available": risk_contributions(w, cov)["volatility"] - base,
            }
        )
    return result
