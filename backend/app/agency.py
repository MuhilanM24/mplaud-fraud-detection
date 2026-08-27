"""Agency / contractor risk profiling.

A running 0-100 risk score per implementing agency built from its observable
history in the analysed dataset — share of projects violating rules, mean
fused risk, delay rate, cost-overrun rate — plus the agency_prior_flagged_count
feature where present. Repeat offenders surface on every NEW project they
touch, even when the new project itself looks unremarkable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def build_agency_profiles(df: pd.DataFrame, per_project: dict[str, dict],
                          violations_by: dict[str, list] | None = None) -> dict[str, dict]:
    """df must have an `agency` column; per_project maps pid -> fused result;
    violations_by maps pid -> rule-violation lists (preferred if provided)."""
    if "agency" not in df.columns or df["agency"].isna().all():
        return {}
    rows = df[["project_id", "agency"]].copy()
    rows["risk"] = rows["project_id"].map(
        lambda p: per_project.get(p, {}).get("risk_score", np.nan))
    rows["nviol"] = rows["project_id"].map(
        lambda p: len((violations_by or {}).get(p, [])))
    prior = None
    if "agency_prior_flagged_count" in df.columns:
        prior = df.groupby("agency")["agency_prior_flagged_count"].max()
    delay = None
    if "actual_delay_days" in df.columns:
        delay = df.groupby("agency")["actual_delay_days"].apply(
            lambda s: float((s > 90).mean()))
    overrun = None
    if "final_cost" in df.columns and "sanctioned_amount" in df.columns:
        ratio = (pd.to_numeric(df["final_cost"], errors="coerce") /
                 pd.to_numeric(df["sanctioned_amount"], errors="coerce"))
        df2 = df.assign(_ratio=ratio)
        overrun = df2.groupby("agency")["_ratio"].apply(
            lambda s: float((s > 1.15).mean()))

    out: dict[str, dict] = {}
    for agency, grp in rows.groupby("agency"):
        risks = grp["risk"].dropna()
        n = len(grp)
        rule_viol = int((grp["nviol"] > 0).sum())
        flagged = sum(1 for _, r in grp.iterrows()
                      if per_project.get(r["project_id"], {}).get("flagged"))
        prior_flags = float(prior.get(agency, 0)) if prior is not None else 0.0
        mean_risk = float(risks.mean()) if len(risks) else 0.0
        score = (
            40.0 * min(1.0, rule_viol / max(n, 1)) +
            30.0 * min(1.0, mean_risk / 100.0) +
            15.0 * min(1.0, prior_flags / 5.0) +
            15.0 * min(1.0, flagged / max(n, 1))
        )
        out[agency] = {
            "agency": agency,
            "n_projects": n,
            "rule_violations": rule_viol,
            "flagged_projects": flagged,
            "mean_project_risk": round(mean_risk, 1),
            "prior_flagged_count": prior_flags,
            "delay_rate": round(float(delay.get(agency, 0.0)), 3) if delay is not None else None,
            "overrun_rate": round(float(overrun.get(agency, 0.0)), 3) if overrun is not None else None,
            "agency_risk_score": round(min(100.0, score), 1),
            "note": ("Repeat-offender pattern: this agency's history alone "
                     "raises the risk of its new projects" if score >= 55 else
                     "No strong historical pattern"),
        }
    return out


def agency_component(profile: dict | None, prior_flags_col: float | None) -> float | None:
    """Agency history contribution 0-100 for one project."""
    if profile is None and prior_flags_col is None:
        return None
    vals = []
    if profile is not None:
        vals.append(profile.get("agency_risk_score", 0.0) * 0.7)
    if prior_flags_col is not None and prior_flags_col == prior_flags_col:
        vals.append(min(100.0, prior_flags_col / 5.0 * 100.0) * 0.5)
    return min(100.0, max(vals)) if vals else None
