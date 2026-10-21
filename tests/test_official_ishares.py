import json
from copy import deepcopy
from datetime import date
from html import escape
from pathlib import Path

import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.models import Holding
from portfolio_lab.official_ishares import collect, estimate_nested, parse_basket, request_spec


def payload():
    columns = {
        "ticker": ["AAA", "USD", "IXTU6"],
        "issueName": ["Example equity", "USD Cash", "Future"],
        "assetClass": ["Equity", "Cash", "Futures"],
        "holdingPercent": [98.0, 2.0, 0.0],
        "marketValue": [980.0, 20.0, 0.0],
        "notionalValue": [980.0, 20.0, 500.0],
        "isin": ["US0000000000", None, None],
        "exchange": ["NASDAQ", "-", "CME"],
        "currencyCode": ["USD"] * 3,
        "countryOfRisk": ["United States"] * 3,
        "sectorName": ["Information Technology", "Cash", "Derivatives"],
        "asOfDate": 20260630,
    }
    return {
        "productId": 239705,
        "currencyCode": "USD",
        "fundName": "iShares Semiconductor ETF",
        "aladdinFundTicker": "I-GSSEM",
        "componentsByNameMap": {
            "holdings": {
                "containersByNameMap": {
                    "all": {
                        "hasData": True,
                        "dataPointsByNameMap": {k: {"value": v} for k, v in columns.items()},
                    }
                }
            }
        },
        "content": {"holdings.disclaimer": [{"text": "investment book of record; vendor price"}]},
    }


def test_basket_rejects_wrong_identity_dates_truncation_and_valuation_drift():
    source = payload()
    assert parse_basket(source, "SOXX", "2026-06-30")["equity_weight"] == 0.98
    for key, value in [("productId", 1), ("fundName", "Different fund"), ("currencyCode", "CNY")]:
        bad = deepcopy(source)
        bad[key] = value
        with pytest.raises(DataError):
            parse_basket(bad, "SOXX", "2026-06-30")
    for key, value in [
        ("asOfDate", 20260928),
        ("ticker", ["AAA"]),
        ("holdingPercent", [98, 2, 50]),
        ("holdingPercent", [97, 3, 0]),
        ("marketValue", [True, 20, 0]),
        ("marketValue", [-980, 20, 0]),
        ("ticker", ["AAA", "AAA", "IXTU6"]),
        ("assetClass", ["Option", "Cash", "Futures"]),
        ("exchange", ["LSE", "-", "CME"]),
        ("isin", [None, None, None]),
    ]:
        bad = deepcopy(source)
        bad["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"]["dataPointsByNameMap"][key][
            "value"
        ] = value
        with pytest.raises(DataError):
            parse_basket(bad, "SOXX", "2026-06-30")
    source["content"] = {}
    with pytest.raises(DataError):
        parse_basket(source, "SOXX", "2026-06-30")


def test_nested_estimate_keeps_nav_coverage_and_derivatives_separate():
    basket = parse_basket(payload(), "SOXX", "2026-06-30")
    parent = Holding(
        fund="123456",
        security="US_FUND:SOXX",
        name="SOXX",
        weight=0.1,
        holding_date="2026-06-30",
        source_id="parent.pdf",
        scope="top10",
        kind="fund",
    )
    weights = {"Current": {"123456": 0.2}, "Candidate": {"123456": 0.4}}
    result = estimate_nested([basket], [parent], weights, date(2026, 9, 21))[0]
    assert result["equity_estimates"][0]["estimated_portfolio_weights"]["Current"] == pytest.approx(0.0196)
    assert result["verified_nav_coverage_increment"] == 0
    assert result["point_in_time_eligible"] is False
    assert len(result["equity_estimates"]) == 1  # Future notional does not become equity or NAV.
    parent.holding_date = date(2026, 7, 31)
    with pytest.raises(DataError):
        estimate_nested([basket], [parent], weights, date(2026, 9, 21))
    with pytest.raises(DataError):
        estimate_nested([basket], [parent], weights, date(2026, 6, 29))


def test_request_uses_only_dates_and_hosts_offered_by_issuer():
    context = {
        "context": {
            "productId": "239705",
            "currencyCode": "USD",
            "ticker": "SOXX",
            "appSubType": "ISHARES",
            "locale": "en_US",
            "targetSite": "us-ishares",
            "userType": "individual",
        },
        "services": {
            "apiHost": "https://www.blackrock.com/varnish-api/product-data/api/v2/get-product-data?"
        },
    }

    def html():
        return (
            f'<walrus-context contextid="productDataContext" value="{escape(json.dumps(context))}">'
            '<walrus-render-on-client componentkey="HoldingsWrapper" '
            f'componentprops="{escape(json.dumps({"initAsOfDateList": {"all": [20260630]}}))}">'
        )

    endpoint, params = request_spec(html(), "SOXX", "2026-06-30")
    assert endpoint.startswith("https://www.ishares.com/")
    assert params["asOfDate"] == "20260630"
    with pytest.raises(DataError):
        request_spec(html(), "SOXX", "2026-07-31")
    context["services"]["apiHost"] = "https://attacker.example/product-data/api/v2/get-product-data?"
    with pytest.raises(DataError):
        request_spec(html(), "SOXX", "2026-06-30")


def test_real_issuer_basket_when_available():
    source = Path("private/raw/issuer/soxx-20260630.json")
    if not source.exists():
        pytest.skip("Private issuer evidence is not distributed")
    basket = parse_basket(json.loads(source.read_text("utf8")), "SOXX", "2026-06-30")
    assert len(basket["rows"]) == 34
    assert len([x for x in basket["rows"] if x["assetClass"] == "Equity"]) == 30
    assert basket["equity_weight"] == pytest.approx(0.9955495)


def test_collection_stops_on_access_denial_and_preserves_failure(tmp_path):
    class Denied:
        calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return type("Response", (), {"status_code": 403})()

    session = Denied()
    output = tmp_path / "batch"
    with pytest.raises(DataError, match="HTTP 403"):
        collect("SOXX", "2026-06-30", output, session)
    assert session.calls == 1
    assert json.loads((output / "status.json").read_text())["status"] == "failed"
    assert not (output / "basket.json").exists()
    with pytest.raises(DataError, match="new issuer basket"):
        collect("SOXX", "2026-06-30", output, session)
    assert session.calls == 1
