"""Refresh the declared market proxies, retaining independent issuer verification."""

import re
from datetime import UTC, date, datetime
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from .evidence import DataError, input_manifest, read_json, write_json
from .market_proxies import DEFINITIONS, load_proxies, parse_dividend
from .official_efunds import CDN, INDEX, ISSUER
from .public_nav import HOST, action_terms, page_script, parse_nav


def fetch(session, url, path, body=None):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        HOST,
        CDN,
        "www.efunds.com.cn",
        "api.efunds.com.cn",
    }:
        raise DataError("Unexpected proxy evidence URL")
    if body is None:
        response = session.get(url, timeout=30, allow_redirects=False)
    else:
        response = session.post(url, json=body, timeout=30, allow_redirects=False)
    write_json(
        path.with_suffix(path.suffix + ".request.json"),
        {
            "url": url,
            "body": body,
            "status": response.status_code,
            "collected_at": datetime.now(UTC).isoformat(),
        },
    )
    if response.status_code != 200:
        raise DataError(f"Proxy evidence HTTP {response.status_code}")
    path.write_bytes(response.content)
    return response


def dividend_index(session, output, code):
    """Read every page; a changing total or repeated record invalidates the batch."""
    records, seen, total = [], set(), None
    for page in range(100):
        body = {
            "siteID": "1",
            "catalogAlias": "xxpllsgg",
            "title": "分红",
            "fundCode": code,
            "isIncludeTransFund": "Y",
            "pageSize": 10,
            "pageIndex": page,
        }
        response = fetch(session, INDEX, output / f"{code}-dividend-index-{page}.json", body)
        result = response.json()
        data = result.get("data", {})
        count, rows = data.get("total"), data.get("data")
        if (
            result.get("status") != 1
            or type(count) is not int
            or count < 0
            or data.get("pageIndex") != page
            or data.get("pageSize") != 10
            or not isinstance(rows, list)
        ):
            raise DataError("Invalid proxy dividend pagination")
        if total is None:
            total = count
        if count != total or len(rows) != min(10, max(total - page * 10, 0)):
            raise DataError("Proxy dividend index changed or truncated")
        for row in rows:
            identity = row.get("id")
            if type(identity) is not int or identity in seen:
                raise DataError("Repeated or invalid proxy dividend record")
            seen.add(identity)
            records.append(row)
        if len(records) == total:
            return records
    raise DataError("Proxy dividend index exceeds bounded pagination")


def resolve_notices(root, output, session, definition, expected, previous, as_of):
    code = definition["code"]
    found = {}

    def register(path, published=None):
        info = parse_dividend("\n".join(p.extract_text() or "" for p in PdfReader(path).pages), code)
        if published is not None and info["published_date"] != published:
            raise DataError("Proxy dividend index/PDF publication mismatch")
        ex_date = info["ex_date"]
        if ex_date not in expected:
            return
        if info["published_date"] > as_of or abs(info["cash_per_share_cny"] - expected[ex_date]) > 1e-12:
            raise DataError("Proxy dividend notice disagrees with NAV action")
        if ex_date in found:
            raise DataError("Ambiguous proxy dividend notices")
        found[ex_date] = path.relative_to(root).as_posix()

    for old in previous:
        register(root / old)
    if found.keys() != expected.keys():
        cached_dates = set(found)
        for row in dividend_index(session, output, code):
            published = row.get("prop1", "")
            try:
                date.fromisoformat(published)
            except (ValueError, TypeError) as exc:
                raise DataError("Invalid proxy dividend publication date") from exc
            title = row.get("title", "")
            if published > as_of or definition["name"] not in title or "分红公告" not in title:
                continue
            path = output / f"{code}-dividend-{row['id']}.pdf"
            response = fetch(session, row["path"], path)
            if not response.content.startswith(b"%PDF"):
                raise DataError("Proxy dividend response is not PDF")
            # Already verified dates are reused; a newly indexed competing notice
            # for another date is still parsed and checked before acceptance.
            info = parse_dividend("\n".join(p.extract_text() or "" for p in PdfReader(path).pages), code)
            if info["ex_date"] in cached_dates:
                if info["cash_per_share_cny"] != expected[info["ex_date"]]:
                    raise DataError("Revised proxy dividend amount")
                if info["published_date"] != published:
                    raise DataError("Proxy dividend index/PDF publication mismatch")
                continue
            register(path, published)
    if found.keys() != expected.keys():
        raise DataError("Missing issuer original proxy dividend notice")
    return [found[d] for d in sorted(found)]


def collect_proxies(root, output, start, as_of, previous_catalog=None, session=None):
    """Return a validated candidate catalog without changing active research state."""
    root, output = root.resolve(), output.resolve()
    if not output.is_relative_to(root) or output.exists():
        raise DataError("Proxy batch must be a new directory inside the project")
    start, as_of = str(start), str(as_of)
    if date.fromisoformat(start) > date.fromisoformat(as_of) or date.fromisoformat(as_of) > date.today():
        raise DataError("Invalid proxy collection research dates")
    output.mkdir(parents=True)
    session = session or requests.Session()
    previous = read_json(previous_catalog) if previous_catalog else []
    cached = {row["factor"]: row for row in previous}
    catalog = []
    try:
        for factor, definition in DEFINITIONS.items():
            code = definition["code"]
            paths = {
                key: output / f"{code}-{suffix}"
                for key, suffix in {
                    "issuer_page": "issuer.html",
                    "all": "all.js",
                    "1y": "1y.js",
                    "vendor_page": "vendor.html",
                    "vendor_nav": "vendor.js",
                }.items()
            }
            page = fetch(session, f"{ISSUER}/fund/{code}.shtml", paths["issuer_page"]).content.decode("utf8")
            links = re.findall(r'<script[^>]+src=["\x27]([^"\x27]+)', page)
            for kind in ["all", "1y"]:
                urls = {u for u in links if urlparse(u).hostname == CDN and u.endswith(f"{code}_{kind}.js")}
                if len(urls) != 1:
                    raise DataError("Issuer proxy NAV link not unique")
                fetch(session, urls.pop(), paths[kind])
            page = fetch(session, f"https://{HOST}/{code}.html", paths["vendor_page"]).content.decode(
                "utf-8-sig"
            )
            fetch(session, page_script(page, code), paths["vendor_nav"])
            nav, details = parse_nav(paths["vendor_nav"].read_text("utf-8-sig"), code, start)
            if nav.date.max().date() > date.today():
                raise DataError("Proxy NAV observation from the future")
            expected = {
                x["date"]: action_terms(x["description"])[0]
                for x in details["actions"]
                if x["date"] <= as_of and action_terms(x["description"])[0]
            }
            notices = resolve_notices(
                root,
                output,
                session,
                definition,
                expected,
                cached.get(factor, {}).get("cash_notices", []),
                as_of,
            )
            catalog.append(
                {
                    "factor": factor,
                    "code": code,
                    "currency": "CNY",
                    **{k: p.relative_to(root).as_posix() for k, p in paths.items()},
                    "cash_notices": notices,
                }
            )
        evidence = [p.relative_to(root).as_posix() for p in sorted(output.glob("*.request.json"))]
        evidence += [p.relative_to(root).as_posix() for p in sorted(output.glob("*-index-*.json"))]
        receipt = output / "collection.json"
        candidate = output / "candidate-proxy-catalog.json"
        for row in catalog:
            cached_receipts = []
            for notice in row["cash_notices"]:
                notice_path = root / notice
                for sidecar in [
                    notice_path.with_suffix(".request.json"),
                    notice_path.with_suffix(notice_path.suffix + ".request.json"),
                ]:
                    if sidecar.exists():
                        cached_receipts.append(sidecar.relative_to(root).as_posix())
            row["evidence_paths"] = sorted(set(evidence + cached_receipts))
        write_json(candidate, catalog)
        _, qa, _ = load_proxies(root, candidate, start, as_of)
        write_json(
            receipt,
            {
                "status": "SUCCESS",
                "research_as_of": as_of,
                "start": start,
                "qa": qa,
                "collected_at": datetime.now(UTC).isoformat(),
                "evidence": input_manifest(
                    [p for p in output.iterdir() if p != candidate]
                    + [root / p for row in catalog for p in row["cash_notices"] + row["evidence_paths"]],
                    root,
                ),
            },
        )
        for row in catalog:
            row["evidence_paths"].append(receipt.relative_to(root).as_posix())
        write_json(candidate, catalog)
        return catalog
    except Exception as exc:
        write_json(output / "collection_failure.json", {"status": "FAILED", "error": str(exc)})
        raise
