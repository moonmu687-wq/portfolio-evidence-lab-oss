"""Bounded, fail-closed adapters for issuer report text. Original PDFs remain the evidence."""

import re
from pathlib import Path

from .evidence import DataError
from .models import Holding


def canonical_security(raw):
    """Listing identity, not issuer identity. A/H and GOOG/GOOGL remain distinct."""
    raw = raw.strip()
    if ":" in raw:
        return raw
    code, sep, exchange = raw.rpartition(".")
    if not sep:
        if raw.isdigit() and len(raw) == 6:
            return "CN:" + raw
        if raw.isdigit() and len(raw) == 5:
            return "HK:" + raw
        raise DataError(f"Unmapped security identity {raw}")
    markets = {"SH": "CN", "SZ": "CN", "BJ": "CN", "HK": "HK", "O": "US", "N": "US", "DF": "DE", "T": "JP"}
    if exchange not in markets:
        raise DataError(f"Unmapped listing suffix {raw}")
    if exchange == "HK":
        code = code.zfill(5)
    return markets[exchange] + ":" + code


def parse_full_equity_text(
    path: Path,
    code: str,
    expected_total: float,
    pages: str,
    holding_date="2026-06-30",
    published_date="2026-08-31",
    report_title="2026年中期报告",
    layout="cn",
):
    text = path.read_text("utf-8")
    compact = re.sub(r"\s+", "", text[:1500])
    if report_title not in compact or code not in text[:18000]:
        raise DataError("Wrong reporting period")
    nav_match = re.search(r"净资产合计\s+([\d,]+\.\d{2})", text)
    if not nav_match:
        raise DataError("NAV denominator absent")
    nav = float(nav_match[1].replace(",", ""))
    if layout not in {"cn", "cn_split", "us", "global", "de_ranked", "hk_ranked"}:
        raise DataError("Unsupported equity report layout")
    if layout in {"de_ranked", "hk_ranked"}:
        from .asset_tables import parse_ranked_equities

        parsed = parse_ranked_equities(text, layout)
    else:
        parsed = None
    heading = "所有权益投资明细" if layout in {"us", "global"} else "所有股票投资明细"
    start = text.rfind(heading)
    if layout == "cn_split":
        # Index-enhanced funds disclose two sleeves. Starting at the last
        # occurrence silently drops the index sleeve; require both boundaries.
        index = list(re.finditer(r"7\.3\.1\s+期末指数投资[^\n]*所有股票投资明细", text))
        active = list(re.finditer(r"7\.3\.2\s+期末积极投资[^\n]*所有股票投资明细", text))
        if len(index) != 1 or len(active) != 1 or index[0].start() >= active[0].start():
            raise DataError("Index and active equity sleeve boundaries unverified")
        start = index[0].start()
    end = re.search(r"(?:7\.5 |7\.4 )?报告期内(?:股票|权益)投资组合的重大变动", text[start:])
    if parsed is None and (start < 0 or not end):
        raise DataError("Full equity table boundaries unverified")
    section = text[start : start + end.start()] if end else ""
    if parsed is None:
        parsed = []
    if layout in {"us", "global"}:
        section = re.sub(r"PAGE \d+\n.*?第 \d+ 页共 \d+ 页\s*", " ", section, flags=re.DOTALL)
        pattern = r"\b([A-Z0-9][A-Z0-9./\- ]{0,10}) (US|CH|HK|JP|KS|TT|GR)\s+.*?([\d,]+\.\d{2})\s+(\d+\.\d{2})(?=\s|$)"
        for m in re.finditer(pattern, section, re.DOTALL):
            ticker = m[1].replace(" ", "")
            market = {"US": "US", "CH": "CN", "HK": "HK", "JP": "JP", "KS": "KR", "TT": "TW", "GR": "DE"}[
                m[2]
            ]
            if layout == "us" and market != "US":
                raise DataError("Unexpected market in US-only report adapter")
            if market == "HK":
                ticker = ticker.zfill(5)
            if market == "US":
                ticker = ticker.replace("/", ".")
            parsed.append((market + ":" + ticker, ticker, float(m[3].replace(",", "")), float(m[4])))
    elif layout in {"cn", "cn_split"}:
        pattern = r"^\d+\s+(\d{5,6})\s+(.+?)\s+[\d,]+(?:\.\d+)?\s+([\d,]+\.\d{2})\s+(\d+\.\d{2})\s*$"
        for m in re.finditer(pattern, section, re.MULTILINE):
            parsed.append((canonical_security(m[1]), m[2], float(m[3].replace(",", "")), float(m[4])))
    total = sum(x[2] for x in parsed)
    if abs(total - expected_total) > 0.02:
        raise DataError(
            f"{code} incomplete table: {len(parsed)} rows sum {total:.2f}, expected {expected_total:.2f}"
        )
    if len({p[0] for p in parsed}) != len(parsed):
        raise DataError("Duplicate PDF securities")
    records = []
    for sec, name, amount, pct in parsed:
        weight = amount / nav
        if abs(weight * 100 - pct) > 0.011:
            raise DataError(f"{code}/{sec}: percentage denominator fails tie-out")
        records.append(
            Holding(
                fund=code,
                security=sec,
                name=name,
                weight=weight,
                holding_date=holding_date,
                published_date=published_date,
                source_id=path.name.replace(".txt", ".pdf") + "#pages=" + pages,
                scope="full_equity",
            )
        )
    return records, {
        "fund": code,
        "rows": len(records),
        "fair_value_sum": total,
        "equity_total": expected_total,
        "net_assets": nav,
        "equity_nav_coverage": total / nav,
        "reconciled": True,
        "pages": pages,
        "scope": "full equity only; net non-equity residual remains unknown",
    }
