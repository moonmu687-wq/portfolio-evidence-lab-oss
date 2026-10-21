"""Derivative economic exposures remain separate from NAV ownership weights."""

import re

from .evidence import DataError


def parse_single_future(text, spec):
    compact = re.sub(r"\s+", "", text)
    if spec["report_title"] not in compact[:1500] or spec["fund"] not in text[:18000]:
        raise DataError("Wrong derivative source identity/period")
    header = re.search(r"持仓量\s*[（(]买/\s*卖[)）]", text)
    if not header:
        raise DataError("Futures table absent")
    end = text.find("净额", header.end())
    if end < 0:
        raise DataError("Futures settlement boundary absent")
    section = text[header.end() : end]
    contracts = set(re.findall(r"\b[A-Z]{1,4}(?:[A-Z]\d|\d{4})\b", section))
    if contracts != {spec["contract"]}:
        raise DataError("Single-contract adapter cannot certify this futures table")
    previous = text[max(0, header.start() - 1200) : header.start()]
    if "人民币元" not in previous:
        raise DataError("Derivative currency unverified")
    nominal = re.search(r"权益衍生工具(-?[\d,]+\.\d{2})", re.sub(r"\s+", "", previous))
    pnl = re.search(r"合计\s+(?:-\s+){0,3}(-?[\d,]+\.\d{2})", section)
    quantity = re.search(r"(?<![\w,])(-?\d+(?:\.\d{2})?)\s+(?=[\d,]+\.)", section)
    nav = re.search(r"净资产合计\s+([\d,]+\.\d{2})", text)
    if not all([nominal, pnl, quantity, nav]):
        raise DataError("Derivative table fields incomplete")
    nominal = float(nominal[1].replace(",", ""))
    pnl = float(pnl[1].replace(",", ""))
    quantity = float(quantity[1])
    nav = float(nav[1].replace(",", ""))
    # The reviewed reports reconcile contract market value = contract amount + valuation movement.
    value = nominal + pnl
    if (
        abs(value - spec["verified_contract_market_value_cny"]) > 0.02
        or quantity != spec["verified_quantity"]
    ):
        raise DataError("Derivative reconstruction fails reviewed market-value/quantity tie-out")
    if value * quantity <= 0:
        raise DataError("Derivative direction unresolved")
    return {
        "fund": spec["fund"],
        "contract": spec["contract"],
        "underlying": spec["underlying"],
        "quantity": quantity,
        "contract_nominal_cny": nominal,
        "valuation_movement_cny": pnl,
        "contract_market_value_cny": value,
        "fund_nav_cny": nav,
        "signed_notional_nav_fraction": value / nav,
        "holding_date": spec["holding_date"],
        "published_date": spec["published_date"],
        "source": spec["path"],
        "pages": spec["pages"],
        "url": spec["url"],
        "scope": "one reviewed long equity-index futures contract; not a complete derivative inventory",
        "method": "contract market value reconstructed from report nominal amount plus valuation movement and tied to reviewed table value",
        "net_fair_value_is_not_risk_exposure": True,
    }


def aggregate_derivatives(records, weights):
    output = []
    for record in records:
        if record["fund"] not in weights:
            continue
        output.append(
            {
                **record,
                "portfolio_signed_notional_fraction": weights[record["fund"]]
                * record["signed_notional_nav_fraction"],
            }
        )
    return {
        "positions": output,
        "sum_disclosed_long_notional_fraction": sum(x["portfolio_signed_notional_fraction"] for x in output),
        "nav_mass_treatment": "Not added to NAV coverage or stock overlap. Collateral and settlement NAV remain in the asset ledger.",
        "completeness": "partial; absence from this list never establishes zero derivatives",
        "security_lookthrough": "Underlying index contracts are not expanded into dated constituents",
        "risk_treatment": "Already reflected in observed fund NAV returns; never add a second volatility charge",
    }
