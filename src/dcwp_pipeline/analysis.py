"""Hypothesis generation with explicit uncertainty bounds.

The screening question:

    Do consumer complaints to DCWP die on process rather than merits at
    materially different rates across business categories, and is a category's
    enforcement footprint proportional to the complaints it generates?

Two cautions drive the implementation.

1.  **Rates on small denominators are not comparable to rates on large ones.**
    A category with 11 complaints and 6 administrative closures has a 55% rate
    and tells us nothing. Every rate here carries a Wilson score interval, and
    the ranking uses the interval's lower bound so a category only surfaces
    when even the pessimistic reading is high.

2.  **This is descriptive, not causal.** A high administrative-closure rate is
    consistent with a category where complainants are harder to reach, with
    complaints that are weaker on arrival, with businesses that stonewall, or
    with uneven casework. Nothing here distinguishes those. The output is a
    list of places worth looking - a hypothesis - and says so wherever it is
    written out.
"""

from __future__ import annotations

import math

import pandas as pd

Z_95 = 1.959963985


def wilson_interval(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal approximation: it stays inside [0, 1] and behaves
    sensibly when ``successes`` is 0 or equals ``trials``, both common in the
    long tail of small categories.
    """
    if trials <= 0:
        return (0.0, 0.0)
    p = successes / trials
    denominator = 1 + z**2 / trials
    centre = p + z**2 / (2 * trials)
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * trials)) / trials)
    return (
        max(0.0, (centre - margin) / denominator),
        min(1.0, (centre + margin) / denominator),
    )


def _add_rate(df: pd.DataFrame, successes: str, trials: str, prefix: str) -> pd.DataFrame:
    """Attach point estimate and 95% Wilson bounds for successes/trials."""
    bounds = df.apply(
        lambda r: wilson_interval(int(r[successes]), int(r[trials])), axis=1, result_type="expand"
    )
    # Zero trials yields NaN rather than a divide-by-zero or a misleading 0.0.
    trials_safe = df[trials].astype(float).where(df[trials].astype(float) > 0)
    df[f"{prefix}_rate"] = df[successes].astype(float) / trials_safe
    df[f"{prefix}_ci_low"] = bounds[0]
    df[f"{prefix}_ci_high"] = bounds[1]
    return df


def category_profile(
    complaints: pd.DataFrame, charges: pd.DataFrame, min_complaints: int = 100
) -> pd.DataFrame:
    """Per-category rates with uncertainty, filtered to analysable volume.

    ``min_complaints`` is a parameter, not a constant, because the right floor
    is a judgement a reviewer should be able to change and re-run.
    """
    df = complaints.merge(charges, on="business_category", how="left")
    for col in ("charge_records", "businesses_charged", "counts_charged", "counts_guilty", "adverse_records"):
        if col in df.columns:
            df[col] = df[col].fillna(0).astype(int)
        else:
            df[col] = 0

    df = df[df["complaints"] >= min_complaints].copy()
    if df.empty:
        return df

    df = _add_rate(df, "administrative", "complaints", "admin")
    df["substantive"] = df["substantive"].astype(int)
    df = _add_rate(df, "relief", "substantive", "relief")

    df["charges_per_100_complaints"] = df["charge_records"] / df["complaints"] * 100
    df["guilty_per_100_complaints"] = df["counts_guilty"] / df["complaints"] * 100

    overall_admin = df["administrative"].sum() / max(df["complaints"].sum(), 1)
    df["baseline_admin_rate"] = overall_admin
    df["admin_vs_baseline"] = df["admin_rate"] / overall_admin if overall_admin else pd.NA

    # The enforcement gap: categories that generate a lot of complaints but
    # comparatively few charges. Rank distance is used rather than a ratio so
    # that categories with zero charges do not divide by zero.
    df["rank_complaints"] = df["complaints"].rank(ascending=False, method="min")
    df["rank_enforcement"] = df["charges_per_100_complaints"].rank(ascending=False, method="min")
    df["enforcement_gap"] = df["rank_enforcement"] - df["rank_complaints"]

    return df.sort_values("admin_ci_low", ascending=False).reset_index(drop=True)


def bridge_summary(bridge: pd.DataFrame) -> dict:
    """How often a complained-about business was ever charged."""
    if bridge.empty:
        return {"businesses": 0}
    total = len(bridge)
    charged = int(bridge["ever_charged"].sum())
    low, high = wilson_interval(charged, total)
    return {
        "businesses": total,
        "ever_charged": charged,
        "ever_charged_rate": round(charged / total, 4),
        "ever_charged_ci": (round(low, 4), round(high, 4)),
        "complaints_covered": int(bridge["complaints"].sum()),
    }


def summarise(profile: pd.DataFrame) -> dict:
    if profile.empty:
        return {"categories": 0}
    return {
        "categories": int(len(profile)),
        "complaints": int(profile["complaints"].sum()),
        "baseline_admin_rate": round(float(profile["baseline_admin_rate"].iloc[0]), 4),
        "highest_admin_category": profile.iloc[0]["business_category"],
        "highest_admin_rate": round(float(profile.iloc[0]["admin_rate"]), 4),
        "lowest_admin_category": profile.iloc[-1]["business_category"],
        "lowest_admin_rate": round(float(profile.iloc[-1]["admin_rate"]), 4),
    }


def to_markdown(profile: pd.DataFrame, summary: dict, bridge: dict, top_n: int = 20) -> str:
    lines = [
        "# Hypothesis: where consumer complaints stop short of a decision",
        "",
        "**This is a screening output, not a finding.** Categories are ranked by the",
        "lower bound of a 95% Wilson interval on the share of complaints closed for",
        "administrative reasons - missing information, no response, withdrawal - rather",
        "than on the merits. Ranking by the lower bound keeps small categories from",
        "topping the list on noise.",
        "",
        "Confounders not controlled for: complaint quality on arrival, how reachable",
        "complainants in a category are, whether some categories attract more",
        "speculative complaints, and DCWP casework priorities. A high rank is a reason",
        "to look closer, nothing more.",
        "",
        "## Summary",
        "",
    ]
    if not summary.get("categories"):
        return "\n".join(lines + ["No category met the minimum-volume threshold."]) + "\n"

    lines += [
        f"- Categories analysed: **{summary['categories']}**",
        f"- Complaints covered: **{summary['complaints']:,}**",
        f"- Baseline administrative-closure rate: **{summary['baseline_admin_rate']:.1%}**",
        f"- Highest: **{summary['highest_admin_category']}** at "
        f"**{summary['highest_admin_rate']:.1%}**",
        f"- Lowest: **{summary['lowest_admin_category']}** at "
        f"**{summary['lowest_admin_rate']:.1%}**",
        "",
    ]
    if bridge.get("businesses"):
        low, high = bridge["ever_charged_ci"]
        lines += [
            f"- Of **{bridge['businesses']:,}** businesses with a consumer complaint, "
            f"**{bridge['ever_charged']:,}** ({bridge['ever_charged_rate']:.1%}, "
            f"95% CI {low:.1%}-{high:.1%}) were ever charged by DCWP.",
            "",
        ]

    lines += [
        f"## Administrative closure by category (top {top_n})",
        "",
        "| Category | Complaints | Admin closed | Rate | 95% CI | vs baseline | Charges/100 | Gap |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, r in profile.head(top_n).iterrows():
        multiple = r["admin_vs_baseline"]
        lines.append(
            f"| {r['business_category']} | {int(r['complaints']):,} | "
            f"{int(r['administrative']):,} | {r['admin_rate']:.1%} | "
            f"{r['admin_ci_low']:.1%}-{r['admin_ci_high']:.1%} | "
            f"{multiple:.2f}x | {r['charges_per_100_complaints']:.1f} | "
            f"{int(r['enforcement_gap']):+d} |"
        )

    lines += [
        "",
        "`Gap` is the category's rank by enforcement intensity minus its rank by",
        "complaint volume. A large positive gap means the category generates many",
        "complaints relative to the charges DCWP brings in it. That is the column",
        "worth a second look.",
        "",
    ]
    return "\n".join(lines) + "\n"
