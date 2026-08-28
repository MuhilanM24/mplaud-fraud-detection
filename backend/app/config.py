"""Central configuration: every threshold used by the risk system lives here.

These values are surfaced via /api/meta so the UI and README can display them,
and several are runtime-overridable via environment variables so deployments
can tune sensitivity without code changes.
"""
from __future__ import annotations

import os


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Guardrail: this system NEVER declares fraud. Only risk scores + routing.
# ---------------------------------------------------------------------------
SYSTEM_NAME = "MPLAUD — MPLADS Risk Intelligence & Early Warning System"
GUARDRAIL_TEXT = (
    "This system never declares fraud. Every output is a risk signal for human "
    "investigation. All alerts route to investigators who make the final call."
)

# ---------------------------------------------------------------------------
# Rule engine (deterministic, independent of ML)
# ---------------------------------------------------------------------------
# MPLADS guideline: final payment may be released only after >= 75% physical
# completion (interim payments per Government accounting norms).
RULE_COMPLETION_MIN_PCT = _f("MPLAUD_RULE_COMPLETION_MIN_PCT", 75.0)
RULE_COMPLETION_WEIGHT = _f("MPLAUD_RULE_COMPLETION_WEIGHT", 60.0)      # max points
# "Insufficient evidence" rule: weak geo-tag match AND almost no site photos.
RULE_GEO_MATCH_MIN = _f("MPLAUD_RULE_GEO_MATCH_MIN", 0.50)
RULE_PHOTOS_MIN = _i("MPLAUD_RULE_PHOTOS_MIN", 2)
RULE_EVIDENCE_WEIGHT = _f("MPLAUD_RULE_EVIDENCE_WEIGHT", 35.0)         # max points

# ---------------------------------------------------------------------------
# Anomaly detection (Isolation Forest)
# ---------------------------------------------------------------------------
IF_N_ESTIMATORS = _i("MPLAUD_IF_N_ESTIMATORS", 300)
IF_CONTAMINATION = _f("MPLAUD_IF_CONTAMINATION", 0.10)
IF_RANDOM_STATE = 42

# ---------------------------------------------------------------------------
# Risk fusion weights (sum normalised at runtime over available components)
# ---------------------------------------------------------------------------
FUSION_WEIGHTS = {
    "rules": _f("MPLAUD_W_RULES", 0.42),
    "ml_anomaly": _f("MPLAUD_W_ML", 0.26),
    "agency_history": _f("MPLAUD_W_AGENCY", 0.16),
    "fund_flow": _f("MPLAUD_W_FUNDFLOW", 0.10),
    "duplicates": _f("MPLAUD_W_DUP", 0.06),
}

# Band boundaries (0-100). "Flagged for investigation" = High or Critical.
BANDS = [
    ("Low", 0.0, 25.0),
    ("Moderate", 25.0, 50.0),
    ("High", 50.0, 75.0),
    ("Critical", 75.0, 100.01),
]
FLAGGED_BANDS = os.environ.get("MPLAUD_FLAGGED_BANDS", "High,Critical")

# Score-floor escalation policy: fund-flow anomalies can be invisible at
# project level (completion % looks compliant), so structural money-trail
# findings escalate the fused score to at least the High band:
#   * major floor  — structuring, or leakage beyond LEAKAGE_FLOOR_PCT
#   * minor floor  — stage delay / missing utilization certificate
FUND_FLOW_FLOOR_SCORE = _f("MPLAUD_FUNDFLOW_FLOOR", 60.0)      # major -> Critical-adjacent High
FUND_FLOW_FLOOR_MINOR = _f("MPLAUD_FUNDFLOW_FLOOR_MINOR", 55.0)  # minor -> lower High

# ---------------------------------------------------------------------------
# Fund-flow (payment ledger) analytics
# ---------------------------------------------------------------------------
STAGES = [
    "SANCTION",
    "DISTRICT_RELEASE",
    "AGENCY_RELEASE",
    "VENDOR_PAYMENT",
    "UTILIZATION_CERTIFICATE",
]
# Leakage / skimming: amount shrinking between consecutive hand-offs.
LEAKAGE_TOLERANCE_PCT = _f("MPLAUD_LEAKAGE_TOL_PCT", 2.0)
LEAKAGE_FLOOR_PCT = _f("MPLAUD_LEAKAGE_FLOOR_PCT", 10.0)   # triggers score floor
# Funds parked: gap in days between consecutive stages.
STAGE_DELAY_DAYS = _i("MPLAUD_STAGE_DELAY_DAYS", 200)
# Structuring: several payments just under an approval/scrutiny threshold.
STRUCTURING_THRESHOLD = _f("MPLAUD_STRUCTURING_THRESHOLD", 500000.0)  # Rs 5 lakh
STRUCTURING_MIN_PAYMENTS = _i("MPLAUD_STRUCTURING_MIN_PAYMENTS", 3)
STRUCTURING_JUST_UNDER_RATIO = _f("MPLAUD_STRUCTURING_JUST_UNDER", 0.85)
STRUCTURING_WINDOW_DAYS = _i("MPLAUD_STRUCTURING_WINDOW_DAYS", 30)
# Utilization certificate must follow vendor payment within this window.
UC_WINDOW_DAYS = _i("MPLAUD_UC_WINDOW_DAYS", 90)

# Flag weights inside the fund-flow component (0-100, capped)
FUNDFLOW_FLAG_WEIGHTS = {
    "leakage": 45.0,
    "structuring": 45.0,
    "stage_delay": 35.0,
    "missing_uc": 30.0,
}

# ---------------------------------------------------------------------------
# Duplicate-work detection
# ---------------------------------------------------------------------------
DUP_SIM_THRESHOLD_SBERT = _f("MPLAUD_DUP_SIM_SBERT", 0.82)
DUP_SIM_THRESHOLD_TFIDF = _f("MPLAUD_DUP_SIM_TFIDF", 0.66)
DUP_DISTANCE_KM = _f("MPLAUD_DUP_DIST_KM", 1.5)      # DBSCAN eps (haversine, km)
DUP_DBSCAN_MIN_SAMPLES = _i("MPLAUD_DUP_DBSCAN_MIN", 1)
# NLP backend: auto | sbert | tfidf
NLP_BACKEND = os.environ.get("MPLAUD_NLP_BACKEND", "auto")

# ---------------------------------------------------------------------------
# Surrogate explainability
# ---------------------------------------------------------------------------
SURROGATE_MIN_ROWS = _i("MPLAUD_SURROGATE_MIN_ROWS", 50)   # below this, BYO data
# uses statistical deviation ranking instead of surrogate SHAP.

# ---------------------------------------------------------------------------
# Prediction models
# ---------------------------------------------------------------------------
OVERRUN_FLAG_RATIO = _f("MPLAUD_OVERRUN_FLAG_RATIO", 1.15)  # predicted final/sanctioned
DELAY_FLAG_DAYS = _i("MPLAUD_DELAY_FLAG_DAYS", 90)

# ---------------------------------------------------------------------------
# Synthetic demo data
# ---------------------------------------------------------------------------
DEMO_SEED = _i("MPLAUD_DEMO_SEED", 42)
DEMO_AS_OF = "2024-06-30"   # "today" for the synthetic dataset
N_NORMAL_PROJECTS = 180

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DATA_DIR = os.environ.get("MPLAUD_DATA_DIR",
                           os.path.join(os.path.dirname(os.path.dirname(
                               os.path.abspath(__file__))), "data"))
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(DATA_DIR, "mplaud.db"))


def band_for(score: float) -> str:
    for name, lo, hi in BANDS:
        if lo <= score < hi:
            return name
    return "Critical"


def is_flagged_band(band: str) -> bool:
    return band in [b.strip() for b in FLAGGED_BANDS.split(",")]
