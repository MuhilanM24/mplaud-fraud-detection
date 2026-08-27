"""End-to-end pipeline orchestrator.

MPLADS Data -> Data Ingestion & Validation -> Feature Engineering ->
Rule Engine + ML Engine + NLP Engine -> Risk Engine -> Risk Score (0-100) ->
Explainable AI -> Alerts + Dashboard + GIS -> Human Investigation -> Feedback

Works for both the built-in demo dataset and bring-your-own CSVs. The pipeline
never sees ground-truth pattern labels — those exist only in truth.csv for the
validation harness.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import config
from .agency import agency_component, build_agency_profiles
from .anomaly import AnomalyEngine
from .delay import DelayModel
from .duplicates import NLPBackend, detect_duplicates, duplicate_component
from .features import build_matrix
from .fundflow import analyze_project_ledger, build_compliance_events
from .overrun import OverrunModel
from .risk_engine import fuse
from .rules import evaluate_rules, rule_gaps
from .surrogate import SurrogateModel


def run_pipeline(df: pd.DataFrame, ledger: pd.DataFrame | None = None,
                 as_of: date | None = None,
                 dataset_label: str = "dataset",
                 confidence_notes: list[str] | None = None) -> dict:
    as_of = as_of or date.today()
    nlp = NLPBackend(config.NLP_BACKEND)

    # ---------------- data validation -----------------------------------
    missing_required = [c for c in ("project_id",) if c not in df.columns]
    if missing_required:
        raise ValueError(f"missing required column(s): {missing_required}")
    df = df.drop_duplicates(subset="project_id", keep="first").reset_index(drop=True)

    # ---------------- feature engineering (incl. NLP/geo duplicate pass) --
    dup_result = detect_duplicates(df, nlp)
    df = df.copy()
    df["nearby_duplicate_count"] = df["project_id"].map(
        lambda p: dup_result["nearby_counts"].get(p, 0))

    district_baseline = None
    if "actual_delay_days" in df.columns and "district" in df.columns:
        district_baseline = (df.assign(
            _d=(pd.to_numeric(df["actual_delay_days"], errors="coerce").fillna(0) >
                config.DELAY_FLAG_DAYS).astype(int))
            .groupby("district")["_d"].mean().to_dict())

    # ---------------- rule engine (pass 1) -------------------------------
    records = df.to_dict(orient="records")
    violations_by = {r["project_id"]: evaluate_rules(r) for r in records}
    gaps_by = {r["project_id"]: rule_gaps(r) for r in records}

    # ---------------- ML: Isolation Forest -------------------------------
    matrix, used_cols = build_matrix(df, None, district_baseline)
    ml_scores: dict[str, dict] = {}
    anomaly_meta: dict = {}
    if len(matrix) >= 10 and matrix.shape[1] >= 2:
        engine = AnomalyEngine(config.IF_N_ESTIMATORS, config.IF_CONTAMINATION,
                               config.IF_RANDOM_STATE).fit(matrix)
        scored = engine.score(matrix)
        for i, pid in enumerate(df["project_id"]):
            ml_scores[pid] = scored[i]
        anomaly_meta = {"model": "IsolationForest",
                        "n_estimators": config.IF_N_ESTIMATORS,
                        "contamination": config.IF_CONTAMINATION,
                        "features": used_cols}
    else:
        anomaly_meta = {"model": None,
                        "note": "too few rows/features for IsolationForest; "
                                "ML component skipped and weights renormalised"}

    # ---------------- fund-flow (ledger) analyses ------------------------
    ff_by: dict[str, dict] = {}
    if ledger is not None and len(ledger):
        by_pid: dict[str, list[dict]] = {}
        sdates = df.set_index("project_id")["sanctioned_date"].to_dict() \
            if "sanctioned_date" in df.columns else {}
        for pid, grp in ledger.groupby("project_id"):
            rows = grp.to_dict(orient="records")
            base = None
            if pid in sdates and isinstance(sdates[pid], str):
                try:
                    base = datetime.fromisoformat(sdates[pid][:10]).date()
                except ValueError:
                    base = None
            # convert ISO dates to day offsets if needed
            norm_rows = []
            for r in rows:
                r = dict(r)
                day = r.get("day_offset", r.get("day"))
                if (day is None or (isinstance(day, float) and day != day)) \
                        and base and r.get("date"):
                    try:
                        r["day_offset"] = (datetime.fromisoformat(
                            str(r["date"])[:10]).date() - base).days
                    except ValueError:
                        pass
                else:
                    r["day_offset"] = day
                norm_rows.append(r)
            # "today" in day-offset units for the missing-UC window check
            as_of_day = (as_of - base).days if base else None
            ff_by[str(pid)] = analyze_project_ledger(norm_rows, str(pid),
                                                     as_of_day)

    # ---------------- provisional agency profiles -------------------------
    prior_by_pid = {}
    if "agency_prior_flagged_count" in df.columns:
        prior_by_pid = df.set_index("project_id")[
            "agency_prior_flagged_count"].astype(float).to_dict()
    provisional = {}
    for r in records:
        pid = r["project_id"]
        provisional[pid] = fuse(
            pid, violations_by[pid], ml_scores.get(pid, {}).get("ml_score"),
            agency_component(None, prior_by_pid.get(pid)),
            ff_by.get(pid), duplicate_component(dup_result, pid),
            notes=gaps_by.get(pid, []))

    # ---------------- final agency profiles + re-fusion -------------------
    profiles = build_agency_profiles(df, provisional, violations_by)
    final = {}
    for r in records:
        pid = r["project_id"]
        final[pid] = fuse(
            pid, violations_by[pid], ml_scores.get(pid, {}).get("ml_score"),
            agency_component(profiles.get(r.get("agency")), prior_by_pid.get(pid)),
            ff_by.get(pid), duplicate_component(dup_result, pid),
            notes=gaps_by.get(pid, []))

    # ---------------- explainable AI (surrogate) --------------------------
    surrogate = None
    explain_method = "Statistical deviation ranking"
    y = np.array([final[p]["risk_score"] for p in df["project_id"]])
    if len(df) >= config.SURROGATE_MIN_ROWS and matrix.shape[1] >= 3:
        surrogate = SurrogateModel().fit(matrix, y)
        explain_method = surrogate.method_label
    factors_by: dict[str, list] = {}
    method_by: dict[str, str] = {}
    if surrogate is not None:
        for i, pid in enumerate(df["project_id"]):
            row = matrix.iloc[i]
            factors_by[pid] = surrogate.top_factors(row, k=5)
            method_by[pid] = surrogate.method_label
    else:
        from .surrogate import deviation_ranking
        for i, pid in enumerate(df["project_id"]):
            row = matrix.iloc[i]
            factors, method = deviation_ranking(row, matrix, k=5)
            factors_by[pid] = factors
            method_by[pid] = method

    # ---------------- prediction models -----------------------------------
    overrun_model = OverrunModel().fit(df)
    delay_model = DelayModel().fit(df, district_baseline)

    # ---------------- assemble per-project results ------------------------
    projects_out = []
    for i, r in enumerate(records):
        pid = r["project_id"]
        ff = ff_by.get(pid)
        pairs = [p for p in dup_result["pairs"]
                 if pid in (p["project_id_a"], p["project_id_b"])]
        overrun_pred = None
        try:
            amt = float(r.get("sanctioned_amount")) if r.get("sanctioned_amount") \
                is not None else None
            if amt and amt == amt:
                overrun_pred = overrun_model.predict(df.iloc[i], amt)
        except (TypeError, ValueError):
            pass
        delay_pred = None
        if delay_model.trained:
            db = None
            if district_baseline and r.get("district") in district_baseline:
                db = district_baseline[r["district"]]
            prof = profiles.get(r.get("agency", ""))
            delay_pred = delay_model.predict(
                df.iloc[i], db,
                prof.get("delay_rate") if prof else None)
        res = dict(r)
        res.update({
            "risk": final[pid],
            "n_rule_violations": len(violations_by[pid]),
            "rule_violations": violations_by[pid],
            "rule_gaps": gaps_by.get(pid, []),
            "ml": ml_scores.get(pid, {}),
            "explainability": {
                "method": method_by.get(pid, explain_method),
                "factors": factors_by.get(pid, []),
            },
            "fund_flow": ff,
            "duplicate_pairs": pairs,
            "agency_profile": profiles.get(r.get("agency", "")),
            "predictions": {"cost_overrun": overrun_pred, "delay": delay_pred},
        })
        projects_out.append(res)

    # ---------------- compliance early-warning events ---------------------
    events = []
    for r, res in zip(records, projects_out):
        pid = r["project_id"]
        # rule events dated at the moment they became visible (payment date)
        sdate = None
        if isinstance(r.get("sanctioned_date"), str):
            try:
                sdate = datetime.fromisoformat(r["sanctioned_date"][:10]).date()
            except ValueError:
                sdate = None
        for v in res["rule_violations"]:
            ev_date = r.get("payment_date") or r.get("sanctioned_date")
            events.append({
                "project_id": pid, "date": ev_date, "source": "rule_engine",
                "type": v["rule_id"], "severity": v["severity"],
                "title": v["title"], "detail": v["detail"],
            })
        if res.get("fund_flow"):
            for ev in build_compliance_events(r, res["fund_flow"]):
                if sdate and isinstance(ev.get("date_offset"), int):
                    ev["date"] = (sdate + timedelta(days=ev["date_offset"])).isoformat()
                else:
                    ev["date"] = r.get("payment_date")
                ev.pop("date_offset", None)
                events.append(ev)
    events.sort(key=lambda e: str(e.get("date") or ""), reverse=True)

    # ---------------- summary --------------------------------------------
    band_counts = {b: 0 for b, _, _ in config.BANDS}
    for res in projects_out:
        band_counts[res["risk"]["band"]] = band_counts.get(res["risk"]["band"], 0) + 1
    flagged = [r for r in projects_out if r["risk"]["flagged"]]

    summary = {
        "dataset_label": dataset_label,
        "n_projects": len(projects_out),
        "n_flagged": len(flagged),
        "band_counts": band_counts,
        "n_rule_violations": sum(r["n_rule_violations"] for r in projects_out),
        "n_fundflow_flags": sum(len((r.get("fund_flow") or {}).get("flags", []))
                                for r in projects_out),
        "n_duplicate_pairs": len(dup_result["pairs"]),
        "n_agencies": len(profiles),
        "as_of": as_of.isoformat(),
        "confidence_notes": confidence_notes or [],
    }

    return {
        "summary": summary,
        "projects": projects_out,
        "agencies": sorted(profiles.values(),
                           key=lambda a: -a["agency_risk_score"]),
        "duplicates": dup_result,
        "compliance_events": events,
        "meta": {
            "anomaly": anomaly_meta,
            "explainer": explain_method,
            "surrogate_r2": None if surrogate is None else round(surrogate.r2, 3),
            "surrogate_mae": None if surrogate is None else round(surrogate.mae, 2),
            "overrun_trained": overrun_model.trained,
            "overrun_r2": overrun_model.r2 and round(overrun_model.r2, 3),
            "overrun_mae": overrun_model.mae and round(overrun_model.mae, 3),
            "delay_trained": delay_model.trained,
            "delay_auc": delay_model.auc and round(delay_model.auc, 3),
            "nlp_backend": dup_result["backend_label"],
            "nlp_backend_kind": dup_result["backend"],
            "dup_sim_threshold": dup_result["sim_threshold"],
            "dup_distance_km": dup_result["distance_km"],
            "thresholds": {
                "completion_before_payment_pct": config.RULE_COMPLETION_MIN_PCT,
                "geo_match_min": config.RULE_GEO_MATCH_MIN,
                "photos_min": config.RULE_PHOTOS_MIN,
                "leakage_tolerance_pct": config.LEAKAGE_TOLERANCE_PCT,
                "stage_delay_days": config.STAGE_DELAY_DAYS,
                "structuring_threshold": config.STRUCTURING_THRESHOLD,
                "structuring_min_payments": config.STRUCTURING_MIN_PAYMENTS,
                "uc_window_days": config.UC_WINDOW_DAYS,
                "bands": [b for b, _, _ in config.BANDS],
                "flagged_bands": config.FLAGGED_BANDS.split(","),
                "fusion_weights": config.FUSION_WEIGHTS,
                "fund_flow_floor": config.FUND_FLOW_FLOOR_SCORE,
            },
            "guardrail": config.GUARDRAIL_TEXT,
            "provenance": {
                "assam_validated": ("Rule R1 + evidence stack replicates the documented "
                                    "2023 Barpeta (Assam) MPLAD case pattern "
                                    "(Rs 28 lakh / 3 unbuilt roads / pre-completion "
                                    "payment); the demo data reproduces it as ground "
                                    "truth and the validation harness verifies top-N "
                                    "ranking recall."),
                "heuristics": ("Fund-flow leakage/structuring/delay thresholds, "
                               "duplicate similarity cutoffs, cost-overrun and delay "
                               "models are general-purpose heuristics, NOT derived "
                               "from the Assam findings."),
            },
        },
    }
