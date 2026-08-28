"""Deterministic rule engine — completely independent of any ML component.

Every violation is explainable on its own, in plain language, with the exact
thresholds that fired. Rules are evaluated per project; rules whose inputs are
missing are reported as "not evaluable" rather than silently passed (important
for bring-your-own datasets with missing optional fields).
"""
from __future__ import annotations

from . import config

R_COMPLETION = "R1_COMPLETION_BEFORE_PAYMENT"
R_EVIDENCE = "R2_INSUFFICIENT_EVIDENCE"


def _fmt_lakh(amount) -> str:
    try:
        v = float(amount)
        return f"Rs {v/1e5:.1f} lakh"
    except (TypeError, ValueError):
        return "the sanctioned amount"


def evaluate_rules(project: dict) -> list[dict]:
    """Return a list of rule violations (empty list = no violations).

    Each violation: {rule_id, title, detail, weight, severity, evidence}.
    """
    violations: list[dict] = []
    comp = project.get("completion_pct_at_payment")
    comp_missing = comp is None or (isinstance(comp, float) and comp != comp)
    amount = project.get("sanctioned_amount")

    # --- R1: MPLADS 75% physical-completion-before-payment rule -------------
    if comp_missing:
        pass  # surfaced as a rule-gap in the notes, not a violation
    else:
        comp = float(comp)
        if comp < config.RULE_COMPLETION_MIN_PCT:
            # severity scales with how far below the threshold
            deficit = config.RULE_COMPLETION_MIN_PCT - comp
            severity = "severe" if deficit > 60 else (
                "major" if deficit > 25 else "borderline")
            weight = config.RULE_COMPLETION_WEIGHT * (
                0.75 if severity == "borderline" else 1.0)
            title = ("Payment released before the mandatory 75% physical "
                     "completion threshold (MPLADS guideline)")
            detail = (f"{_fmt_lakh(amount)} was paid on "
                      f"{project.get('payment_date', '(date unknown)')} when "
                      f"recorded physical completion was only {comp:.1f}% "
                      f"(rule requires >= {config.RULE_COMPLETION_MIN_PCT:.0f}%). "
                      f"Gap to threshold: {deficit:.1f} percentage points.")
            if comp <= 15:
                detail += (" Near-zero completion at payment mirrors the "
                           "documented 2023 Barpeta (Assam) MPLAD case, where "
                           "bills were paid for roads never built.")
            violations.append({
                "rule_id": R_COMPLETION, "title": title, "detail": detail,
                "weight": weight, "severity": severity,
                "evidence": {"completion_pct_at_payment": comp,
                             "threshold": config.RULE_COMPLETION_MIN_PCT,
                             "payment_date": project.get("payment_date"),
                             "sanctioned_amount": amount},
            })

    # --- R2: insufficient evidence (weak geo-tag + few/no photos) ------------
    geo = project.get("geo_tag_match_score")
    photos = project.get("site_photos_uploaded")
    geo_missing = geo is None or (isinstance(geo, float) and geo != geo)
    photos_missing = photos is None or (isinstance(photos, float) and photos != photos)
    if not geo_missing and not photos_missing:
        geo, photos = float(geo), float(photos)
        if geo < config.RULE_GEO_MATCH_MIN and photos < config.RULE_PHOTOS_MIN:
            violations.append({
                "rule_id": R_EVIDENCE,
                "title": "Insufficient site evidence (geo-tag mismatch + no site photos)",
                "detail": (f"Geo-tag match confidence is {geo:.2f} "
                           f"(below {config.RULE_GEO_MATCH_MIN:.2f}) and only "
                           f"{int(photos)} site photo(s) were uploaded "
                           f"(minimum expected: {config.RULE_PHOTOS_MIN}). There "
                           "is little documentary evidence the work exists on "
                           "the ground."),
                "weight": config.RULE_EVIDENCE_WEIGHT,
                "severity": "major" if (geo < 0.35 and photos == 0) else "moderate",
                "evidence": {"geo_tag_match_score": geo,
                             "site_photos_uploaded": int(photos),
                             "geo_threshold": config.RULE_GEO_MATCH_MIN,
                             "photo_threshold": config.RULE_PHOTOS_MIN},
            })
    return violations


def rule_gaps(project: dict) -> list[str]:
    """Rules that could not be evaluated because inputs were missing."""
    gaps: list[str] = []
    comp = project.get("completion_pct_at_payment")
    if comp is None or (isinstance(comp, float) and comp != comp):
        gaps.append("R1 (completion-before-payment) not evaluable: "
                    "completion_pct_at_payment missing")
    geo = project.get("geo_tag_match_score")
    photos = project.get("site_photos_uploaded")
    geo_missing = geo is None or (isinstance(geo, float) and geo != geo)
    photos_missing = photos is None or (isinstance(photos, float) and photos != photos)
    if geo_missing or photos_missing:
        gaps.append("R2 (insufficient evidence) not evaluable: "
                    "geo_tag_match_score / site_photos_uploaded missing")
    return gaps


def rule_component_score(violations: list[dict]) -> float:
    """0-100 component from rule violations alone."""
    return min(100.0, sum(v["weight"] for v in violations))
