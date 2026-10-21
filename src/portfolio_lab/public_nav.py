"""Public fund NAV acquisition; third-party data, never an issuer or execution price.

Remote scripts are parsed as JSON literals, never evaluated. Total returns use
unit NAV and explicit distributions/splits, not rounded displayed daily returns
or cumulative NAV. Every activated series must reconcile with an independent
archived CNY reference. An unknown corporate action fails closed.
"""

import json
import re
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .evidence import DataError, input_manifest, write_json
from .official_efunds import cross_check_returns

HOST = "fund.eastmoney.com"


def literal(text, field):
    matches = list(re.finditer(r"\bvar\s+" + re.escape(field) + r"\s*=\s*", text))
    if len(matches) != 1:
        raise DataError(f"Public NAV field missing or repeated: {field}")
    tail = text[matches[0].end() :]
    try:
        value, end = json.JSONDecoder().raw_decode(tail)
    except (ValueError, TypeError) as exc:
        raise DataError(f"Invalid JSON literal: {field}") from exc
    if not tail[end:].lstrip().startswith(";"):
        raise DataError(f"Expression instead of a literal: {field}")
    return value


def action_terms(description):
    if description == "":
        return 0.0, 1.0
    cash = re.fullmatch(r"(?:分红：)?每份派现金([0-9]+(?:\.[0-9]+)?)元", description)
    split = re.fullmatch(r"拆分：每份基金份额(?:分拆|折算)([0-9]+(?:\.[0-9]+)?)份", description)
    if cash and float(cash[1]) > 0:
        return float(cash[1]), 1.0
    if split and float(split[1]) > 0:
        return 0.0, float(split[1])
    raise DataError("Unrecognized distribution/split: " + str(description))


def parse_nav(text, code, start):
    if literal(text, "fS_code") != code or literal(text, "ishb") is not False:
        raise DataError("Public NAV identity/type mismatch")
    name = literal(text, "fS_name")
    raw = literal(text, "Data_netWorthTrend")
    if not isinstance(name, str) or not name or not isinstance(raw, list) or len(raw) < 2:
        raise DataError("Missing public NAV data")
    frame = pd.DataFrame(raw)
    if not {"x", "y", "equityReturn", "unitMoney"}.issubset(frame.columns):
        raise DataError("Public NAV schema changed")
    if any(type(v) is not int for v in frame.x):
        raise DataError("NAV timestamps must be integer milliseconds")
    dates = pd.to_datetime(frame.x, unit="ms", utc=True).dt.tz_convert("Asia/Shanghai").dt.tz_localize(None)
    if (
        dates.duplicated().any()
        or not dates.is_monotonic_increasing
        or not dates.equals(dates.dt.normalize())
    ):
        raise DataError("Duplicate, unordered or non-midnight NAV dates")
    frame["date"] = dates
    frame = frame[frame.date >= pd.Timestamp(start)].copy()
    if len(frame) < 2:
        raise DataError("Insufficient NAV observations in requested window")
    if not all(isinstance(v, str) for v in frame.unitMoney):
        raise DataError("Invalid corporate-action field")
    if any(isinstance(v, (bool, np.bool_)) for v in frame[["y", "equityReturn"]].to_numpy().ravel()):
        raise DataError("Boolean is not a NAV or return")
    numeric = frame[["y", "equityReturn"]].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(numeric.to_numpy()).all() or (numeric.y <= 0).any():
        raise DataError("Nonfinite or nonpositive NAV")
    values = numeric.y.to_numpy(dtype=float)
    returns = numeric.equityReturn.to_numpy(dtype=float) / 100
    adjusted = [values[0]]
    actions = []
    for i, description in enumerate(frame.unitMoney):
        cash, split = action_terms(description)
        if description:
            actions.append({"date": str(frame.date.iloc[i].date()), "description": description})
        if i == 0:
            continue  # Arbitrary base is the first observed closing NAV, after that day's action.
        factor = (values[i] * split + cash) / values[i - 1]
        # Rounded daily return is a consistency check only, never a calculation input.
        if abs(factor - 1 - returns[i]) > 0.000051:
            raise DataError(f"{code}: return/action mismatch on {frame.date.iloc[i].date()}")
        adjusted.append(adjusted[-1] * factor)
    result = pd.DataFrame({"code": code, "date": frame.date, "adjusted_nav": adjusted, "unit_nav": values})
    return result, {
        "name": name,
        "actions": actions,
        "first_date": str(frame.date.iloc[0].date()),
        "last_date": str(frame.date.iloc[-1].date()),
        "rows": len(frame),
    }


def page_script(page, code):
    if literal(page, "currency") != "元" or literal(page, "rmbMiddlePrice") != 1:
        raise DataError("Public page currency is not verified CNY")
    urls = re.findall(r'<script[^>]+src=["\x27]([^"\x27]+)', page)
    urls = [urljoin(f"https://{HOST}/{code}.html", u) for u in urls]
    urls = [
        u for u in urls if urlparse(u).hostname == HOST and urlparse(u).path == f"/pingzhongdata/{code}.js"
    ]
    if len(set(urls)) != 1:
        raise DataError("Public NAV link not uniquely discovered from product page")
    return urls[0]


def load_issuer_nav(
    root,
    catalog,
    code,
    reference,
    reference_label="independent previously captured Wind adjusted NAV",
):
    entry = catalog[code]
    if entry["currency"] != "CNY":
        raise DataError("Unsupported public NAV currency")
    paths = [root / entry[k] for k in ["page", "nav"]]
    page_script(paths[0].read_text("utf-8-sig"), code)
    frame, details = parse_nav(paths[1].read_text("utf-8-sig"), code, entry["start"])
    ref = reference[(reference.date >= frame.date.min()) & (reference.date <= frame.date.max())]
    if not set(ref.date).issubset(set(frame.date)):
        raise DataError("Public NAV omitted independently observed dates")
    qa = cross_check_returns(frame, ref, reference_label=reference_label)
    qa.update(
        provider="Eastmoney public fund page (third party)",
        source_basis="Unit NAV plus explicit cash distributions/splits; reinvestment at ex-date NAV",
        reference_last_date=str(ref.date.max().date()),
        **details,
    )
    frame["source_id"] = entry["nav"]
    return frame, paths, qa


def collect(
    codes,
    output,
    start,
    reference,
    session=None,
    reference_label="independent previously captured Wind adjusted NAV",
):
    if output.exists():
        raise DataError("Collection directory exists; use a new batch")
    if not codes or len(set(codes)) != len(codes) or any(not re.fullmatch(r"\d{6}", c) for c in codes):
        raise DataError("Unique six-digit fund codes required")
    pd.Timestamp(start)
    output.mkdir(parents=True)
    if session is None:
        session = requests.Session()
        session.mount(
            "https://",
            HTTPAdapter(max_retries=Retry(total=1, backoff_factor=1, status_forcelist=[502, 503, 504])),
        )
    records = []

    def fetch(url, path):
        if urlparse(url).scheme != "https" or urlparse(url).hostname != HOST:
            raise DataError("Unexpected public NAV host")
        r = session.get(url, timeout=20, allow_redirects=False)
        if r.status_code != 200:
            raise DataError(f"Public NAV HTTP {r.status_code}; batch stopped")
        path.write_bytes(r.content)
        write_json(
            path.with_suffix(path.suffix + ".request.json"),
            {"url": url, "collected_at": datetime.now(UTC).isoformat(), "status": r.status_code},
        )
        return r.content.decode("utf-8-sig")

    try:
        for code in codes:
            page = fetch(f"https://{HOST}/{code}.html", output / f"{code}-page.html")
            url = page_script(page, code)
            fetch(url, output / f"{code}.js")
            entry = {
                "provider": "eastmoney",
                "currency": "CNY",
                "start": str(pd.Timestamp(start).date()),
                "page": f"{code}-page.html",
                "nav": f"{code}.js",
            }
            frame, _, qa = load_issuer_nav(
                output,
                {code: entry},
                code,
                reference[reference.code == code],
                reference_label=reference_label,
            )
            if frame.date.max().date() > datetime.now().date():
                raise DataError("NAV observation from the future")
            records.append({"code": code, "entry": entry, "qa": qa})
        write_json(
            output / "collection.json",
            {
                "provider": "Eastmoney (third party)",
                "status": "SUCCESS",
                "collected_at": datetime.now(UTC).isoformat(),
                "records": records,
                "evidence": input_manifest(list(output.iterdir()), output),
            },
        )
    except Exception as exc:
        write_json(output / "collection_failure.json", {"status": "FAILED", "error": str(exc)})
        raise DataError(f"Public NAV collection failed: {exc}") from exc
    return records
