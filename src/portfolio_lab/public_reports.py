"""Versioned manager report PDFs obtained from a public third-party mirror.

Collection does not promote an unreviewed report into the exposure catalog.
Every page is retained; product, period, pagination and PDF identity are checked.
"""

import re
from datetime import UTC, date, datetime
from io import BytesIO

import requests
from pypdf import PdfReader

from .evidence import DataError, input_manifest, write_json

INDEX = "https://api.fund.eastmoney.com/f10/JJGG"
PAGE_SIZE = 20


def validate_page(payload, code, page):
    if (
        payload.get("ErrCode") != 0
        or payload.get("PageIndex") != page
        or payload.get("PageSize") != PAGE_SIZE
    ):
        raise DataError("Public report pagination/schema mismatch")
    total, rows = payload.get("TotalCount"), payload.get("Data")
    if type(total) is not int or total < 0 or not isinstance(rows, list):
        raise DataError("Public report totals/rows missing")
    if len(rows) != max(0, min(PAGE_SIZE, total - (page - 1) * PAGE_SIZE)):
        raise DataError("Truncated public report page")
    for row in rows:
        if row.get("FUNDCODE") != code or not re.fullmatch(r"AN\d+", row.get("ID", "")):
            raise DataError("Public report product/identifier mismatch")
        if not isinstance(row.get("TITLE"), str) or not row["TITLE"]:
            raise DataError("Public report title absent")
        published = date.fromisoformat(row.get("PUBLISHDATEDesc", ""))
        if row.get("PUBLISHDATE", "")[:10] != published.isoformat():
            raise DataError("Public report publication dates disagree")
    return rows, total


def select_report(rows, code, title, as_of):
    compact_title = re.sub(r"\s+", "", title)
    matches = [
        row
        for row in rows
        if re.sub(r"\s+", "", row["TITLE"]).endswith(compact_title)
        and "提示" not in row["TITLE"]
        and row["PUBLISHDATEDesc"] <= as_of
    ]
    if len(matches) != 1 or matches[0]["FUNDCODE"] != code or matches[0].get("ATTACHTYPE") != "0":
        raise DataError("Target report absent/ambiguous or not an original PDF attachment")
    return matches[0]


def collect(codes, output, title, as_of, session=None):
    date.fromisoformat(as_of)
    if not re.fullmatch(r"20\d{2}年(?:中期|年度|第[1-4]季度)报告", title):
        raise DataError("Explicit reporting period required")
    if not codes or len(set(codes)) != len(codes) or any(not re.fullmatch(r"\d{6}", c) for c in codes):
        raise DataError("Unique six-digit codes required")
    if output.exists():
        raise DataError("Use a new public report evidence batch")
    output.mkdir(parents=True)
    session = session or requests.Session()
    reports = []
    try:
        for code in codes:
            page, rows, total = 1, [], None
            while True:
                params = {"fundcode": code, "pageIndex": page, "pageSize": PAGE_SIZE, "type": 3}
                r = session.get(
                    INDEX,
                    params=params,
                    headers={"Referer": f"https://fundf10.eastmoney.com/jjgg_{code}.html"},
                    timeout=25,
                    allow_redirects=False,
                )
                if r.status_code != 200:
                    raise DataError(f"Public report index HTTP {r.status_code}")
                path = output / f"{code}-index-{page}.json"
                path.write_bytes(r.content)
                write_json(
                    path.with_suffix(".json.request.json"),
                    {"url": INDEX, "params": params, "collected_at": datetime.now(UTC).isoformat()},
                )
                batch, count = validate_page(r.json(), code, page)
                if total is not None and total != count:
                    raise DataError("Public report index changed while paging; recollect")
                total = count
                rows.extend(batch)
                if len(rows) >= total:
                    break
                if page >= 100:
                    raise DataError("Public report pagination limit exceeded")
                page += 1
            if len({r["ID"] for r in rows}) != len(rows):
                raise DataError("Duplicate public report identifiers")
            chosen = select_report(rows, code, title, as_of)
            url = f"https://pdf.dfcfw.com/pdf/H2_{chosen['ID']}_1.pdf"
            r = session.get(url, timeout=25, allow_redirects=False)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                raise DataError("Public report attachment is not a successful PDF response")
            pdf_path = output / f"{code}-report.pdf"
            pdf_path.write_bytes(r.content)
            reader = PdfReader(BytesIO(r.content))
            prefix = "\n".join(p.extract_text() for p in reader.pages[:8])
            if code not in prefix or title not in re.sub(r"\s+", "", prefix):
                raise DataError("PDF product/reporting period mismatch")
            report = {
                "code": code,
                "url": url,
                "title": chosen["TITLE"],
                "published_date": chosen["PUBLISHDATEDesc"],
                "pages": len(reader.pages),
                "scope": "Manager disclosure PDF served by third-party mirror; holdings not automatically activated",
            }
            write_json(
                pdf_path.with_suffix(".pdf.request.json"),
                {**report, "collected_at": datetime.now(UTC).isoformat()},
            )
            reports.append(report)
        write_json(
            output / "collection.json",
            {
                "status": "SUCCESS",
                "provider": "Eastmoney report mirror",
                "as_of": as_of,
                "reports": reports,
                "evidence": input_manifest(list(output.iterdir()), output),
            },
        )
    except Exception as exc:
        write_json(output / "collection_failure.json", {"status": "FAILED", "error": str(exc)})
        raise DataError(f"Public report collection failed: {exc}") from exc
    return reports
