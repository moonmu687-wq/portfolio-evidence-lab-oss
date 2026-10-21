import pytest

from portfolio_lab.evidence import DataError, read_json, write_json
from portfolio_lab.refresh import refresh_once


def test_failed_refresh_preserves_last_success_and_records_failure(tmp_path, monkeypatch):
    import portfolio_lab.refresh as refresh

    write_json(tmp_path / "private/latest.json", {"run_id": "last-good"})
    monkeypatch.setattr(refresh, "normalize", lambda *args: 1)

    def fail(*args):
        raise DataError("Missing required market data")

    monkeypatch.setattr(refresh, "run_research", fail)
    with pytest.raises(DataError):
        refresh_once(tmp_path, "catalog", "config", "snapshot")
    assert read_json(tmp_path / "private/latest.json")["run_id"] == "last-good"
    assert read_json(tmp_path / "private/update_status.json")["status"] == "FAILED"
    assert (tmp_path / "private/update_history.jsonl").exists()
