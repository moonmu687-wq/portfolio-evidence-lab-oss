"""Three declared CNY market proxies, verified against issuer evidence.

These are funded fund-return benchmarks, not pure style factors or FX hedges.
Cash-distribution returns use an explicit ex-date reinvestment convention.
"""

import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from pypdf import PdfReader

from .evidence import DataError, read_json
from .official_efunds import cross_check_returns, merge_nav_scripts, parse_nav_script
from .public_nav import action_terms, page_script, parse_nav

DEFINITIONS = {
    "CN_EQUITY": {"code": "510310", "label": "沪深300人民币基金代理", "name": "易方达沪深300"},
    "US_EQUITY_CNY": {"code": "161125", "label": "标普500人民币基金代理", "name": "易方达标普500"},
    "GOLD_CNY": {"code": "159934", "label": "境内黄金人民币基金代理", "name": "易方达黄金"},
}


def parse_dividend(text, code):
    text = re.sub(r"\s+", "", text)
    if "基金主代码" + code not in text:
        raise DataError("Dividend notice product identity mismatch")

    def day(label):
        found = re.search(label + r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
        if not found:
            raise DataError("Dividend notice date missing: " + label)
        return date(*map(int, found.groups())).isoformat()

    amount = re.search(r"本次分红方案[（(]单位[：:]人民币元/10份基金份额[）)]([\d.]+)", text)
    if not amount or float(amount[1]) <= 0:
        raise DataError("Dividend notice amount/unit unsupported")
    result = {
        "ex_date": day("除息日"),
        "published_date": day("公告送出日期："),
        "cash_per_share_cny": float(amount[1]) / 10,
    }
    if result["published_date"] > result["ex_date"]:
        raise DataError("Dividend notice published after ex-date")
    return result


def verify_proxy(official, vendor, vendor_details, dividends, code):
    """Rebuild matching conventions rather than relaxing a failed return check."""
    if set(official.date) != set(vendor.date):
        raise DataError("Proxy providers have different observation dates")
    joined = official.merge(vendor, on=["code", "date"], suffixes=("_issuer", "_vendor")).sort_values("date")
    if len(joined) < 40 or not np.allclose(joined.unit_nav_issuer, joined.unit_nav_vendor, atol=1e-9, rtol=0):
        raise DataError("Proxy raw unit NAVs do not independently reconcile")
    actual_actions = {x["date"]: action_terms(x["description"]) for x in vendor_details["actions"]}
    expected_cash = {x["ex_date"]: x["cash_per_share_cny"] for x in dividends}
    observed_cash = {d: cash for d, (cash, _) in actual_actions.items() if cash}
    if observed_cash.keys() != expected_cash.keys() or any(
        abs(observed_cash[d] - expected_cash[d]) > 1e-12 for d in expected_cash
    ):
        raise DataError("Proxy cash distributions disagree with issuer original notices")
    ref = official.sort_values("date").copy()
    raw_difference = float(
        (joined.adjusted_nav_issuer.pct_change() - joined.adjusted_nav_vendor.pct_change()).abs().max()
    )
    if dividends:
        if any(split != 1 for _, split in actual_actions.values()):
            raise DataError("Mixed cash and share actions require additional primary evidence")
        units = ref.unit_nav.to_numpy()
        levels = [units[0]]
        for i in range(1, len(ref)):
            cash = expected_cash.get(str(ref.date.iloc[i].date()), 0)
            levels.append(levels[-1] * (units[i] + cash) / units[i - 1])
        # Cash day discrepancies are retained explicitly. Other dates must still
        # agree with the issuer's own cumulative-return series.
        daily_delta = (
            ref.adjusted_nav.pct_change().to_numpy()
            - vendor.sort_values("date").adjusted_nav.pct_change().to_numpy()
        )
        noncash = np.array([str(d.date()) not in expected_cash for d in ref.date])
        if np.nanmax(np.abs(daily_delta[noncash])) > 2e-6:
            raise DataError("Issuer proxy discrepancies extend beyond verified cash days")
        ref["adjusted_nav"] = levels
    qa = cross_check_returns(
        vendor,
        ref,
        reference_label=(
            "E Fund raw unit NAV plus original cash-dividend PDFs, ex-date NAV reinvestment"
            if dividends
            else "E Fund issuer cumulative-return scripts; same CNY share class"
        ),
    )
    qa.update(
        code=code,
        raw_unit_nav_match=True,
        dividends=dividends,
        issuer_chart_return_difference_before_convention_alignment=raw_difference,
        share_actions=[x for x in vendor_details["actions"] if action_terms(x["description"])[1] != 1],
        source_basis="CNY unit NAV with cash distributions reinvested at ex-date NAV and explicit share conversions",
        cash_timing_limitation="Analytical total return: cash is assumed reinvested on ex-date, not delayed payment date; no execution claim",
    )
    return qa


def load_proxies(root: Path, catalog_path: Path, start, as_of):
    catalog = read_json(catalog_path)
    if {x["factor"] for x in catalog} != set(DEFINITIONS) or len(catalog) != len(DEFINITIONS):
        raise DataError("Market proxy definitions missing/duplicated")
    frames, qa, paths = [], {}, [catalog_path]
    for spec in catalog:
        definition = DEFINITIONS[spec["factor"]]
        code = definition["code"]
        if spec["code"] != code or spec["currency"] != "CNY":
            raise DataError("Proxy identity or currency mismatch")
        p = {key: root / spec[key] for key in ["issuer_page", "all", "1y", "vendor_page", "vendor_nav"]}
        issuer_page = p["issuer_page"].read_text("utf8")
        if (
            definition["name"] not in issuer_page
            or code not in issuer_page
            or "单位净值(元)" not in issuer_page
        ):
            raise DataError("Issuer proxy name/CNY unit evidence missing")
        page_script(p["vendor_page"].read_text("utf-8-sig"), code)
        official = merge_nav_scripts(*[parse_nav_script(p[k].read_text("utf8"), code) for k in ["all", "1y"]])
        vendor, details = parse_nav(p["vendor_nav"].read_text("utf-8-sig"), code, str(start))
        official = official[(official.date >= pd.Timestamp(start)) & (official.date <= pd.Timestamp(as_of))]
        vendor = vendor[(vendor.date >= pd.Timestamp(start)) & (vendor.date <= pd.Timestamp(as_of))]
        if vendor.empty or (pd.Timestamp(as_of) - vendor.date.max()).days > 4:
            raise DataError("Proxy NAV stale at research date")
        details["actions"] = [x for x in details["actions"] if x["date"] <= str(as_of)]
        dividends = []
        for file in spec.get("cash_notices", []):
            path = root / file
            dividend = parse_dividend("\n".join(p.extract_text() for p in PdfReader(path).pages), code)
            if dividend["published_date"] > str(as_of):
                raise DataError("Look-ahead dividend evidence")
            if str(start) <= dividend["ex_date"] <= str(as_of):
                dividends.append({**dividend, "source": file})
            paths.append(path)
        if len({d["ex_date"] for d in dividends}) != len(dividends):
            raise DataError("Duplicate dividend notices")
        qa[spec["factor"]] = {
            **verify_proxy(official, vendor, details, dividends, code),
            **definition,
            "date_start": str(vendor.date.min().date()),
            "date_end": str(vendor.date.max().date()),
        }
        vendor["code"] = spec["factor"]
        frames.append(vendor)
        paths.extend(p.values())
        paths.extend(root / x for x in spec.get("evidence_paths", []))
    return pd.concat(frames, ignore_index=True), qa, paths
