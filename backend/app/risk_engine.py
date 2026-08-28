"""Risk fusion engine: rule violations + ML anomaly + agency history +
fund-flow anomalies + duplicate involvement -> one 0-100 risk score.

GUARDRAIL: the output is a risk score with bands (Low / Moderate / High /
Critical) and a routing status — "Flagged for investigation" or "Not flagged".
It is NEVER a fraud verdict. Wording throughout is investigative, not
accusatory.
"""
from __future__ import annotations

from . import config
from .rules import rule_component_score


def fuse(project_id: str, rule_violations: list[dict], ml_score: float | None,
         agency_score: float | None, fundflow: dict | None,
         dup_score: float | None, notes: list[str] | None = None) -> dict:
    """Fuse available components; unavailable ones are excluded and weights
    renormalised (so bring-your-own datasets with fewer fields still work)."""
    parts: dict[str, float] = {}
    parts["rules"] = rule_component_score(rule_violations)
    if ml_score is not None:
        parts["ml_anomaly"] = float(ml_score)
    if agency_score is not None:
        parts["agency_history"] = float(agency_score)
    if fundflow and fundflow.get("has_ledger"):
        parts["fund_flow"] = float(fundflow["component_score"])
    if dup_score is not None and dup_score > 0:
        parts["duplicates"] = float(dup_score)

    weights = {k: config.FUSION_WEIGHTS[k] for k in parts}
    wsum = sum(weights.values()) or 1.0
    raw = sum(parts[k] * weights[k] for k in parts) / wsum
    score = max(0.0, min(100.0, raw))

    # Policy floor: fund-flow anomalies can be invisible at project level, so
    # structural money-trail findings escalate the score into the High band.
    ff = fundflow or {}
    floor_target = None
    if ff.get("floor_class") == "major":
        floor_target = config.FUND_FLOW_FLOOR_SCORE
    elif ff.get("floor_class") == "minor":
        floor_target = config.FUND_FLOW_FLOOR_MINOR
    floor_applied = bool(floor_target is not None and score < floor_target)
    if floor_applied:
        score = floor_target

    band = config.band_for(score)
    flagged = config.is_flagged_band(band)
    reasons = _plain_reasons(parts, rule_violations, fundflow or {},
                             floor_applied, notes or [])
    return {
        "project_id": project_id,
        "risk_score": round(score, 1),
        "band": band,
        "flagged": flagged,
        "status": "Flagged for investigation" if flagged else "Not flagged",
        "components": {k: round(v, 1) for k, v in parts.items()},
        "component_weights": {k: round(w / wsum, 3) for k, w in weights.items()},
        "floor_applied": floor_applied,
        "reasons": reasons,   # plain-language reason list (BYO requirement)
        "guardrail": config.GUARDRAIL_TEXT,
    }


def _plain_reasons(parts: dict, violations: list[dict], ff: dict,
                   floor_applied: bool, notes: list[str]) -> list[str]:
    reasons: list[str] = []
    for v in violations:
        reasons.append(f"[Rule {v['rule_id'].split('_')[0]}] {v['title']}")
    if parts.get("ml_anomaly", 0) >= 85:
        reasons.append("Project is an extreme statistical outlier (top anomaly "
                       "scores on completion-at-payment, speed of payment, "
                       "evidence, or cost benchmarks)")
    elif parts.get("ml_anomaly", 0) >= 70:
        reasons.append("Project is a strong statistical outlier across several "
                       "engineered features")
    if parts.get("agency_history", 0) >= 60:
        reasons.append("Implementing agency has a repeated history of flagged "
                       "projects")
    if ff:
        for f in ff.get("flags", []):
            reasons.append(f"[Fund flow] {f['title']}")
    if floor_applied:
        reasons.append("Score escalated into the High band by a fund-flow "
                       "anomaly ("
                       + ("serious: structured or leaked money" if
                          ff.get("floor_class") == "major" else
                          "moderate: stalled funds or missing utilization "
                          "certificate") +
                       ") despite clean project-level indicators")
    if parts.get("duplicates", 0) >= 40:
        reasons.append("Sanctioned work is near-identical to another sanctioned "
                       "work at the same location (possible duplicate claim)")
    reasons.extend(notes)
    return reasons
