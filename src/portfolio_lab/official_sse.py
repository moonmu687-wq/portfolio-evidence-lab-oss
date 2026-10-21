"""Read-only, paginated SSE fund filings, discovered through the public disclosure UI."""

import re
from datetime import UTC, date, datetime
from urllib.parse import urljoin, urlparse

import requests

from .evidence import DataError, input_manifest, write_json

PAGE_URL = "https://www.sse.com.cn/disclosure/fund/etf/"
QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
SQL_ID = "COMMON_SSE_PL_JJXX_ETFGG_L"


def validate_page(payload, code, page, start, end):
    if payload.get("actionErrors") or payload.get("fieldErrors") or payload.get("sqlId") != SQL_ID:
        raise DataError("SSE disclosure query failed/schema changed")
    info = payload.get("pageHelp", {})
    rows = payload.get("result")
    if not isinstance(rows, list) or info.get("pageNo") != page or info.get("data") != rows:
        raise DataError("SSE pagination mismatch")
    if not isinstance(info.get("total"), int) or not isinstance(info.get("pageCount"), int):
        raise DataError("SSE pagination totals missing")
    for row in rows:
        if row.get("SECURITY_CODE") != code or not start <= row.get("SSEDATE", "") <= end:
            raise DataError("SSE filing code/date mismatch")
        url = urljoin(PAGE_URL, row.get("URL", ""))
        if urlparse(url).hostname != "www.sse.com.cn" or not url.endswith(".pdf"):
            raise DataError("SSE filing URL unverified")
    return rows, info


def collect(codes, output, start, end, title, session=None):
    if date.fromisoformat(start) > date.fromisoformat(end) or not codes or len(set(codes)) != len(codes):
        raise DataError("Invalid SSE collection dates/codes")
    if any(not re.fullmatch(r"\d{6}", code) for code in codes):
        raise DataError("SSE code must have six digits")
    if output.exists():
        raise DataError("Use a new SSE evidence batch directory")
    output.mkdir(parents=True)
    session = session or requests.Session()
    collected = []
    try:
        for code in codes:
            rows, page, expected = [], 1, None
            while True:
                params = {
                    "isPagination": "true",
                    "sqlId": SQL_ID,
                    "pageHelp.pageSize": 25,
                    "pageHelp.pageNo": page,
                    "pageHelp.beginPage": page,
                    "pageHelp.endPage": page,
                    "pageHelp.cacheSize": 1,
                    "SECURITY_CODE": code,
                    "BEGIN_DATE": start,
                    "END_DATE": end,
                    "DATE_DESC": 1,
                }
                response = session.get(QUERY_URL, params=params, headers={"Referer": PAGE_URL}, timeout=30)
                response.raise_for_status()
                name = f"{code}-index-{page}.json"
                (output / name).write_bytes(response.content)
                write_json(
                    output / (name + ".request.json"),
                    {
                        "url": QUERY_URL,
                        "query": params,
                        "discovery_page": PAGE_URL,
                        "retrieved_at": datetime.now(UTC).isoformat(),
                    },
                )
                batch, info = validate_page(response.json(), code, page, start, end)
                if expected is not None and expected != info["total"]:
                    raise DataError("SSE filings changed during pagination; recollect a fresh batch")
                expected = info["total"]
                rows.extend(batch)
                if page >= info["pageCount"]:
                    break
                if not batch or page >= 100:
                    raise DataError("SSE pagination stalled/exceeded bounded collection")
                page += 1
            if len(rows) != expected or len({row["URL"] for row in rows}) != len(rows):
                raise DataError("SSE duplicate/truncated disclosure index")
            matches = [row for row in rows if row["TITLE"].endswith(title) and "提示" not in row["TITLE"]]
            if len(matches) != 1:
                raise DataError("SSE target report absent/ambiguous")
            row = matches[0]
            url = urljoin(PAGE_URL, row["URL"])
            response = session.get(url, timeout=30)
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise DataError("SSE report is not PDF")
            (output / f"{code}-report.pdf").write_bytes(response.content)
            collected.append(
                {"code": code, "title": row["TITLE"], "published_date": row["SSEDATE"], "url": url}
            )
        write_json(
            output / "collection.json",
            {
                "status": "SUCCESS",
                "provider": "Shanghai Stock Exchange public fund filings",
                "collected_at": datetime.now(UTC).isoformat(),
                "reports": collected,
                "evidence": input_manifest(list(output.iterdir()), output),
            },
        )
        return collected
    except Exception as exc:
        write_json(output / "collection_failure.json", {"status": "FAILED", "error": str(exc)})
        raise
