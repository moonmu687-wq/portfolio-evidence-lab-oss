"""Reviewed fund-of-funds PDF tables; first-layer disclosure never implies stock coverage."""

import re

from .evidence import DataError
from .models import Holding


def parse_fund_investments(text, source):
    compact = re.sub(r"\s+", "", text)
    if source["report_title"] not in compact[:1500] or source["fund"] not in text[:18000]:
        raise DataError("Wrong fund-investment report identity/period")
    start = text.rfind("前十名基金投资明细")
    end = text.find("7.11", start)
    if start < 0 or end < 0:
        raise DataError("Fund table boundaries absent")
    section = re.sub(r"PAGE \d+\n.*?第 \d+ 页 共 \d+ 页\s*", " ", text[start:end], flags=re.S)
    if "人民币元" not in section:
        raise DataError("Fund investment currency unverified")
    nav_match = re.search(r"净资产合计\s+([\d,]+\.\d{2})", text)
    total_match = re.search(r"基金投资\s+([\d,]+\.\d{2})\s+\d+\.\d{2}", text)
    if not nav_match or not total_match:
        raise DataError("Fund NAV/investment denominator absent")
    nav = float(nav_match[1].replace(",", ""))
    total = float(total_match[1].replace(",", ""))
    matches = list(re.finditer(r"(?m)^([1-9]\d?)\s+", section))
    if [int(m[1]) for m in matches] != list(range(1, 11)) or len(source["reviewed_rows"]) != 10:
        raise DataError("Expected exactly ten ranked fund investments")
    rows, audit = [], []
    for i, (match, reviewed) in enumerate(zip(matches, source["reviewed_rows"], strict=True)):
        block = section[match.end() : matches[i + 1].start() if i < 9 else len(section)]
        compact_block = re.sub(r"\s+", "", block)
        if not all(re.sub(r"\s+", "", p) in compact_block for p in reviewed["name_parts"]):
            raise DataError("Ranked fund identity differs from reviewed source")
        amounts = re.findall(
            r"(?<![\w,])(\d{1,3}(?:,\s*\d(?:\s*\d){2})+\s*\.\s*\d\s*\d)\s+(\d{1,2}\.\d{2})",
            block,
        )
        if len(amounts) != 1:
            raise DataError("Fund amount/percentage ambiguous")
        amount, pct = float(re.sub(r"[\s,]", "", amounts[0][0])), float(amounts[0][1])
        if abs(amount / nav * 100 - pct) > 0.011:
            raise DataError("Fund investment NAV denominator fails reconciliation")
        rows.append(
            Holding(
                fund=source["fund"],
                security=reviewed["security"],
                name=reviewed["name"],
                weight=amount / nav,
                holding_date=source["holding_date"],
                published_date=source["published_date"],
                source_id=source["path"] + "#pages=" + source["pages"],
                scope="top10",
                kind="fund",
            )
        )
        audit.append(
            {
                "security": reviewed["security"],
                "name": reviewed["name"],
                "value_cny": amount,
                "nav_fraction": amount / nav,
                "identity_source": reviewed["identity_source"],
            }
        )
    known = sum(x["value_cny"] for x in audit)
    if known > total + 0.02 or known > nav or len({x.security for x in rows}) != 10:
        raise DataError("Fund table mass/identity invalid")
    return rows, {
        "fund": source["fund"],
        "net_assets": nav,
        "fund_investment_total_cny": total,
        "disclosed_top10_total_cny": known,
        "disclosed_top10_nav_fraction": known / nav,
        "other_fund_nav_fraction": (total - known) / nav,
        "net_nonfund_residual_fraction": 1 - total / nav,
        "holding_date": source["holding_date"],
        "published_date": source["published_date"],
        "url": source["url"],
        "pages": source["pages"],
        "rows": audit,
        "scope": "top ten fund investments only; underlying holdings remain unresolved",
    }
