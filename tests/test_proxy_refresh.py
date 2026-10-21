import json
from types import SimpleNamespace

import pandas as pd
import pytest

from portfolio_lab.evidence import DataError, read_json, write_json
from portfolio_lab.market_proxies import DEFINITIONS, load_proxies
from portfolio_lab.proxy_refresh import collect_proxies, dividend_index, resolve_notices


class Response:
    status_code = 200

    def __init__(self, payload):
        self.content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def json(self):
        return json.loads(self.content)


def test_dividend_pagination_rejects_truncation_duplicates_and_changing_totals(tmp_path):
    def response(page, count=11, rows=None):
        return Response(
            {
                "status": 1,
                "data": {
                    "pageSize": 10,
                    "pageIndex": page,
                    "total": count,
                    "data": rows
                    if rows is not None
                    else [{"id": i} for i in range(page * 10, min(page * 10 + 10, count))],
                },
            }
        )

    class Session:
        def __init__(self, responses):
            self.responses = iter(responses)

        def post(self, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            return next(self.responses)

    assert len(dividend_index(Session([response(0), response(1)]), tmp_path, "510310")) == 11
    for responses in [
        [response(0, rows=[{"id": 1}])],
        [response(0), response(1, count=12)],
        [response(0), response(1, rows=[{"id": 1}])],
    ]:
        with pytest.raises(DataError):
            dividend_index(Session(responses), tmp_path, "510310")


def test_new_dividend_requires_unique_matching_original_notice(tmp_path, monkeypatch):
    import portfolio_lab.proxy_refresh as proxy

    records = [
        {
            "id": 1,
            "prop1": "2026-01-15",
            "title": "易方达沪深300基金分红公告",
            "path": "https://cdn.efunds.com.cn/dividend.pdf",
        }
    ]
    info = {"ex_date": "2026-01-20", "published_date": "2026-01-15", "cash_per_share_cny": 0.1}
    monkeypatch.setattr(proxy, "dividend_index", lambda *args: records)
    monkeypatch.setattr(proxy, "parse_dividend", lambda *args: info.copy())
    monkeypatch.setattr(
        proxy,
        "PdfReader",
        lambda *args: SimpleNamespace(
            pages=[SimpleNamespace(extract_text=lambda: "parsed in separate parser tests")]
        ),
    )

    class Session:
        def get(self, *args, **kwargs):
            return Response(b"%PDF original fixture boundary")

    args = (tmp_path, tmp_path, Session(), DEFINITIONS["CN_EQUITY"], {"2026-01-20": 0.1}, [], "2026-02-01")
    assert resolve_notices(*args) == ["510310-dividend-1.pdf"]
    records.append({**records[0], "id": 2})
    with pytest.raises(DataError, match="Ambiguous"):
        resolve_notices(*args)
    records.pop()
    info["cash_per_share_cny"] = 0.2
    with pytest.raises(DataError, match="disagrees"):
        resolve_notices(*args)
    records.clear()
    with pytest.raises(DataError, match="Missing issuer"):
        resolve_notices(*args)


def test_complete_proxy_collection_validates_both_sources_without_activating(tmp_path):
    dates = pd.date_range("2026-01-01", periods=45, tz="Asia/Shanghai")

    class Session:
        def __init__(self):
            self.calls = []
            self.wrong_currency = False

        def get(self, url, **kwargs):
            self.calls.append(url)
            assert kwargs["allow_redirects"] is False
            definition = next(d for d in DEFINITIONS.values() if d["code"] in url)
            code = definition["code"]
            if "www.efunds.com.cn" in url:
                text = (
                    definition["name"]
                    + code
                    + "单位净值(元)"
                    + "".join(
                        f'<script src="https://cdn.efunds.com.cn/{code}_{kind}.js"></script>'
                        for kind in ["all", "1y"]
                    )
                )
            elif "cdn.efunds.com.cn" in url:
                kind = "all" if url.endswith("_all.js") else "1y"
                text = f'mk_{code}_{kind}="0_1_2_3_4;' + "".join(f"{d:%Y%m%d}_0_1_0_0;" for d in dates) + '";'
            elif "pingzhongdata" in url:
                text = f'var fS_code="{code}";var fS_name="Synthetic test";var ishb=false;'
                text += (
                    "var Data_netWorthTrend="
                    + json.dumps(
                        [dict(x=int(d.timestamp() * 1000), y=1, equityReturn=0, unitMoney="") for d in dates]
                    )
                    + ";"
                )
            else:
                currency = "美元" if self.wrong_currency else "元"
                text = f'var currency="{currency}";var rmbMiddlePrice=1;'
                text += f'<script src="https://fund.eastmoney.com/pingzhongdata/{code}.js"></script>'
            return Response(text.encode())

    session = Session()
    active = tmp_path / "private/market_proxies.json"
    write_json(active, {"sentinel": "previous active catalog"})
    before = active.read_bytes()
    output = tmp_path / "batch"
    catalog = collect_proxies(tmp_path, output, "2026-01-01", "2026-02-14", session=session)
    assert active.read_bytes() == before
    assert len(session.calls) == 15 and len(catalog) == 3
    nav, qa, paths = load_proxies(
        tmp_path, output / "candidate-proxy-catalog.json", "2026-01-01", "2026-02-14"
    )
    assert len(nav) == 135 and all(v["matched_dates"] == 45 for v in qa.values())
    assert all(p.exists() for p in paths)
    assert read_json(output / "collection.json")["status"] == "SUCCESS"
    with pytest.raises(DataError, match="new directory"):
        collect_proxies(tmp_path, output, "2026-01-01", "2026-02-14", session=session)
    session.wrong_currency = True
    with pytest.raises(DataError, match="currency"):
        collect_proxies(tmp_path, tmp_path / "bad", "2026-01-01", "2026-02-14", session=session)
    assert active.read_bytes() == before
    assert read_json(tmp_path / "bad/collection_failure.json")["status"] == "FAILED"


@pytest.mark.parametrize("failure", ["proxy", "normalization", "research", None])
def test_online_refresh_commits_both_catalogs_together_or_restores_exact_bytes(
    tmp_path, monkeypatch, failure
):
    import portfolio_lab.providers as providers
    import portfolio_lab.proxy_refresh as proxy
    import portfolio_lab.public_nav as public
    import portfolio_lab.refresh as refresh
    import portfolio_lab.ssot as ssot
    from portfolio_lab.models import Position

    write_json(tmp_path / "config.json", {"as_of": "2026-02-14", "start": "2026-01-01"})
    write_json(tmp_path / "snapshot.json", {})
    names = ["market_proxies", "market_catalog", "latest", "holdings", "normalization_manifest"]
    files = [tmp_path / f"private/{name}.json" for name in names]
    for path in files:
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'{ "old" : "exact bytes" }\n')
    original = {p: p.read_bytes() for p in files}
    monkeypatch.setattr(
        ssot,
        "parse_snapshot",
        lambda raw: (
            [Position(code="123456", name="test", as_of="2026-02-14", venue="exchange", market_value=100)],
            [],
        ),
    )
    monkeypatch.setattr(providers, "load_nav", lambda *args: (pd.DataFrame(), []))

    def collect_proxy(*args):
        if failure == "proxy":
            raise DataError("proxy failed")
        return [{"new": "proxy"}]

    def collect_public(codes, batch, *args):
        batch.mkdir(parents=True)
        return [{"code": "123456", "entry": {"page": "page.html", "nav": "nav.js"}}]

    def normalize(*args):
        write_json(files[3], {"new": "holdings"})
        write_json(tmp_path / "private/disclosure_qa.json", {"new": "qa"})
        if failure == "normalization":
            raise DataError("normalization failed")
        return 1

    def research(*args):
        assert read_json(files[0]) == [{"new": "proxy"}]
        assert "123456" in read_json(files[1])
        if failure == "research":
            raise DataError("research failed")
        write_json(files[2], {"run_id": "new"})
        return tmp_path / "run", {"run_id": "new", "as_of": "2026-02-14"}

    monkeypatch.setattr(proxy, "collect_proxies", collect_proxy)
    monkeypatch.setattr(public, "collect", collect_public)
    monkeypatch.setattr(refresh, "normalize", normalize)
    monkeypatch.setattr(refresh, "run_research", research)
    if failure:
        with pytest.raises(DataError, match=failure):
            refresh.refresh_once(tmp_path, "catalog", "config.json", "snapshot.json", online_market=True)
        assert all(p.read_bytes() == original[p] for p in files)
        assert not (tmp_path / "private/disclosure_qa.json").exists()
    else:
        refresh.refresh_once(tmp_path, "catalog", "config.json", "snapshot.json", online_market=True)
        assert read_json(files[2])["run_id"] == "new"
