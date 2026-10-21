from copy import deepcopy

import pytest

from portfolio_lab.evidence import DataError, read_json, write_json
from portfolio_lab.snapshot_update import select_inputs, snapshot_changes, update_guard, update_snapshot
from portfolio_lab.ssot import parse_snapshot, read_google_sheet, sheet_ranges


def snapshot(value=100, as_of="2026-01-01"):
    return {
        "metadata": {"spreadsheetId": "example_sheet_123"},
        "portfolio": {
            "values": [
                ["as_of", "venue", "code", "name", "market_value"],
                [as_of, "场内", "123456", "Synthetic test position", value],
            ]
        },
        "account": {"values": [["as_of", "base_currency"]]},
    }


def metadata():
    return {
        "spreadsheetId": "example_sheet_123",
        "sheets": [
            {
                "properties": {
                    "title": name,
                    "sheetType": "GRID",
                    "gridProperties": {"rowCount": 1200, "columnCount": 27},
                }
            }
            for name in ["00_Portfolio", "01_Account"]
        ],
    }


def test_grid_reads_cover_beyond_old_fixed_boundary_and_reject_truncation():
    ranges = sheet_ranges(metadata(), "example_sheet_123")
    assert ranges == ["'00_Portfolio'!A1:AA1200", "'01_Account'!A1:AA1200"]
    for key, value in [("rowCount", None), ("columnCount", True), ("rowCount", 10000)]:
        bad = metadata()
        bad["sheets"][0]["properties"]["gridProperties"][key] = value
        with pytest.raises(DataError):
            sheet_ranges(bad, "example_sheet_123")


def test_snapshot_schema_does_not_silently_drop_or_coerce_data():
    for mutate in [
        lambda b: b["portfolio"]["values"][0].append("market_value"),
        lambda b: b["portfolio"]["values"][1].append(500),
        lambda b: b["portfolio"]["values"][0].append("new_risk_limit"),
        lambda b: b["portfolio"]["values"][1].__setitem__(4, True),
        lambda b: b["portfolio"]["values"][1].__setitem__(0, 46000.5),
    ]:
        bad = snapshot()
        mutate(bad)
        with pytest.raises(DataError):
            parse_snapshot(bad)


def test_direct_sheet_read_checks_full_ranges_consistency_and_secret_safety(monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEETS_ACCESS_TOKEN", "test-token-never-log")
    ranges = sheet_ranges(metadata(), "example_sheet_123")
    portfolio = {"range": ranges[0], "majorDimension": "ROWS", "values": snapshot()["portfolio"]["values"]}
    # A position after row 500 must be included, even when intervening rows are blank.
    portfolio["values"] += [[] for _ in range(600)]
    portfolio["values"].append(["2026-01-01", "场内", "654321", "Second test position", 50])
    account = {"range": ranges[1], "majorDimension": "ROWS", "values": snapshot()["account"]["values"]}

    class Session:
        def __init__(self, responses):
            self.responses = iter(responses)
            self.urls = []

        def get(self, url, **kwargs):
            self.urls.append(url)
            data = next(self.responses)
            return type("Response", (), {"status_code": 200, "json": lambda s: data})()

    session = Session([metadata(), portfolio, account, portfolio, account, metadata()])
    result = read_google_sheet("example_sheet_123", session=session)
    assert len(parse_snapshot(result)[0]) == 2
    assert any("AA1200" in u for u in session.urls)
    assert "test-token" not in str(result)
    changed = deepcopy(portfolio)
    changed["values"][1][4] += 1
    with pytest.raises(DataError, match="changed during read"):
        read_google_sheet(
            "example_sheet_123",
            session=Session([metadata(), portfolio, account, changed, account, metadata()]),
        )

    class Denied:
        def get(self, *args, **kwargs):
            return type("Response", (), {"status_code": 401})()

    with pytest.raises(DataError) as err:
        read_google_sheet("example_sheet_123", session=Denied())
    assert "401" in str(err.value) and "test-token" not in str(err.value)


def test_snapshot_changes_are_not_claimed_as_returns_or_trades():
    before, after = snapshot(), snapshot(value=120, as_of="2026-01-02")
    after["portfolio"]["values"].append(["2026-01-02", "场外", "654321", "Test new", 30])
    changes = snapshot_changes(before, after)
    assert changes["added_codes"] == ["654321"]
    assert changes["market_value_difference_cny"] == 50
    assert changes["changed_positions"][0]["fields"]["market_value"] == {"before": 100, "after": 120}
    assert "not P&L" in changes["interpretation"]
    after["metadata"]["spreadsheetId"] = "another_sheet_456"
    with pytest.raises(DataError, match="different SSOT"):
        snapshot_changes(before, after)


def prepare(root):
    write_json(root / "private/ssot/raw.json", snapshot())
    write_json(
        root / "config/research.json",
        {"as_of": "2026-01-01", "start": "2025-01-01", "constraints": {"max_weights": {"123456": 0.8}}},
    )
    write_json(root / "private/latest.json", {"run_id": "last-good"})


def test_update_preserves_baseline_follows_date_and_keeps_constraints(tmp_path, monkeypatch):
    import portfolio_lab.refresh as refresh

    prepare(tmp_path)
    original = (tmp_path / "private/ssot/raw.json").read_bytes()

    def succeed(root, catalog, config, source, online_market, _locked):
        assert _locked and (root / "private/update.lock").exists()
        cfg = read_json(root / config)
        assert cfg["as_of"] == "2026-01-02"
        assert cfg["constraints"]["max_weights"]["123456"] == 0.8
        write_json(root / "private/latest.json", {"run_id": "new-good"})
        return "report.html"

    monkeypatch.setattr(refresh, "refresh_once", succeed)
    status = update_snapshot(tmp_path, snapshot(120, "2026-01-02"))
    assert status["run_id"] == "new-good"
    config, source = select_inputs(tmp_path)
    assert source != "private/ssot/raw.json" and config != "config/research.json"
    assert (tmp_path / "private/ssot/raw.json").read_bytes() == original
    assert not (tmp_path / "private/update.lock").exists()


def test_failed_update_restores_exact_bytes_and_active_inputs(tmp_path, monkeypatch):
    import portfolio_lab.refresh as refresh

    prepare(tmp_path)
    original = b'{  "run_id" : "last-good" }\r\n'
    (tmp_path / "private/latest.json").write_bytes(original)
    write_json(tmp_path / "private/holdings.json", [{"previous": "holding"}])
    old_holdings = (tmp_path / "private/holdings.json").read_bytes()

    def fail(root, *args, **kwargs):
        write_json(root / "private/latest.json", {"run_id": "not-adopted"})
        write_json(root / "private/holdings.json", [{"invalid": "new"}])
        write_json(root / "private/market_catalog.json", {"invalid": "new"})
        write_json(root / "private/market_proxies.json", [{"invalid": "new proxy"}])
        raise DataError("Required independent history missing for new product")

    monkeypatch.setattr(refresh, "refresh_once", fail)
    with pytest.raises(DataError):
        update_snapshot(tmp_path, snapshot(120, "2026-01-02"))
    assert (tmp_path / "private/latest.json").read_bytes() == original
    assert (tmp_path / "private/holdings.json").read_bytes() == old_holdings
    assert not (tmp_path / "private/market_catalog.json").exists()
    assert not (tmp_path / "private/market_proxies.json").exists()
    assert not (tmp_path / "private/active_research.json").exists()
    assert read_json(tmp_path / "private/update_status.json")["status"] == "FAILED"
    assert len(list((tmp_path / "private/updates").glob("*/snapshot.json"))) == 1


def test_update_rejects_concurrent_jobs_and_date_regression(tmp_path):
    prepare(tmp_path)
    with update_guard(tmp_path):
        with pytest.raises(DataError, match="lock"):
            update_snapshot(tmp_path, snapshot())
        assert (tmp_path / "private/update.lock").exists()
    with pytest.raises(DataError, match="regress"):
        update_snapshot(tmp_path, snapshot(as_of="2025-12-31"))
    assert read_json(tmp_path / "private/latest.json")["run_id"] == "last-good"
