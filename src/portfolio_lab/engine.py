"""End-to-end offline research and reproducible artifact production."""

import hashlib
import importlib.metadata
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .evidence import DataError, archive_inputs, input_manifest, read_json, verify_manifest, write_json
from .exposure import aggregate_exposure, build_exposure, complete_equity_overlaps
from .factors import statistical_factors
from .models import Holding, ResearchConfig
from .optimize import cost_estimates, leave_one_out, solve_candidate
from .providers import load_nav
from .returns import weekly_panel
from .risk import (
    block_bootstrap,
    covariance,
    funded_shifts,
    historical_attribution,
    metrics,
    net_cost_path,
    risk_contributions,
)
from .ssot import parse_snapshot


def run_research(root: Path, config_path: Path, snapshot_path: Path, holdings_path: Path):
    config = ResearchConfig.model_validate(read_json(config_path))
    normalization = root / "private/normalization_manifest.json"
    if normalization.exists():
        norm_manifest = read_json(normalization)
        verify_manifest(norm_manifest["inputs"], root)
        verify_manifest(norm_manifest["outputs"], root)
    snapshot_bundle = read_json(snapshot_path)
    positions, flags = parse_snapshot(snapshot_bundle)
    snapshot_update = None
    snapshot_evidence = []
    changes_path = snapshot_path.with_suffix(".changes.json")
    if changes_path.exists():
        from .snapshot_update import relative_input, snapshot_changes

        recorded = read_json(changes_path)
        previous_snapshot = root / relative_input(root, recorded["previous_snapshot"])
        previous_config = root / relative_input(root, recorded["previous_config"])
        expected = snapshot_changes(read_json(previous_snapshot), snapshot_bundle)
        if {
            k: v for k, v in recorded.items() if k not in {"previous_snapshot", "previous_config"}
        } != expected:
            raise DataError("Snapshot change ledger disagrees with original snapshots")
        snapshot_update = {**expected, "source_retrieved_at": snapshot_bundle.get("retrieved_at")}
        snapshot_evidence = [changes_path, previous_snapshot, previous_config]
    if (root / "private/disclosure_qa.json").exists():
        flags += read_json(root / "private/disclosure_qa.json").get("gaps", [])
    if positions[0].as_of != config.as_of:
        raise DataError("SSOT date differs from research as_of; explicitly select the correct snapshot")
    codes = [p.code for p in positions]
    total = sum(p.market_value for p in positions)
    current = np.array([p.market_value / total for p in positions])
    local_nav = root / "private/nav.csv"
    if local_nav.exists():
        from .csv_inputs import load_csv_nav

        nav, nav_files = load_csv_nav(local_nav, codes)
        nav_source = "Local CSV; CNY total-return basis declared by the data supplier"
    else:
        nav, nav_files = load_nav(root / "private/raw/wind", codes)
        nav_source = "Versioned provider evidence; see input manifest and cross-validation results"
    issuer_qa = {}
    market_catalog = root / "private/market_catalog.json"
    if market_catalog.exists():
        catalog = read_json(market_catalog)
        nav_files.append(market_catalog)
        for code, entry in catalog.items():
            if code not in codes:
                continue
            if entry.get("provider", "efunds") == "efunds":
                from .official_efunds import load_issuer_nav
            elif entry.get("provider") == "fsfund":
                from .official_fsfund import load_issuer_nav
            elif entry.get("provider") == "eastmoney":
                from .public_nav import load_issuer_nav
            else:
                raise DataError("Unknown issuer NAV adapter")
            reference = nav.loc[nav.code == code]
            issuer, paths, qa = load_issuer_nav(root, catalog, code, reference)
            nav = pd.concat([nav.loc[nav.code != code], issuer], ignore_index=True)
            nav_files += paths + [root / p for p in entry.get("evidence_paths", [])]
            issuer_qa[code] = qa
    nav = nav[(nav.date >= pd.Timestamp(config.start)) & (nav.date <= pd.Timestamp(config.as_of))]
    for code in codes:
        latest = nav.loc[nav.code == code, "date"].max()
        if pd.isna(latest) or (pd.Timestamp(config.as_of) - latest).days > config.max_nav_age_days:
            raise DataError(f"{code} NAV stale at research date")
    returns, levels, dates, ages, alignment = weekly_panel(
        nav, codes, config.start, config.as_of, config.max_nav_age_days, config.min_observations
    )
    # Levels with gaps bridge actual capital growth for path metrics only.
    path_returns = levels.dropna().pct_change(fill_method=None).dropna()
    holdings = [Holding.model_validate(d) for d in read_json(holdings_path)]
    matrix, coverage, lower, upper, registry, exposure_flags = build_exposure(
        codes, holdings, config.as_of, config.disclosure_max_age_days
    )
    flags += exposure_flags
    cov, shrinkage = covariance(returns)
    candidates = {"Current": current}
    objectives = {}
    for label, kind, cost in [
        ("Minimum variance", "minimum_variance", 0),
        ("Risk balance", "risk_balance", 0),
        ("Cost-aware risk", "minimum_variance", config.optimization_cost_bps),
        ("Historical-return stress", "historical_return_frontier", config.optimization_cost_bps),
    ]:
        w, meta = solve_candidate(
            cov, current, codes, config.constraints, kind, cost, returns.mean().to_numpy() * 52
        )
        candidates[label] = w
        objectives[label] = meta
    split = max(26, int(len(returns) * 0.65))
    train, test = returns.iloc[:split], returns.iloc[split:]
    train_cov, _ = covariance(train)
    test_cov, _ = covariance(test)
    evaluation = {}
    from .derivatives import aggregate_derivatives

    derivative_path = root / "private/derivatives.json"
    derivatives = read_json(derivative_path) if derivative_path.exists() else []
    if any(
        x["holding_date"] > str(config.as_of) or x["published_date"] > str(config.as_of) for x in derivatives
    ):
        raise DataError("Look-ahead derivative disclosure")
    for label, w in candidates.items():
        m = metrics(returns, w, cov, path_returns)
        rc = risk_contributions(w, cov)
        evaluation[label] = {
            "derivative_exposure": aggregate_derivatives(derivatives, dict(zip(codes, map(float, w)))),
            "weights": dict(zip(codes, map(float, w))),
            "metrics": m,
            "historical_attribution": historical_attribution(returns, w, path_returns),
            "net_cost_path_scenarios": [
                net_cost_path(path_returns, w, current, b) for b in config.cost_bps_scenarios
            ],
            "risk_contributions": {
                c: {
                    "marginal_vol": float(rc["marginal"][i]),
                    "component_vol": float(rc["component"][i]),
                    "risk_share": float(rc["share"][i]),
                }
                for i, c in enumerate(codes)
            },
            "exposure": aggregate_exposure(matrix, pd.Series(w, index=codes), registry),
            "cost": cost_estimates(
                current, w, total, config.cost_bps_scenarios, [p.venue for p in positions]
            ),
            "bootstrap": block_bootstrap(returns, current, w, config.bootstrap_samples, config.seed),
        }
        # Fit only earlier returns. Test path begins after final training endpoint.
        if label == "Current":
            test_w = current
        else:
            o = objectives[label]
            test_w, _ = solve_candidate(
                train_cov,
                current,
                codes,
                config.constraints,
                o["objective"],
                o["cost_bps_assumed"],
                train.mean().to_numpy() * 52,
            )
        test_path = path_returns[path_returns.index > train.index[-1]]
        evaluation[label]["holdout"] = {
            "weights_trained_before_test": dict(zip(codes, map(float, test_w))),
            "train_end": str(train.index[-1].date()),
            "test_start": str(test.index[0].date()),
            "test_end": str(test.index[-1].date()),
            "test_observations": len(test),
            "metrics": metrics(test, test_w, test_cov, test_path),
            "cost": cost_estimates(current, test_w, total, config.cost_bps_scenarios),
            "limitation": "single chronological holdout; snapshot product universe and current benchmark weights selected ex post",
        }
    shifts = funded_shifts(current, cov)
    rc = risk_contributions(current, cov)
    position_analysis = []
    for i, p in enumerate(positions):
        if rc["share"][i] > current[i] * 1.2:
            role = "风险份额高于资金份额；增加仓位会强化现有波动来源"
        elif rc["share"][i] < current[i] * 0.8:
            role = "样本内风险份额低于资金份额；有分散作用，但不代表预期收益更高"
        else:
            role = "风险份额接近资金份额；需结合底层重叠和投资判断解释持有理由"
        position_analysis.append(
            {
                **p.model_dump(mode="json"),
                "weight": float(current[i]),
                "identified_nav_fraction": float(coverage[p.code]),
                "risk_share": float(rc["share"][i]),
                "funded_plus_1pp_vol_delta": shifts[i],
                "model_interpretation": role,
                "user_rationale": p.user_thesis,
                "user_rationale_status": "unknown" if not p.user_thesis else "user-supplied",
            }
        )
    overlap = []
    correlation = returns.corr()
    for i, a in enumerate(codes):
        for b in codes[i + 1 :]:
            overlap.append(
                {
                    "a": a,
                    "b": b,
                    "overlap_lower": float(lower.loc[a, b]),
                    "overlap_upper_conservative": float(upper.loc[a, b]),
                    "correlation": float(correlation.loc[a, b]),
                }
            )
    overlap.sort(key=lambda r: r["overlap_lower"], reverse=True)
    equity_overlap = complete_equity_overlaps(codes, holdings)
    for row in equity_overlap:
        row["return_correlation"] = float(correlation.loc[row["a"], row["b"]])
    paths = [config_path, snapshot_path, holdings_path] + nav_files + snapshot_evidence
    market_model = None
    proxy_frames = []
    proxy_catalog = root / "private/market_proxies.json"
    if proxy_catalog.exists():
        from .market_model import analyze_market_proxies
        from .market_proxies import DEFINITIONS, load_proxies

        proxy_nav, proxy_qa, proxy_paths = load_proxies(root, proxy_catalog, config.start, config.as_of)
        proxy_returns, proxy_levels, proxy_dates, proxy_ages, proxy_alignment = weekly_panel(
            proxy_nav,
            list(DEFINITIONS),
            config.start,
            config.as_of,
            config.max_nav_age_days,
            config.min_observations,
        )
        market_model = analyze_market_proxies(returns, proxy_returns, candidates)
        market_model.update(source_qa=proxy_qa, alignment=proxy_alignment)
        paths.extend(proxy_paths)
        proxy_frames = [
            ("market_proxy_daily_nav", proxy_nav.set_index(["code", "date"])),
            ("market_proxy_weekly_returns", proxy_returns),
            ("market_proxy_levels", proxy_levels),
            ("market_proxy_actual_dates", proxy_dates),
            ("market_proxy_age_days", proxy_ages),
        ]
    supplemental = []
    supplemental_catalog = root / "private/supplemental_baskets.json"
    if supplemental_catalog.exists():
        from .official_ishares import estimate_nested, parse_basket

        paths.append(supplemental_catalog)
        baskets = []
        for spec in read_json(supplemental_catalog):
            source = root / spec["path"]
            collection_manifest = root / spec["manifest"]
            collection_inputs = read_json(collection_manifest)["inputs"]
            verify_manifest(collection_inputs, collection_manifest.parent)
            collection_paths = [collection_manifest.parent / p["path"] for p in collection_inputs]
            if source.resolve() not in {p.resolve() for p in collection_paths}:
                raise DataError("Supplemental source is absent from its acquisition manifest")
            baskets.append(parse_basket(read_json(source), spec["ticker"], spec["holding_date"]))
            paths.extend([collection_manifest] + collection_paths)
        supplemental = estimate_nested(
            baskets,
            holdings,
            {label: dict(zip(codes, map(float, w))) for label, w in candidates.items()},
            config.as_of,
        )
    if derivative_path.exists():
        paths.append(derivative_path)
    # Include all evidence underlying the normalized look-through and classifications.
    paths += list((root / "private/raw/reports").glob("*.pdf"))
    paths += [p for p in (root / "private/raw/wind").glob("*.json") if "nav-" not in p.name]
    if (root / "private/disclosure_qa.json").exists():
        paths.append(root / "private/disclosure_qa.json")
    if normalization.exists():
        paths.append(normalization)
        paths.extend(root / p["path"] for p in norm_manifest["inputs"])
    inputs = input_manifest(paths, root)
    code_files = sorted((root / "src").rglob("*.py")) + [root / "pyproject.toml"]
    if (root / "requirements.lock").exists():
        code_files.append(root / "requirements.lock")
    code_manifest = input_manifest(code_files, root)
    code_digest = hashlib.sha256(json.dumps(code_manifest, sort_keys=True).encode()).hexdigest()
    packages = {
        p: importlib.metadata.version(p)
        for p in ["numpy", "pandas", "scipy", "scikit-learn", "pydantic", "pypdf"]
    }
    environment = {"python": platform.python_version(), "packages": packages}
    run_id = hashlib.sha256(
        json.dumps([inputs, code_digest, environment], sort_keys=True).encode()
    ).hexdigest()[:16]
    out = root / "private/runs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    missing_products = [c for c in codes if coverage[c] == 0]
    flags += [
        "账户交易份额、费用、持有天数及申赎限制未知；候选不是可直接执行订单",
        "共同历史有限，尾部样本不足；CVaR为描述性估计，不能推断极端损失上限",
        "基金净值口径不含场内溢折价；真实成交与净值组合可能不同",
        "当前仓位回套历史属于反事实路径，不是用户账户历史收益",
        "没有前瞻收益预测；Historical-return stress 仅用于揭示追逐样本收益的集中风险",
        "地区和币种属性不等于收入来源、经济风险或净外汇敞口；纯风格及独立外汇因子未识别",
    ]
    if missing_products:
        flags.append("未完成证券级穿透的产品：" + ", ".join(missing_products))
    result = {
        "schema_version": "1.0",
        "data_kind": snapshot_bundle.get("data_kind", "user-supplied"),
        "data_provenance": {
            "portfolio": snapshot_bundle.get("source_observation", {}).get("provider", "Local snapshot"),
            "nav": nav_source,
            "holdings": "Explicit source_id, scope, holding_date and publication date per holding",
        },
        "engine_version": __version__,
        "run_id": run_id,
        "as_of": str(config.as_of),
        "position_total_cny": total,
        "position_count": len(codes),
        "snapshot_update": snapshot_update,
        "disclosure_dates": sorted({str(h.holding_date) for h in holdings}),
        "readiness": "RESEARCH_WITH_LIMITS",
        "implementation_ready": False,
        "alignment": alignment,
        "covariance": {
            "estimator": "Ledoit-Wolf, complete cases, 52 periods/year",
            "shrinkage": shrinkage,
            "annualized": True,
        },
        "issuer_nav_cross_validation": issuer_qa,
        "configuration": config.model_dump(mode="json"),
        "positions": position_analysis,
        "candidates": evaluation,
        "objectives": objectives,
        "overlap": overlap,
        "complete_equity_overlap": equity_overlap,
        "supplemental_basket_estimates": supplemental,
        "leave_one_out": leave_one_out(cov, current, codes),
        "statistical_factors": statistical_factors(returns, current),
        "market_proxy_model": market_model,
        "flags": sorted(set(flags)),
        "disclosure_qa": read_json(root / "private/disclosure_qa.json")
        if (root / "private/disclosure_qa.json").exists()
        else {},
        "security_registry": {
            k: {"name": h.name, "source": h.source_id, "holding_date": str(h.holding_date)}
            for k, h in registry.items()
        },
        "cash_scenario": {
            "minimum_risk_without_return_requirement": "100% deterministic cash under zero-interest/no-inflation-risk assumption",
            "reason_separate": "not an investable expected-return recommendation; risk-free nominal model is degenerate",
        },
    }
    write_json(out / "decision.json", result)
    for filename, frame in [
        ("weekly_returns", returns),
        ("weekly_nav_levels", levels),
        ("actual_nav_dates", dates),
        ("nav_age_days", ages),
        ("exposure_matrix", matrix),
        ("overlap_lower", lower),
        ("overlap_upper", upper),
        ("correlation", correlation),
        ("covariance", pd.DataFrame(cov, index=codes, columns=codes)),
        ("sample_covariance", returns.cov() * 52),
        ("path_returns", path_returns),
    ] + proxy_frames:
        frame.to_csv(out / (filename + ".csv"), encoding="utf-8")
    nav.to_csv(out / "daily_adjusted_nav.csv", index=False)
    pd.DataFrame(equity_overlap).to_csv(out / "complete_equity_overlap.csv", index=False)
    pd.DataFrame(
        [
            {
                "parent": b["parent"],
                "fund": b["fund"],
                "holding_date": b["holding_date"],
                "basis": b["basis"],
                "security": e["security"],
                "name": e["name"],
                "basket_weight": e["basket_weight"],
                **e["estimated_portfolio_weights"],
            }
            for b in supplemental
            for e in b["equity_estimates"]
        ]
    ).to_csv(out / "supplemental_basket_estimates.csv", index=False)
    pd.DataFrame({name: w for name, w in candidates.items()}, index=codes).to_csv(
        out / "candidate_weights.csv"
    )
    from .report import render_report

    render_report(result, out / "Portfolio_Decision_Report.html")
    manifest = {
        "run_id": run_id,
        "engine_version": __version__,
        "code_sha256": code_digest,
        "inputs": archive_inputs(inputs, root),
        "code": archive_inputs(code_manifest, root),
        "execution": {
            "config": config_path.relative_to(root).as_posix(),
            "snapshot": snapshot_path.relative_to(root).as_posix(),
            "holdings": holdings_path.relative_to(root).as_posix(),
        },
        "outputs": input_manifest([p for p in out.iterdir() if p.name != "manifest.json"], root),
        **environment,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    write_json(out / "manifest.json", manifest)
    write_json(
        root / "private/latest.json",
        {"run_id": run_id, "report": str((out / "Portfolio_Decision_Report.html").resolve())},
    )
    return out, result
