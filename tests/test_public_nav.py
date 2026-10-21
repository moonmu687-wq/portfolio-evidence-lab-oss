import json

import pandas as pd
import pytest

from portfolio_lab.evidence import DataError, read_json, write_json
from portfolio_lab.public_nav import collect, load_issuer_nav, page_script, parse_nav


def script(rows, code="123456"):
    return (
        f'var fS_code="{code}";var fS_name="Test only";var ishb=false;var Data_netWorthTrend='
        + json.dumps(rows)
        + ";"
    )


def rows(values, actions=None):
    dates = pd.date_range("2026-01-05", periods=len(values), tz="Asia/Shanghai")
    return [
        dict(x=int(d.timestamp() * 1000), y=v, equityReturn=r, unitMoney=(actions or {}).get(i, ""))
        for i, (d, (v, r)) in enumerate(zip(dates, values))
    ]


PAGE = 'var currency="元";var rmbMiddlePrice=1.0000;<script src="//fund.eastmoney.com/pingzhongdata/123456.js?v=1"></script>'


def test_cash_reinvestment_and_split_preserve_economic_return():
    data = rows(
        [(1, 0), (0.9, 0), (0.225, 0), (0.2475, 10)], {1: "每份派现金0.1元", 2: "拆分：每份基金份额分拆4.0份"}
    )
    frame, qa = parse_nav(script(data), "123456", "2026-01-05")
    assert frame.adjusted_nav.tolist() == pytest.approx([1, 1, 1, 1.1])
    assert len(qa["actions"]) == 2
    # A report window starting after an action has an arbitrary new base.
    frame, _ = parse_nav(script(data), "123456", "2026-01-07")
    assert frame.adjusted_nav.iloc[-1] / frame.adjusted_nav.iloc[0] == pytest.approx(1.1)


def test_explicit_dividend_prefix_and_combined_action_rejection():
    data = rows([(1, 0), (0.978, 0)], {1: "分红：每份派现金0.022元"})
    frame, _ = parse_nav(script(data), "123456", "2026-01-05")
    assert frame.adjusted_nav.tolist() == pytest.approx([1, 1])
    data[1]["unitMoney"] += "；拆分：每份基金份额分拆2份"
    with pytest.raises(DataError, match="Unrecognized"):
        parse_nav(script(data), "123456", "2026-01-05")


def test_reverse_share_conversion_preserves_wealth():
    data = rows([(1, 0), (2, 0), (2.2, 10)], {1: "拆分：每份基金份额折算0.5份"})
    frame, _ = parse_nav(script(data), "123456", "2026-01-05")
    assert frame.adjusted_nav.tolist() == pytest.approx([1, 1, 1.1])


@pytest.mark.parametrize("change", ["identity", "duplicate", "expression", "action", "return", "time"])
def test_untrusted_nav_cannot_silently_change_identity_or_returns(change):
    data = rows([(1, 0), (1.01, 1)])
    text = script(data)
    if change == "identity":
        text = script(data, "654321")
    if change == "duplicate":
        text = script([data[0], data[0]])
    if change == "expression":
        text = text[:-1] + '+fetch("bad");'
    if change == "action":
        data[1]["unitMoney"] = "未知折算"
        text = script(data)
    if change == "return":
        data[1]["y"] = 2
        text = script(data)
    if change == "time":
        data[1]["x"] += 3600000
        text = script(data)
    with pytest.raises(DataError):
        parse_nav(text, "123456", "2026-01-01")


def test_product_currency_host_and_missing_reference_dates(tmp_path):
    assert page_script(PAGE, "123456").startswith("https://fund.eastmoney.com/")
    for bad in [PAGE.replace('"元"', '"美元"'), PAGE.replace("fund.eastmoney.com", "invalid.example")]:
        with pytest.raises(DataError):
            page_script(bad, "123456")
    data = rows([(1, 0)] * 50)
    (tmp_path / "page.html").write_text(PAGE, "utf8")
    (tmp_path / "nav.js").write_text(script(data), "utf8")
    frame, _ = parse_nav(script(data), "123456", "2026-01-01")
    ref = frame.copy()
    ref.adjusted_nav *= 4
    catalog = {"123456": dict(currency="CNY", page="page.html", nav="nav.js", start="2026-01-01")}
    assert load_issuer_nav(tmp_path, catalog, "123456", ref)[2]["matched_dates"] == 50
    data.pop(25)
    (tmp_path / "nav.js").write_text(script(data), "utf8")
    with pytest.raises(DataError, match="omitted"):
        load_issuer_nav(tmp_path, catalog, "123456", ref)


def test_collection_failure_is_recorded_and_cannot_overwrite_batch(tmp_path):
    class Unavailable:
        def get(self, *args, **kwargs):
            return type("Response", (), {"status_code": 403})()

    output = tmp_path / "batch"
    with pytest.raises(DataError, match="403"):
        collect(["123456"], output, "2026-01-01", pd.DataFrame(), session=Unavailable())
    assert read_json(output / "collection_failure.json")["status"] == "FAILED"
    with pytest.raises(DataError, match="exists"):
        collect(["123456"], output, "2026-01-01", pd.DataFrame(), session=Unavailable())


def test_online_refresh_rolls_back_market_catalog_on_research_failure(tmp_path, monkeypatch):
    import portfolio_lab.providers as providers
    import portfolio_lab.public_nav as public
    import portfolio_lab.refresh as refresh
    import portfolio_lab.ssot as ssot
    from portfolio_lab.models import Position

    write_json(tmp_path / "config.json", {"as_of": "2026-01-10", "start": "2025-01-01"})
    write_json(tmp_path / "snapshot.json", {})
    old = {"old": "catalog"}
    write_json(tmp_path / "private/market_catalog.json", old)
    write_json(tmp_path / "private/latest.json", {"run_id": "previous-good"})
    pos = Position(code="123456", name="Test only", as_of="2026-01-10", venue="exchange", market_value=1)
    monkeypatch.setattr(ssot, "parse_snapshot", lambda raw: ([pos], []))
    monkeypatch.setattr(providers, "load_nav", lambda *args: (pd.DataFrame(), []))

    def fake_collection(codes, output, start, reference):
        output.mkdir(parents=True)
        return [{"code": "123456", "entry": dict(provider="eastmoney", page="page.html", nav="nav.js")}]

    monkeypatch.setattr(public, "collect", fake_collection)
    monkeypatch.setattr(refresh, "normalize", lambda *args: 1)

    def fail(*args):
        raise DataError("infeasible constraints")

    monkeypatch.setattr(refresh, "run_research", fail)
    with pytest.raises(DataError):
        refresh.refresh_once(tmp_path, "catalog", "config.json", "snapshot.json", True)
    assert read_json(tmp_path / "private/market_catalog.json") == old
    assert read_json(tmp_path / "private/latest.json")["run_id"] == "previous-good"
    assert read_json(tmp_path / "private/update_status.json")["status"] == "FAILED"
