"""Feature engineering for the anomaly / surrogate / prediction models.

The 8 primary anomaly features (per the system specification):
  1. completion_pct_at_payment
  2. days_sanction_to_payment
  3. geo_tag_match_score
  4. site_photos_uploaded
  5. cost_per_unit_ratio
  6. agency_prior_flagged_count
  7. round_number_bill (0/1)
  8. nearby_duplicate_count (from the duplicate pre-pass)

Extra context features used by the surrogate / prediction models are appended
(they carry signal the fusion consumed, so the surrogate can reproduce it).

Works on partial data: any feature missing from the source dataframe is
dropped from the matrix and reported, so bring-your-own datasets with only the
required 4 columns still get an Isolation Forest over those features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ANOMALY_FEATURES = [
    "completion_pct_at_payment",
    "days_sanction_to_payment",
    "geo_tag_match_score",
    "site_photos_uploaded",
    "cost_per_unit_ratio",
    "agency_prior_flagged_count",
    "round_number_bill",
    "nearby_duplicate_count",
]

# Extra features for the surrogate / prediction models (all optional).
CONTEXT_FEATURES = [
    "sanctioned_amount_lakh",
    "district_delay_baseline",
    "agency_delay_rate",
]

REQUIRED_COLUMNS = ["project_id", "completion_pct_at_payment",
                    "geo_tag_match_score", "site_photos_uploaded"]

OPTIONAL_COLUMNS = [
    "work_description", "sanctioned_amount", "days_sanction_to_payment",
    "cost_per_unit_ratio", "agency_prior_flagged_count", "district", "agency",
    "work_type", "mp_name", "geo_lat", "geo_lon", "sanctioned_date",
    "payment_date", "completion_pct_final", "final_cost", "round_number_bill",
    "expected_duration_days", "actual_delay_days",
]


def build_matrix(df: pd.DataFrame,
                 agency_stats: dict | None = None,
                 district_baseline: dict | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Return (feature_matrix, used_columns). Missing features are skipped."""
    work = df.copy()
    # numeric coercion with NaN tolerance
    for col in ANOMALY_FEATURES + CONTEXT_FEATURES:
        if col in work.columns:
            work[col] = pd.to_numeric(work[col], errors="coerce")

    if "sanctioned_amount" in work.columns:
        work["sanctioned_amount_lakh"] = pd.to_numeric(
            work["sanctioned_amount"], errors="coerce") / 1e5
    if "round_number_bill" in work.columns:
        work["round_number_bill"] = pd.to_numeric(
            work["round_number_bill"], errors="coerce").fillna(0).astype(int)

    # context enrichment from provided lookups (optional)
    if district_baseline is not None and "district" in work.columns:
        work["district_delay_baseline"] = work["district"].map(
            lambda d: district_baseline.get(d, np.nan))
    if agency_stats is not None and "agency" in work.columns:
        work["agency_delay_rate"] = work["agency"].map(
            lambda a: (agency_stats.get(a) or {}).get("delay_rate", np.nan))

    used = [c for c in ANOMALY_FEATURES + CONTEXT_FEATURES
            if c in work.columns and work[c].notna().any()]
    matrix = work[used].fillna(work[used].median(numeric_only=True)).fillna(0.0)
    return matrix, used


# Human-readable names + direction hints for explanations.
FEATURE_LABELS = {
    "completion_pct_at_payment":
        ("Physical completion % when payment was released",
         "low values increase risk — MPLADS requires >= 75% before payment"),
    "days_sanction_to_payment":
        ("Days from sanction to payment",
         "both unusually fast and unusually slow payments increase risk"),
    "geo_tag_match_score":
        ("Geo-tag match confidence",
         "low confidence increases risk — work may not exist at the tagged site"),
    "site_photos_uploaded":
        ("Site photos uploaded",
         "few or no photos increase risk — no documentary evidence of work"),
    "cost_per_unit_ratio":
        ("Cost per unit vs regional benchmark",
         "values far above 1.0 increase risk — possible over-invoicing"),
    "agency_prior_flagged_count":
        ("Prior flags on the implementing agency",
         "repeat-flagged agencies increase risk of every new project"),
    "round_number_bill":
        ("Round-number bill amount",
         "suspiciously round bill amounts slightly increase risk"),
    "nearby_duplicate_count":
        ("Nearby very-similar sanctioned works",
         "similar works within 1.5 km increase duplicate-claim risk"),
    "sanctioned_amount_lakh":
        ("Sanctioned amount (Rs lakh)",
         "contributes context on project size"),
    "district_delay_baseline":
        ("District baseline delay rate",
         "districts with slow historical completion increase delay risk"),
    "agency_delay_rate":
        ("Agency historical delay rate",
         "agencies with slow history increase delay risk"),
}
