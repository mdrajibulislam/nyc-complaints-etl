import math

import pandas as pd
import pytest

from dcwp_pipeline import analysis


def test_wilson_interval_brackets_the_point_estimate():
    low, high = analysis.wilson_interval(50, 100)
    assert low < 0.5 < high
    assert 0.0 <= low and high <= 1.0


def test_wilson_interval_is_wider_on_small_samples():
    """The whole reason ranking uses the lower bound."""
    small_low, small_high = analysis.wilson_interval(3, 4)
    large_low, large_high = analysis.wilson_interval(750, 1000)
    assert (small_high - small_low) > (large_high - large_low)
    # 75% of 4 must not outrank 75% of 1000 on the lower bound.
    assert small_low < large_low


def test_wilson_interval_handles_degenerate_inputs():
    assert analysis.wilson_interval(0, 0) == (0.0, 0.0)
    low, high = analysis.wilson_interval(0, 25)
    assert low == 0.0 and 0.0 < high < 1.0
    low, high = analysis.wilson_interval(25, 25)
    assert high == 1.0 and 0.0 < low < 1.0


def _complaints_frame():
    return pd.DataFrame(
        {
            "business_category": ["Big", "Small", "Tiny"],
            "complaints": [1000, 200, 20],
            "businesses": [100, 30, 5],
            "median_days_to_result": [30.0, 25.0, 10.0],
            "relief": [60, 20, 2],
            "no_relief": [40, 30, 3],
            "administrative": [400, 120, 15],
            "out_of_scope": [500, 30, 0],
            "unknown": [0, 0, 0],
            "substantive": [100, 50, 5],
        }
    )


def _charges_frame():
    return pd.DataFrame(
        {
            "business_category": ["Big", "Small"],
            "charge_records": [200, 5],
            "businesses_charged": [50, 3],
            "counts_charged": [400, 8],
            "counts_guilty": [350, 6],
            "adverse_records": [180, 4],
        }
    )


def test_category_profile_applies_volume_floor():
    profile = analysis.category_profile(_complaints_frame(), _charges_frame(), min_complaints=100)
    assert set(profile["business_category"]) == {"Big", "Small"}, "Tiny is below the floor"


def test_category_profile_fills_missing_charges_with_zero():
    profile = analysis.category_profile(
        _complaints_frame().head(2).assign(business_category=["Big", "NoCharges"]),
        _charges_frame().head(1),
        min_complaints=100,
    )
    row = profile.set_index("business_category").loc["NoCharges"]
    assert row["charge_records"] == 0
    assert row["charges_per_100_complaints"] == 0.0


def test_relief_rate_uses_substantive_denominator_not_all_complaints():
    profile = analysis.category_profile(_complaints_frame(), _charges_frame(), min_complaints=100)
    big = profile.set_index("business_category").loc["Big"]
    # 60 relief out of 100 substantive, not out of 1000 complaints.
    assert math.isclose(big["relief_rate"], 0.6, rel_tol=1e-9)


def test_ranking_is_by_lower_bound():
    profile = analysis.category_profile(_complaints_frame(), _charges_frame(), min_complaints=100)
    bounds = profile["admin_ci_low"].tolist()
    assert bounds == sorted(bounds, reverse=True)


def test_empty_input_returns_empty_not_error():
    empty = _complaints_frame().iloc[0:0]
    profile = analysis.category_profile(empty, _charges_frame(), min_complaints=100)
    assert profile.empty
    assert analysis.summarise(profile) == {"categories": 0}
