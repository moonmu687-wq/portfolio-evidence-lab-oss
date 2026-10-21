"""Reviewed split-line equity and physical-gold tables; no inference from fund names."""

import re

from .evidence import DataError
from .models import Holding

MONEY = r"\d{1,3}(?:,\s*\d(?:\s*\d){2})+\s*\.\s*\d\s*\d"


def amount(value):
    return float(re.sub(r"[\s,]", "", value))


def parse_ranked_equities(text, layout):
    start = text.rfind("§7")
    section = text[start:] if start >= 0 else text
    heading = re.search(r"所有(?:权益|股票)投资\s*明细", section)
    end = re.search(r"报告期内(?:权益|股票)投资组合的重大变动", section)
    if not heading or not end or heading.end() >= end.start():
        raise DataError("Ranked equity boundaries absent")
    section = section[heading.end() : end.start()]
    section = re.sub(r"PAGE \d+\n.*?第\s*\d+\s*页\s*共\s*\d+\s*页\s*", "\n", section, flags=re.S)
    rank_pattern = (
        r"(?m)^([1-9]\d?)\s+(?=\d{5}\s)" if layout == "hk_ranked" else r"(?m)^([1-9]\d?)\s+(?=[A-Z])"
    )
    ranks = []
    for match in re.finditer(rank_pattern, section):
        # A company name can itself wrap onto a numeric line (e.g. SCOUT / 24 SE).
        # Sequential ranks plus per-row amount uniqueness and total reconciliation are required.
        if int(match[1]) == len(ranks) + 1:
            ranks.append(match)
    if not ranks or [int(x[1]) for x in ranks] != list(range(1, len(ranks) + 1)):
        raise DataError("Ranked equities have missing/duplicate ranks")
    parsed = []
    for i, rank in enumerate(ranks):
        block = section[rank.end() : ranks[i + 1].start() if i + 1 < len(ranks) else len(section)]
        money = re.findall(r"(?<![\w,])(" + MONEY + r")\s+(\d+\.\d{2})(?=\s|$)", block)
        if len(money) != 1:
            raise DataError("Equity fair value/percentage ambiguous")
        if layout == "de_ranked":
            codes = re.findall(r"\b([A-Z][A-Z0-9]{0,4})\s+(?:GY\s+)?德国\s+德国", block)
            if len(codes) != 1 or not re.search(r"\bGY\b", block):
                raise DataError("German listing identity unverified")
            security, name = "DE:" + codes[0], codes[0]
        else:
            match = re.match(r"(\d{5})\s+(.+?)\s+[\d,]+\s+", block, re.S)
            if not match:
                raise DataError("Hong Kong listing identity unverified")
            security, name = "HK:" + match[1], re.sub(r"\s+", "", match[2])
        parsed.append((security, name, amount(money[0][0]), float(money[0][1])))
    return parsed


def parse_physical_gold(text, source):
    compact = re.sub(r"\s+", "", text)
    if source["report_title"] not in compact[:1500] or source["report_code"] not in text[:18000]:
        raise DataError("Gold report identity/period mismatch")
    nav = re.search(r"净资产合计\s+([\d,]+\.\d{2})", text)
    total = re.search(r"贵金属投资\s+([\d,]+\.\d{2})", text)
    start = text.rfind("贵金属投资明细")
    end = text.find("7.9", start)
    if not nav or not total or start < 0 or end < 0:
        raise DataError("Gold NAV/asset ledger/table absent")
    nav, total = amount(nav[1]), amount(total[1])
    section = text[start:end]
    row = re.search(r"\b1\s+Au99\.99\s+Au99\.99\s+([\d,]+\.\d{2})\s+(" + MONEY + r")\s+(\d+\.\d{2})", section)
    if not row or re.search(r"(?m)^[2-9]\s+", section) or nav <= 0:
        raise DataError("Single physical-gold table cannot be certified")
    value = amount(row[2])
    if abs(value - total) > 0.02 or abs(value / nav * 100 - float(row[3])) > 0.011:
        raise DataError("Gold table fails asset-total/NAV reconciliation")
    holding = Holding(
        fund=source["fund"],
        security="SGE:Au99.99",
        name="Au99.99",
        weight=value / nav,
        holding_date=source["holding_date"],
        published_date=source["published_date"],
        source_id=source["path"] + "#pages=" + source["pages"],
        kind="gold",
        scope="full_gold",
        currency="CNY",
        classification_source=source["path"],
    )
    return [holding], {
        "fund": source["fund"],
        "security": holding.security,
        "quantity_reported": amount(row[1]),
        "fair_value_cny": value,
        "net_assets_cny": nav,
        "identified_nav_fraction": value / nav,
        "holding_date": source["holding_date"],
        "published_date": source["published_date"],
        "url": source["url"],
        "pages": source["pages"],
        "reconciled": True,
        "scope": "all reported gold value reconciled; other net assets remain unknown",
    }
