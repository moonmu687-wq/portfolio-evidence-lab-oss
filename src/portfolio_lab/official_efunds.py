"""Read-only issuer adapter. Parses published data strings; never executes remote JavaScript."""

import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests

from .evidence import DataError, input_manifest, write_json

ISSUER = "https://www.efunds.com.cn"
CDN = "cdn.efunds.com.cn"
INDEX = "https://api.efunds.com.cn/xcowch/front/contents"


def parse_nav_script(text, code):
    match = re.fullmatch(r"\s*mk_" + re.escape(code) + r'_(?:all|1y)\s*=\s*"([^"\\]+)";?\s*', text)
    if not match:
        raise DataError("Unexpected issuer script envelope/identity")
    tokens = match[1].split(";")
    header = tokens[0].split("_")
    # Official product-detail-overview.js declares 0=date, 1=cumulative return, 2=NAV.
    if header != ["0", "1", "2", "3", "4"]:
        raise DataError("Issuer NAV field mapping changed")
    rows = []
    for item in tokens[1:]:
        if not item:
            continue
        fields = item.split("_")
        if len(fields) != 5 or not re.fullmatch(r"\d{8}", fields[0]):
            raise DataError("Malformed issuer NAV row")
        numbers = np.array(list(map(float, fields[1:])))
        if not np.isfinite(numbers).all() or numbers[0] <= -1 or numbers[1] <= 0:
            raise DataError("Invalid issuer NAV values")
        rows.append(
            {
                "code": code,
                "date": pd.to_datetime(fields[0], format="%Y%m%d"),
                "adjusted_nav": 1 + numbers[0],
                "unit_nav": numbers[1],
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty or frame.date.duplicated().any():
        raise DataError("Empty/duplicate issuer dates")
    return frame.sort_values("date")


def merge_nav_scripts(all_frame, year_frame):
    overlap = all_frame.merge(year_frame, on=["code", "date"], suffixes=("_all", "_year"))
    if len(overlap) < 20:
        raise DataError("Issuer scripts have insufficient internal overlap")
    if not np.allclose(overlap.adjusted_nav_all, overlap.adjusted_nav_year, atol=2e-6, rtol=0):
        raise DataError("Issuer all-history and daily scripts disagree")
    return (
        pd.concat([all_frame, year_frame]).drop_duplicates(["code", "date"], keep="last").sort_values("date")
    )


def cross_check_returns(
    official,
    reference,
    min_overlap=40,
    tolerance=2e-6,
    reference_label="independent previously captured Wind adjusted NAV",
):
    joined = official.merge(reference, on=["code", "date"], suffixes=("_official", "_reference")).sort_values(
        "date"
    )
    if len(joined) < min_overlap:
        raise DataError("Insufficient independent NAV overlap")
    diff = (
        (joined.adjusted_nav_official.pct_change() - joined.adjusted_nav_reference.pct_change())
        .abs()
        .dropna()
    )
    maximum = float(diff.max())
    if maximum > tolerance:
        raise DataError(f"Issuer/vendor return mismatch {maximum:.8f}")
    return {
        "matched_dates": len(joined),
        "maximum_return_difference": maximum,
        "tolerance": tolerance,
        "reference": reference_label,
        "source_basis": "1 + issuer cumulative return; daily script preferred to rounded all-history script",
    }


def collect(codes, output, report_title="2026年中期报告", session=None):
    if output.exists():
        raise DataError("Collection directory already exists; use a new batch path")
    if not codes or any(not re.fullmatch(r"\d{6}", c) for c in codes):
        raise DataError("Six-digit fund codes required")
    output.mkdir(parents=True)
    session = session or requests.Session()
    records = []

    def fetch(url, path, body=None):
        if not url.startswith("https://") or urlparse(url).hostname not in {
            "www.efunds.com.cn",
            CDN,
            "api.efunds.com.cn",
        }:
            raise DataError("Unexpected issuer URL")
        response = session.post(url, json=body, timeout=30) if body else session.get(url, timeout=30)
        if response.status_code != 200:
            raise DataError(f"Issuer HTTP {response.status_code}; batch stopped")
        path.write_bytes(response.content)
        return response

    try:
        for code in codes:
            page = fetch(f"{ISSUER}/fund/{code}.shtml", output / f"{code}-page.html").content.decode("utf8")
            found = re.findall(r'<script[^>]+src=["\x27]([^"\x27]+)', page)
            urls = [
                u
                for u in found
                if urlparse(u).hostname == CDN
                and (u.endswith(f"{code}_all.js") or u.endswith(f"{code}_1y.js"))
            ]
            if len(set(urls)) != 2:
                raise DataError("Issuer product NAV links not uniquely discovered")
            frames = {}
            entry = {"code": code, "page_url": f"{ISSUER}/fund/{code}.shtml", "nav": {}}
            for url in sorted(set(urls)):
                kind = "all" if url.endswith("_all.js") else "1y"
                path = output / f"{code}-{kind}.js"
                response = fetch(url, path)
                frames[kind] = parse_nav_script(response.content.decode("utf8"), code)
                entry["nav"][kind] = {"url": url, "file": path.name}
            merge_nav_scripts(frames["all"], frames["1y"])
            body = {
                "siteID": "1",
                "catalogAlias": "xxpldqgg",
                "title": report_title,
                "fundCode": code,
                "isIncludeTransFund": "Y",
                "pageSize": 10,
                "pageIndex": 0,
            }
            response = fetch(INDEX, output / f"{code}-report-index.json", body)
            result = response.json()
            if result.get("status") != 1 or result["data"]["total"] != 1:
                raise DataError("Report index not unique")
            report = result["data"]["data"][0]
            if report_title not in report["title"]:
                raise DataError("Wrong reporting period")
            pdf = output / f"{code}-report.pdf"
            response = fetch(report["path"], pdf)
            if not response.content.startswith(b"%PDF"):
                raise DataError("Issuer report is not a PDF")
            entry["report"] = {
                "url": report["path"],
                "file": pdf.name,
                "title": report["title"],
                "published": report["prop1"],
            }
            entry["report_query"] = {"endpoint": INDEX, "body": body}
            records.append(entry)
        write_json(
            output / "collection.json",
            {
                "provider": "E Fund official website",
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "records": records,
                "evidence": input_manifest(list(output.iterdir()), output),
                "status": "SUCCESS",
            },
        )
    except Exception as exc:
        write_json(output / "collection_failure.json", {"status": "FAILED", "error": str(exc)})
        raise
    return records


def load_issuer_nav(root, catalog, code, reference):
    entry = catalog[code]
    if entry["currency"] != "CNY":
        raise DataError("Unsupported research currency")
    paths = [root / entry[k] for k in ["all", "1y"]]
    frames = [parse_nav_script(p.read_text("utf8"), code) for p in paths]
    frame = merge_nav_scripts(*frames)
    qa = cross_check_returns(frame, reference)
    frame["source_id"] = entry["1y"] + " + " + entry["all"]
    return frame, paths, qa
