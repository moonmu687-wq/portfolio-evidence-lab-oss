from copy import deepcopy

import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.official_sse import SQL_ID, validate_page


def test_exchange_filings_reject_wrong_identity_and_pagination():
    rows = [
        {
            "SECURITY_CODE": "123456",
            "SSEDATE": "2026-08-31",
            "TITLE": "2026年中期报告",
            "URL": "/disclosure/fund/announcement/test.pdf",
        }
    ]
    payload = {
        "sqlId": SQL_ID,
        "result": rows,
        "pageHelp": {"pageNo": 1, "data": rows, "total": 1, "pageCount": 1},
    }
    assert validate_page(payload, "123456", 1, "2026-08-01", "2026-09-01")[0] == rows
    for code, page, end in [
        ("654321", 1, "2026-09-01"),
        ("123456", 2, "2026-09-01"),
        ("123456", 1, "2026-08-30"),
    ]:
        with pytest.raises(DataError):
            validate_page(payload, code, page, "2026-08-01", end)
    bad = deepcopy(payload)
    bad["result"][0]["URL"] = "https://unrelated.example/report.pdf"
    with pytest.raises(DataError):
        validate_page(bad, "123456", 1, "2026-08-01", "2026-09-01")
