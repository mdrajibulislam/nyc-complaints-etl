"""Transformations from raw DCWP records into the analytic model.

The substantive modelling decision in this file is the outcome taxonomy below.
DCWP records 34 distinct ``result`` values on consumer complaints, and they do
not mean comparable things: "Cash Amount - AMT" is a consumer getting money
back, while "Requested Information Not Provided" is a case dying because the
consumer stopped replying. Collapsing all 34 into a single "resolved" rate
would produce a number that looks precise and means nothing.

The four buckets are:

``relief``
    The consumer demonstrably got something - money, a refund, a cancelled
    contract, repaired or replaced goods.
``no_relief``
    The complaint was worked to a substantive conclusion and the consumer got
    nothing, including being told to sue.
``administrative``
    The complaint ended on process rather than merits - missing information,
    no response, duplicate, withdrawn.
``out_of_scope``
    DCWP referred it elsewhere, had no jurisdiction, or only provided
    information. These are excluded from rate denominators entirely.

The mapping is a judgement call and is deliberately in one readable constant so
a reviewer can disagree with a specific assignment and re-run.
"""

from __future__ import annotations

import pandas as pd

RELIEF_RESULTS = {
    "Cash Amount - AMT",
    "Credit Card Refund and/or Contract Cancelled - CRC",
    "Resolved and Consumer Satisfied - SPF",
    "Bill Reduced - BLR",
    "Store Credit - SCR",
    "Goods Repaired - GRS",
    "Goods Received - GDR",
    "Goods Exchanged - GEX",
    "Agency Collected Judgement - ACJ",
}

NO_RELIEF_RESULTS = {
    "No Satisfactory Agreement - NSA",
    "No Business Response - NVR",
    "Advised to Sue - ATS",
    "Unable to Locate Business- ULV",
    "Out of Business - OOB",
}

ADMINISTRATIVE_RESULTS = {
    "Requested Information Not Provided",
    "Insufficient Info Received",
    "No Consumer Response - NCR",
    "Duplicate Complaint - DUP",
    "Wrong Business and Null and Void - NUL",
    "Complaint Invalid - CIN",
    "Consumer Withdrew Complaint - CWC",
    "Unable to Locate Customer - ULC",
    "Technical Problem",
}

OUT_OF_SCOPE_RESULTS = {
    "Referred",
    "Referred to Outside - RTO",
    "Referred to Manufacturer - RMF",
    "Referred to Hearing - RTH",
    "No Jurisdiction",
    "Information Provided",
    "Complaint Review Complete",
    "Business Reported",
    "Inspection Requested",
    "Consumer Took Action - CTA",
    "Provider Feedback Received",
}

# Outcomes on the charges side where DCWP prevailed on at least one count.
ADVERSE_OUTCOMES = {"Default Decision", "Pleaded", "Hearing Decision"}


def classify_result(result: str | None) -> str:
    if result is None or (isinstance(result, float) and pd.isna(result)):
        return "unknown"
    text = str(result).strip()
    if text in RELIEF_RESULTS:
        return "relief"
    if text in NO_RELIEF_RESULTS:
        return "no_relief"
    if text in ADMINISTRATIVE_RESULTS:
        return "administrative"
    if text in OUT_OF_SCOPE_RESULTS:
        return "out_of_scope"
    return "unknown"


def clean_complaints(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["intake_date"] = pd.to_datetime(df.get("intake_date"), errors="coerce")
    df["result_date"] = pd.to_datetime(df.get("result_date"), errors="coerce")

    for col in ("record_id", "business_unique_id", "business_name", "business_category", "result"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    df["business_category"] = df["business_category"].fillna("Unknown")
    df["outcome_class"] = df["result"].map(classify_result)

    # Days to disposition, where both ends are known. Negative values would
    # indicate a data error rather than a fast resolution, so they are dropped.
    delta = (df["result_date"] - df["intake_date"]).dt.days
    df["days_to_result"] = delta.where(delta >= 0)

    df = df[df["record_id"].notna() & (df["record_id"] != "")]

    # 134 record_ids appear twice, almost always because the same complaint was
    # filed against two spellings of one business ("Paypal Inc" / "PayPal,
    # Inc."). Keeping the first occurrence is correct: it is one complaint.
    return df.drop_duplicates(subset=["record_id"])


def clean_charges(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["violation_date"] = pd.to_datetime(df.get("violation_date"), errors="coerce")

    for col in ("record_id", "business_unique_id", "business_name", "business_category", "outcome", "charge"):
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    # `guilty` is a COUNT of counts found guilty, not a boolean - values run
    # from 1 to 20 in the source. Treating it as a flag would badly overstate
    # single-count cases and understate multi-count ones.
    df["charge_count"] = pd.to_numeric(df.get("charge_count"), errors="coerce").fillna(0).astype(int)
    df["guilty"] = pd.to_numeric(df.get("guilty"), errors="coerce").fillna(0).astype(int)
    df["guilty"] = df[["guilty", "charge_count"]].min(axis=1)

    df["business_category"] = df["business_category"].fillna("Unknown")
    df["is_adverse"] = df["outcome"].isin(ADVERSE_OUTCOMES).astype(int)

    df = df[df["record_id"].notna() & (df["record_id"] != "")]

    # `record_id` is the adjudication CASE id (e.g. "0001-2026-ADJC"), not a row
    # key: one case carries a line per charge brought, 143,146 rows across 56,290
    # cases. The grain is (case, charge). Deduplicating on record_id alone would
    # silently discard ~60% of the charges in the dataset.
    return df.drop_duplicates(subset=["record_id", "charge"])


def complaints_by_category(complaints: pd.DataFrame) -> pd.DataFrame:
    """One row per business category with outcome-class counts."""
    pivot = (
        complaints.pivot_table(
            index="business_category",
            columns="outcome_class",
            values="record_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )
    for col in ("relief", "no_relief", "administrative", "out_of_scope", "unknown"):
        if col not in pivot.columns:
            pivot[col] = 0

    totals = (
        complaints.groupby("business_category", as_index=False)
        .agg(
            complaints=("record_id", "nunique"),
            businesses=("business_unique_id", "nunique"),
            median_days_to_result=("days_to_result", "median"),
        )
    )

    out = totals.merge(pivot, on="business_category", how="left")
    # Complaints that reached a decision on the merits, either way.
    out["substantive"] = out["relief"] + out["no_relief"]
    return out


def charges_by_category(charges: pd.DataFrame) -> pd.DataFrame:
    return (
        charges.groupby("business_category", as_index=False)
        .agg(
            charge_records=("record_id", "nunique"),
            businesses_charged=("business_unique_id", "nunique"),
            counts_charged=("charge_count", "sum"),
            counts_guilty=("guilty", "sum"),
            adverse_records=("is_adverse", "sum"),
        )
    )


def build_business_bridge(complaints: pd.DataFrame, charges: pd.DataFrame) -> pd.DataFrame:
    """Businesses that appear in both datasets, joined on business_unique_id.

    This is the link that makes the two sources one story: it answers whether a
    business consumers complained about was ever actually charged.
    """
    comp = (
        complaints.dropna(subset=["business_unique_id"])
        .groupby("business_unique_id", as_index=False)
        .agg(
            business_name=("business_name", "first"),
            business_category=("business_category", "first"),
            complaints=("record_id", "nunique"),
            relief=("outcome_class", lambda s: int((s == "relief").sum())),
            administrative=("outcome_class", lambda s: int((s == "administrative").sum())),
        )
    )
    chg = (
        charges.dropna(subset=["business_unique_id"])
        .groupby("business_unique_id", as_index=False)
        .agg(
            charge_records=("record_id", "nunique"),
            counts_charged=("charge_count", "sum"),
            counts_guilty=("guilty", "sum"),
        )
    )
    bridge = comp.merge(chg, on="business_unique_id", how="left")
    for col in ("charge_records", "counts_charged", "counts_guilty"):
        bridge[col] = bridge[col].fillna(0).astype(int)
    bridge["ever_charged"] = (bridge["charge_records"] > 0).astype(int)
    return bridge
