"""Calendar alignment preserves actual NAV dates and never fills missing returns."""

import numpy as np
import pandas as pd

from .evidence import DataError


def weekly_panel(nav, codes, start, end, max_age_days=4, min_observations=40):
    if nav.duplicated(["code", "date"]).any():
        raise DataError("Duplicate NAV date")
    endpoints = pd.date_range(start, end, freq="W-FRI").as_unit("ns")
    levels = pd.DataFrame(index=endpoints, columns=codes, dtype=float)
    ages = pd.DataFrame(index=endpoints, columns=codes, dtype=float)
    dates = pd.DataFrame(index=endpoints, columns=codes)
    for code in codes:
        s = nav.loc[nav.code == code].sort_values("date").copy()
        s["date"] = pd.to_datetime(s["date"]).astype("datetime64[ns]")
        if s.empty:
            raise DataError(f"Missing series {code}")
        merged = pd.merge_asof(
            pd.DataFrame({"endpoint": endpoints}),
            s,
            left_on="endpoint",
            right_on="date",
            direction="backward",
        )
        age = (merged.endpoint - merged.date).dt.days
        valid = age.between(0, max_age_days)
        levels[code] = merged.adjusted_nav.where(valid).to_numpy()
        ages[code] = age.to_numpy()
        dates[code] = merged.date.dt.strftime("%Y-%m-%d").to_numpy()
    raw = levels.pct_change(fill_method=None)
    valid = raw.notna().all(axis=1)
    panel = raw.loc[valid]
    if len(panel) < min_observations:
        raise DataError(f"Only {len(panel)} complete weekly returns; need {min_observations}")
    if not np.isfinite(panel.to_numpy()).all() or (panel <= -1).any().any():
        raise DataError("Invalid total return")
    return (
        panel,
        levels,
        dates,
        ages,
        {
            "calendar": "Friday endpoint, latest observed NAV within age limit; no forward fill of returns",
            "periods": len(panel),
            "dropped_periods": raw.index[~valid].strftime("%Y-%m-%d").tolist(),
            "start": panel.index.min().date().isoformat(),
            "end": panel.index.max().date().isoformat(),
            "max_nav_age_days": max_age_days,
            "cross_market_close_synchrony": "NOT_GUARANTEED; weekly returns reduce but do not remove timing bias",
            "price_basis": "CNY adjusted fund NAV; ETF/LOF market premium and execution return excluded",
        },
    )
