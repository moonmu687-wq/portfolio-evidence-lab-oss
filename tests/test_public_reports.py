from copy import deepcopy

import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.public_reports import select_report, validate_page


def entry():
    return dict(
        FUNDCODE="123456",
        ID="AN2026083112345",
        TITLE="某基金2026年中期报告",
        PUBLISHDATEDesc="2026-08-31",
        PUBLISHDATE="2026-08-31T00:00:00",
        ATTACHTYPE="0",
    )


def test_report_identity_and_page_completeness_are_required():
    payload = dict(ErrCode=0, PageIndex=1, PageSize=20, TotalCount=1, Data=[entry()])
    assert validate_page(payload, "123456", 1)[1] == 1
    for key, value in [("PageIndex", 2), ("PageSize", 100), ("TotalCount", 2), ("ErrCode", 1)]:
        broken = deepcopy(payload)
        broken[key] = value
        with pytest.raises(DataError):
            validate_page(broken, "123456", 1)
    for key, value in [("FUNDCODE", "654321"), ("ID", "../../bad"), ("PUBLISHDATE", "2026-09-01")]:
        broken = deepcopy(payload)
        broken["Data"][0][key] = value
        with pytest.raises(DataError):
            validate_page(broken, "123456", 1)


def test_report_selection_rejects_lookahead_ambiguity_and_notice_only():
    row = entry()
    assert select_report([row], "123456", "2026年中期报告", "2026-09-21") == row
    with pytest.raises(DataError):
        select_report([row], "123456", "2026年中期报告", "2026-08-30")
    with pytest.raises(DataError):
        select_report([row, row], "123456", "2026年中期报告", "2026-09-21")
    row["TITLE"] = "提示性公告：某基金2026年中期报告"
    with pytest.raises(DataError):
        select_report([row], "123456", "2026年中期报告", "2026-09-21")
