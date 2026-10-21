"""Read the public Hwabao website protocol, with strict identity and return checks."""

import hashlib
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests

from .evidence import DataError, input_manifest, read_json, write_json
from .official_efunds import cross_check_returns


def parse_nav(response, code):
    if response.get("code") != "0000" or not response.get("data"):
        raise DataError("Hwabao NAV response failed/empty")
    rows = []
    for row in response["data"]:
        if row.get("fundCode") != code or row.get("setupInc") is None:
            raise DataError("Hwabao NAV identity or cumulative return missing")
        if not re.fullmatch(r"\d{8}", str(row.get("navDate", ""))):
            raise DataError("Hwabao date malformed")
        value = 1 + float(row["setupInc"])
        if not np.isfinite(value) or value <= 0 or float(row["nav"]) <= 0:
            raise DataError("Invalid Hwabao total-return level")
        rows.append(
            {
                "code": code,
                "date": pd.to_datetime(row["navDate"], format="%Y%m%d"),
                "adjusted_nav": value,
                "unit_nav": float(row["nav"]),
            }
        )
    frame = pd.DataFrame(rows).sort_values("date")
    if frame.date.duplicated().any():
        raise DataError("Duplicate Hwabao NAV dates")
    return frame


def collect(code, output, report_title="2026年中期报告", session=None):
    if code != "501312":
        raise DataError("Hwabao adapter currently certified for 501312 only")
    if output.exists():
        raise DataError("Collection directory exists; use a new batch")
    output.mkdir(parents=True)
    session = session or requests.Session()

    def fetch(url, name, body=None):
        if urlparse(url).scheme != "https" or urlparse(url).hostname not in {
            "www.fsfund.com",
            "api.fsfund.com",
        }:
            raise DataError("Unexpected Hwabao host")
        response = (
            session.get(url, timeout=30)
            if body is None
            else session.post(url, json=body, headers={"netNo": "web"}, timeout=30)
        )
        if response.status_code != 200:
            raise DataError(f"Hwabao HTTP {response.status_code}")
        (output / name).write_bytes(response.content)
        return response

    try:
        page_url = f"https://www.fsfund.com/fund/{code}/fundDetail.shtml"
        page = fetch(page_url, "product.html").content.decode("utf8")
        if not re.search(r'id="run_way">\s*' + code, page):
            raise DataError("Hwabao product identity changed")
        base = re.search(r'id="basePath" value="([^"]+)"', page)
        if not base or base[1] != "https://api.fsfund.com/v2/webzk":
            raise DataError("Hwabao public endpoint changed")
        # Public browser request checksum, not an account credential. No remote script execution.
        script = fetch(
            "https://www.fsfund.com/static/js/common/common.js", "public-protocol.js"
        ).content.decode("utf8")
        checksum_constant = re.search(r"signStr \+= 'key=' \+ '([A-F0-9]+)'", script)
        if not checksum_constant:
            raise DataError("Public request protocol changed")

        def query(endpoint, payload, name):
            body = {k: str(v) for k, v in payload.items()}
            body.update(netNo="web", timestamp=str(int(time.time() * 1000)))
            encoded = "".join(f"{k}={body[k]}&" for k in sorted(body)) + "key=" + checksum_constant[1]
            body["signature"] = hashlib.md5(encoded.encode()).hexdigest()
            url = base[1] + "/queryController/" + endpoint
            response = fetch(url, name, body).json()
            write_json(
                output / (name + ".request.json"),
                {
                    "url": url,
                    "query": payload,
                    "protocol_source": "public-protocol.js",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                },
            )
            if response.get("code") != "0000":
                raise DataError("Hwabao query rejected")
            return response

        nav = query("queryFundNavs", {"fundCode": code, "timeType": "36"}, "nav.json")
        parse_nav(nav, code)
        reports = query(
            "queryArticles",
            {"fundCode": code, "columnId": "281", "pageSize": 10, "offset": 0},
            "reports.json",
        )
        matching = [x for x in reports["data"] if report_title in x["title"]]
        if len(matching) != 1:
            raise DataError("Target report absent/ambiguous in latest announcement page")
        report = matching[0]
        pdf = fetch(report["articleFile"], "report.pdf")
        if not pdf.content.startswith(b"%PDF"):
            raise DataError("Hwabao report is not PDF")
        write_json(
            output / "collection.json",
            {
                "provider": "Hwabao official website",
                "status": "SUCCESS",
                "code": code,
                "product_url": page_url,
                "report_url": report["articleFile"],
                "published_date": report["publishDate1"],
                "collected_at": datetime.now(UTC).isoformat(),
                "evidence": input_manifest(list(output.iterdir()), output),
            },
        )
    except Exception as exc:
        write_json(output / "collection_failure.json", {"status": "FAILED", "error": str(exc)})
        raise


def load_issuer_nav(root, catalog, code, reference):
    entry = catalog[code]
    if entry["currency"] != "CNY":
        raise DataError("Hwabao research currency unverified")
    path = root / entry["nav"]
    frame = parse_nav(read_json(path), code)
    qa = cross_check_returns(frame, reference)
    qa["source_basis"] = (
        "1 + official inception cumulative return (setupInc); never window-rounded chart dayInc"
    )
    frame["source_id"] = entry["nav"]
    return frame, [path], qa
