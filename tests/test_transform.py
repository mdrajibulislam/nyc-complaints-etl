import pandas as pd
import pytest

from dcwp_pipeline import transform


def test_classify_result_covers_each_bucket():
    assert transform.classify_result("Cash Amount - AMT") == "relief"
    assert transform.classify_result("Advised to Sue - ATS") == "no_relief"
    assert transform.classify_result("Requested Information Not Provided") == "administrative"
    assert transform.classify_result("No Jurisdiction") == "out_of_scope"
    assert transform.classify_result("Something DCWP Invented Later") == "unknown"
    assert transform.classify_result(None) == "unknown"


def test_result_buckets_do_not_overlap():
    """A result in two buckets gets counted twice."""
    buckets = [
        transform.RELIEF_RESULTS,
        transform.NO_RELIEF_RESULTS,
        transform.ADMINISTRATIVE_RESULTS,
        transform.OUT_OF_SCOPE_RESULTS,
    ]
    seen: set[str] = set()
    for bucket in buckets:
        overlap = seen & bucket
        assert not overlap, f"result appears in two buckets: {overlap}"
        seen |= bucket


def test_clean_complaints_dedupes_and_derives():
    raw = pd.DataFrame(
        {
            "record_id": ["1", "1", "2"],
            "business_unique_id": ["BA-1-2024", "BA-1-2024", "BA-2-2024"],
            "business_name": ["A", "A", "B"],
            "business_category": ["Restaurant", "Restaurant", None],
            "result": ["Cash Amount - AMT", "Cash Amount - AMT", "Insufficient Info Received"],
            "intake_date": ["2024-01-01", "2024-01-01", "2024-02-01"],
            "result_date": ["2024-01-11", "2024-01-11", "2024-01-01"],
        }
    )
    out = transform.clean_complaints(raw)

    assert len(out) == 2, "duplicate record_id should collapse"
    assert out.loc[out.record_id == "1", "days_to_result"].iloc[0] == 10
    # result_date before intake_date is an error, not a 31-day turnaround.
    assert pd.isna(out.loc[out.record_id == "2", "days_to_result"].iloc[0])
    assert out.loc[out.record_id == "2", "business_category"].iloc[0] == "Unknown"


def test_clean_charges_caps_guilty_at_charge_count():
    """`guilty` is a count of counts, so it can never exceed charge_count."""
    raw = pd.DataFrame(
        {
            "record_id": ["1", "2"],
            "business_unique_id": ["BA-1-2024", "BA-2-2024"],
            "business_name": ["A", "B"],
            "business_category": ["Restaurant", "Car Wash"],
            "charge": ["x", "y"],
            "charge_count": ["3", "1"],
            "guilty": ["20", None],
            "outcome": ["Pleaded", "Charges Withdrawn"],
            "violation_date": ["2024-01-01", "2024-02-01"],
        }
    )
    out = transform.clean_charges(raw)

    assert out.loc[out.record_id == "1", "guilty"].iloc[0] == 3
    assert out.loc[out.record_id == "2", "guilty"].iloc[0] == 0
    assert out.loc[out.record_id == "1", "is_adverse"].iloc[0] == 1
    assert out.loc[out.record_id == "2", "is_adverse"].iloc[0] == 0


def test_business_bridge_marks_uncharged_businesses():
    complaints = transform.clean_complaints(
        pd.DataFrame(
            {
                "record_id": ["1", "2"],
                "business_unique_id": ["BA-1-2024", "BA-2-2024"],
                "business_name": ["A", "B"],
                "business_category": ["Restaurant", "Car Wash"],
                "result": ["Cash Amount - AMT", "Insufficient Info Received"],
                "intake_date": ["2024-01-01", "2024-02-01"],
                "result_date": ["2024-01-05", "2024-02-05"],
            }
        )
    )
    charges = transform.clean_charges(
        pd.DataFrame(
            {
                "record_id": ["9"],
                "business_unique_id": ["BA-1-2024"],
                "business_name": ["A"],
                "business_category": ["Restaurant"],
                "charge": ["x"],
                "charge_count": ["2"],
                "guilty": ["2"],
                "outcome": ["Pleaded"],
                "violation_date": ["2024-03-01"],
            }
        )
    )
    bridge = transform.build_business_bridge(complaints, charges)

    assert set(bridge["business_unique_id"]) == {"BA-1-2024", "BA-2-2024"}
    assert bridge.set_index("business_unique_id").loc["BA-1-2024", "ever_charged"] == 1
    assert bridge.set_index("business_unique_id").loc["BA-2-2024", "ever_charged"] == 0
