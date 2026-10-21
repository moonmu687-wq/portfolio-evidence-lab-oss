"""Dated issuer investment-book baskets, kept separate from accounting NAV.

Historical retrieval is not proof of historical publication. This adapter never
promotes a basket into the verified NAV exposure matrix or backtest inputs.
"""

import json
import math
import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit

import requests

from .evidence import DataError, input_manifest, write_json

PRODUCTS = {
    "SOXX": {
        "id": 239705,
        "name": "iShares Semiconductor ETF",
        "aladdin": "I-GSSEM",
        "url": "https://www.ishares.com/us/products/239705/ishares-phlx-semiconductor-etf",
    }
}


class PageContext(HTMLParser):
    def __init__(self):
        super().__init__()
        self.contexts = []
        self.dates = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "walrus-context" and attrs.get("contextid") == "productDataContext":
            self.contexts.append(json.loads(attrs["value"]))
        if attrs.get("componentkey") == "HoldingsWrapper":
            self.dates.extend(json.loads(attrs["componentprops"])["initAsOfDateList"]["all"])


def request_spec(page, ticker, holding_date):
    spec = PRODUCTS[ticker]
    parser = PageContext()
    parser.feed(page)
    target = int(date.fromisoformat(holding_date).strftime("%Y%m%d"))
    if target not in parser.dates or not parser.contexts:
        raise DataError("Requested historical holdings date is not offered by issuer")
    contexts = [x for x in parser.contexts if x.get("context", {}).get("ticker") == ticker]
    if not contexts:
        raise DataError("Issuer page ticker mismatch")
    context = contexts[0]["context"]
    if str(context.get("productId")) != str(spec["id"]) or context.get("currencyCode") != "USD":
        raise DataError("Issuer page product/currency mismatch")
    endpoint = contexts[0]["services"]["apiHost"]
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.netloc not in {"www.blackrock.com", "www.ishares.com"}
        or not parsed.path.endswith("/product-data/api/v2/get-product-data")
        or parsed.query
    ):
        raise DataError("Unexpected issuer public API host/path")
    # The issuer's public ProductPageAjaxUtils uses the current ishares host.
    endpoint = endpoint.replace("www.blackrock.com/", "www.ishares.com/")
    params = {k: context[k] for k in ["appSubType", "locale", "targetSite", "userType"]}
    params.update(
        appType="PRODUCT_PAGE",
        component="holdings.all",
        portfolioId=str(spec["id"]),
        excludeContent="false",
        asOfDate=str(target),
        includeConfig="true",
    )
    return endpoint, params


def parse_basket(payload, ticker, holding_date):
    spec = PRODUCTS[ticker]
    if any(
        payload.get(k) != v
        for k, v in {
            "productId": spec["id"],
            "currencyCode": "USD",
            "fundName": spec["name"],
            "aladdinFundTicker": spec["aladdin"],
        }.items()
    ):
        raise DataError("Issuer basket identity/currency mismatch")
    try:
        container = payload["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"]
        points = container["dataPointsByNameMap"]
        values = {k: v["value"] for k, v in points.items()}
        actual = datetime.strptime(str(values["asOfDate"]), "%Y%m%d").date().isoformat()
        fields = [
            "ticker",
            "issueName",
            "assetClass",
            "holdingPercent",
            "marketValue",
            "notionalValue",
            "isin",
            "exchange",
            "currencyCode",
            "countryOfRisk",
            "sectorName",
        ]
        columns = {k: values[k] for k in fields}
    except (KeyError, TypeError, ValueError) as exc:
        raise DataError("Issuer basket schema/date missing") from exc
    if actual != holding_date or not container.get("hasData"):
        raise DataError("Issuer returned another date or empty holdings")
    if any(not isinstance(v, list) for v in columns.values()):
        raise DataError("Issuer basket column is not an array")
    size = len(columns["ticker"])
    if not size or any(len(v) != size for v in columns.values()):
        raise DataError("Issuer basket columns are truncated")
    disclaimer = " ".join(x["text"] for x in payload.get("content", {}).get("holdings.disclaimer", []))
    if "investment book of record" not in disclaimer or "vendor price" not in disclaimer:
        raise DataError("Issuer valuation basis could not be verified")
    rows = []
    for i in range(size):
        row = {k: v[i] for k, v in columns.items()}
        for field in ["holdingPercent", "marketValue", "notionalValue"]:
            v = row[field]
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) or v < 0:
                raise DataError("Basket requires an explicit model for negative/nonfinite positions")
        if row["currencyCode"] != "USD" or not isinstance(row["issueName"], str) or not row["issueName"]:
            raise DataError("Basket currency/name missing")
        if not isinstance(row["ticker"], str) or not re.fullmatch(r"[A-Z0-9.\-/]+", row["ticker"]):
            raise DataError("Basket ticker malformed")
        if row["assetClass"] not in {
            "Equity",
            "Cash",
            "Money Market",
            "Cash Collateral and Margins",
            "Futures",
        }:
            raise DataError("Unsupported basket asset class")
        if row["assetClass"] == "Equity":
            if row["exchange"] not in {"NASDAQ", "NYSE"} or not re.fullmatch(
                r"[A-Z]{2}[A-Z0-9]{9}\d", row["isin"] or ""
            ):
                raise DataError("Equity identity/US listing unverified")
            row["security"] = "US:" + row["ticker"].replace("/", ".")
        else:
            row["security"] = None
        if row["assetClass"] == "Futures" and (row["marketValue"] != 0 or row["holdingPercent"] != 0):
            raise DataError("Nonzero derivative fair value requires a separate accounting model")
        rows.append(row)
    if len({x["ticker"] for x in rows}) != size:
        raise DataError("Duplicate issuer basket ticker")
    market_total = sum(x["marketValue"] for x in rows)
    if market_total <= 0 or abs(sum(x["holdingPercent"] for x in rows) - 100) > size * 0.000006:
        raise DataError("Issuer investment-book weight total does not reconcile")
    if any(abs(x["marketValue"] / market_total * 100 - x["holdingPercent"]) > 0.000006 for x in rows):
        raise DataError("Issuer market values and weights disagree")
    return {
        "fund": "US_FUND:" + ticker,
        "name": spec["name"],
        "holding_date": actual,
        "published_date": None,
        "point_in_time_eligible": False,
        "basis": "issuer_investment_book_vendor_prices_not_accounting_nav",
        "market_value_total_usd": market_total,
        "equity_weight": sum(x["holdingPercent"] for x in rows if x["assetClass"] == "Equity") / 100,
        "rows": rows,
        "source_url": spec["url"],
    }


def collect(ticker, holding_date, output, session=None):
    if ticker not in PRODUCTS:
        raise DataError("Unsupported issuer product; verify its identity before adding it")
    date.fromisoformat(holding_date)
    output = output.resolve()
    if output.exists():
        raise DataError("Use a new issuer basket evidence batch")
    output.mkdir(parents=True)
    session = session or requests.Session()
    evidence = []

    def get(url, path, params=None):
        r = session.get(
            url,
            params=params,
            headers={"Accept": "application/json,text/html", "x-application-id": "pp-ui-csr"},
            timeout=30,
            allow_redirects=False,
        )
        if r.status_code != 200:
            raise DataError(f"Issuer basket HTTP {r.status_code}; no alternate access attempted")
        path.write_bytes(r.content)
        receipt = path.with_suffix(path.suffix + ".request.json")
        write_json(receipt, {"url": url, "params": params, "collected_at": datetime.now(UTC).isoformat()})
        evidence.extend([path, receipt])
        return r

    try:
        page = get(PRODUCTS[ticker]["url"], output / "product.html")
        endpoint, params = request_spec(page.text, ticker, holding_date)
        payload = get(endpoint, output / "holdings.json", params).json()
        basket = parse_basket(payload, ticker, holding_date)
        write_json(output / "basket.json", basket)
        evidence.append(output / "basket.json")
        write_json(output / "manifest.json", {"inputs": input_manifest(evidence, output)})
        write_json(output / "status.json", {"status": "success", "point_in_time_eligible": False})
        return basket
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        write_json(output / "status.json", {"status": "failed", "error_type": type(exc).__name__})
        if isinstance(exc, DataError):
            raise
        raise DataError("Issuer basket collection failed; previous evidence is unchanged") from exc


def estimate_nested(baskets, holdings, candidate_weights, as_of):
    """Only same-date, one-parent edges. Never modify verified exposure coverage."""
    results = []
    if len({b["fund"] for b in baskets}) != len(baskets):
        raise DataError("Duplicate supplemental basket")
    for b in baskets:
        if date.fromisoformat(b["holding_date"]) > as_of:
            raise DataError("Look-ahead supplemental basket")
        for h in holdings:
            if h.kind != "fund" or h.security != b["fund"] or h.fund not in candidate_weights["Current"]:
                continue
            if str(h.holding_date) != b["holding_date"]:
                raise DataError("Parent and supplemental basket dates differ")
            weights = {name: w[h.fund] * h.weight for name, w in candidate_weights.items()}
            equities = [
                {
                    "security": x["security"],
                    "name": x["issueName"],
                    "basket_weight": x["holdingPercent"] / 100,
                    "estimated_portfolio_weights": {
                        n: w * x["holdingPercent"] / 100 for n, w in weights.items()
                    },
                }
                for x in b["rows"]
                if x["assetClass"] == "Equity"
            ]
            results.append(
                {
                    **b,
                    "parent": h.fund,
                    "parent_fund_nav_weight": h.weight,
                    "portfolio_fund_weights": weights,
                    "equity_estimates": equities,
                    "verified_nav_coverage_increment": 0.0,
                }
            )
    return results
