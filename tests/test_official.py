import numpy as np
import pandas as pd
import pytest

from portfolio_lab.evidence import DataError
from portfolio_lab.official_efunds import cross_check_returns, merge_nav_scripts, parse_nav_script


def test_published_nav_string_is_parsed_without_executing_code():
    frame = parse_nav_script(
        'mk_123456_1y="0_1_2_3_4;20260101_0.2_1.1_1.2_1.0;20260102_0.3_1.2_1.3_1.0";', "123456"
    )
    assert frame.adjusted_nav.tolist() == [1.2, 1.3]
    with pytest.raises(DataError):
        parse_nav_script('mk_123456_all="0_2_1_3_4;20260101_1_1_1_1"', "123456")
    with pytest.raises(DataError):
        parse_nav_script('mk_123456_all="0_1_2_3_4";fetch("bad")', "123456")


def test_internal_conflict_and_independent_return_mismatch_fail():
    frame = pd.DataFrame(
        {
            "code": "123456",
            "date": pd.date_range("2026-01-01", periods=50),
            "adjusted_nav": np.arange(50) * 0.01 + 1,
        }
    )
    assert len(merge_nav_scripts(frame, frame)) == 50
    other = frame.copy()
    other.loc[25, "adjusted_nav"] *= 1.1
    with pytest.raises(DataError):
        merge_nav_scripts(frame, other)
    with pytest.raises(DataError):
        cross_check_returns(frame, other)
    # Total-return indexes may use different base levels; return agreement is the invariant.
    other = frame.copy()
    other.adjusted_nav *= 2
    assert cross_check_returns(frame, other)["maximum_return_difference"] < 1e-12
