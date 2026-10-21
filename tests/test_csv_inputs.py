import csv

import pytest

from portfolio_lab.csv_inputs import load_csv_nav, portfolio_csv
from portfolio_lab.evidence import DataError


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(rows)
    return path


def test_position_csv_preserves_identity_and_does_not_store_account_fields(tmp_path):
    path = write_csv(
        tmp_path / "positions.csv",
        [
            ["code", "name", "market_value", "as_of", "venue"],
            ["009901", "Fictional fund", "1000", "2025-06-27", "synthetic"],
        ],
    )
    bundle = portfolio_csv(path)
    assert bundle["portfolio"]["values"][1][0] == "009901"
    assert bundle["data_kind"] == "user-supplied"
    assert str(tmp_path) not in str(bundle)


@pytest.mark.parametrize(
    "row",
    [
        ["990001", "2025-06-27", "nan", "CNY", "total_return", "synthetic"],
        ["990001", "2025-06-27", "1", "USD", "total_return", "synthetic"],
        ["990001", "2025-06-27", "1", "CNY", "unadjusted", "synthetic"],
        ["990002", "2025-06-27", "1", "CNY", "total_return", "synthetic"],
        ["990001", "2025-02-30", "1", "CNY", "total_return", "synthetic"],
    ],
)
def test_nav_csv_rejects_incompatible_evidence(tmp_path, row):
    path = write_csv(
        tmp_path / "nav.csv",
        [
            ["code", "date", "adjusted_nav", "currency", "adjustment", "source_id"],
            row,
        ],
    )
    with pytest.raises(DataError):
        load_csv_nav(path, ["990001"])


def test_nav_csv_rejects_duplicate_observations(tmp_path):
    row = ["990001", "2025-06-27", "1", "CNY", "total_return", "synthetic"]
    path = write_csv(
        tmp_path / "nav.csv",
        [
            ["code", "date", "adjusted_nav", "currency", "adjustment", "source_id"],
            row,
            row,
        ],
    )
    with pytest.raises(DataError, match="duplicate"):
        load_csv_nav(path, ["990001"])


def test_position_csv_rejects_duplicate_headers_and_accounts(tmp_path):
    for extra in ["name", "account"]:
        path = write_csv(
            tmp_path / "positions.csv",
            [
                ["code", "name", "market_value", "as_of", "venue", extra],
                ["990001", "Fictional", "1000", "2025-06-27", "synthetic", "x"],
            ],
        )
        with pytest.raises(DataError, match="headers"):
            portfolio_csv(path)
