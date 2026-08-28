"""FastAPI application: API + static frontend hosting.

Anti-fraud guardrail is enforced at the API boundary too: responses expose
risk scores, bands, rule flags and "Flagged for investigation" routing
statuses only — never an automated fraud verdict.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db
from .byodataset import (ByoDataset, ledger_template_csv, sample_ledger_csv,
                         sample_projects_csv, template_csv)
from .data_generator import generate
from .pipeline import run_pipeline

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

app = FastAPI(title=config.SYSTEM_NAME, version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

# --------------------------------------------------------------------------
# Demo dataset pipeline (built at startup, cached in-process)
# --------------------------------------------------------------------------
_state: dict = {"demo": None}


def _load_demo() -> dict:
    if _state["demo"] is not None:
        return _state["demo"]
    proj_path, ledger_path, _truth = generate()
    df = pd.read_csv(proj_path)
    ledger = pd.read_csv(ledger_path)
    result = run_pipeline(df, ledger, as_of=date.fromisoformat(config.DEMO_AS_OF),
                          dataset_label="Synthetic demo dataset (Assam, 2022-24)",
                          confidence_notes=[
                              "Demo data is synthetic, generated deterministically "
                              "(seed 42); the assam_scam pattern replicates the "
                              "documented 2023 Barpeta case."])
    _state["demo"] = result
    return result


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    _load_demo()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "system": config.SYSTEM_NAME, "time": datetime.utcnow().isoformat()}


@app.get("/api/meta")
def meta() -> dict:
    demo = _load_demo()
    return {"system": config.SYSTEM_NAME, "meta": demo["meta"],
            "summary": demo["summary"], "guardrail": config.GUARDRAIL_TEXT}


@app.get("/api/summary")
def summary() -> dict:
    d = _load_demo()
    return {"summary": d["summary"], "agencies": d["agencies"][:12],
            "meta": {k: d["meta"][k] for k in
                     ("anomaly", "explainer", "surrogate_r2", "delay_auc",
                      "overrun_r2", "nlp_backend", "thresholds", "provenance")}}


def _filtered_projects(demo: dict, band: str | None, district: str | None,
                       agency: str | None, flagged: bool | None,
                       search: str | None, rule: str | None,
                       fund_flow_flag: str | None) -> list[dict]:
    out = []
    for p in demo["projects"]:
        r = p["risk"]
        if band and r["band"] != band:
            continue
        if district and str(p.get("district", "")) != district:
            continue
        if agency and str(p.get("agency", "")) != agency:
            continue
        if flagged is not None and r["flagged"] != flagged:
            continue
        if rule and not any(v["rule_id"] == rule for v in p["rule_violations"]):
            continue
        if fund_flow_flag and not any(
                f["type"] == fund_flow_flag
                for f in (p.get("fund_flow") or {}).get("flags", [])):
            continue
        if search:
            s = search.lower()
            hay = " ".join(str(p.get(k, "")) for k in
                           ("project_id", "work_description", "district",
                            "agency", "mp_name")).lower()
            if s not in hay:
                continue
        out.append({
            "project_id": p["project_id"],
            "work_description": p.get("work_description", ""),
            "district": p.get("district"),
            "mp_name": p.get("mp_name"),
            "agency": p.get("agency"),
            "work_type": p.get("work_type"),
            "sanctioned_amount": p.get("sanctioned_amount"),
            "completion_pct_at_payment": p.get("completion_pct_at_payment"),
            "ml_anomaly_score": p.get("ml", {}).get("ml_score"),
            "risk_score": r["risk_score"], "band": r["band"],
            "status": r["status"], "flagged": r["flagged"],
            "reasons": r["reasons"][:4],
            "n_rule_violations": p["n_rule_violations"],
            "n_fundflow_flags": len((p.get("fund_flow") or {}).get("flags", [])),
            "has_duplicates": bool(p.get("duplicate_pairs")),
            "geo_lat": p.get("geo_lat"), "geo_lon": p.get("geo_lon"),
        })
    return out


@app.get("/api/projects")
def projects(band: str | None = None, district: str | None = None,
             agency: str | None = None, flagged: str | None = None,
             search: str | None = None, rule: str | None = None,
             fund_flow_flag: str | None = None, sort: str = "risk_desc",
             limit: str | None = None) -> dict:
    demo = _load_demo()
    flagged_b = None
    if flagged is not None and flagged != "":
        flagged_b = str(flagged).strip().lower() in ("1", "true", "yes", "y")
    try:
        limit_i = int(limit) if limit not in (None, "") else 0
    except ValueError:
        limit_i = 0
    rows = _filtered_projects(demo, band or None, district or None,
                              agency or None, flagged_b, search or None,
                              rule or None, fund_flow_flag or None)
    rows.sort(key=lambda r: r["risk_score"],
              reverse=(sort != "risk_asc"))
    total = len(rows)
    if limit_i:
        rows = rows[:limit_i]
    return {"total": total, "projects": rows}


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict:
    demo = _load_demo()
    for p in demo["projects"]:
        if p["project_id"] == project_id:
            return p
    raise HTTPException(404, "project not found")


@app.get("/api/map/projects")
def map_projects() -> dict:
    demo = _load_demo()
    rows = [{"project_id": p["project_id"],
             "lat": p.get("geo_lat"), "lon": p.get("geo_lon"),
             "risk": p["risk"]["risk_score"], "band": p["risk"]["band"],
             "district": p.get("district"),
             "desc": (p.get("work_description") or "")[:90]}
            for p in demo["projects"]
            if p.get("geo_lat") is not None and p.get("geo_lon") is not None]
    return {"projects": rows}


@app.get("/api/duplicates")
def duplicates() -> dict:
    d = _load_demo()["duplicates"]
    return {"pairs": d["pairs"], "backend": d["backend_label"],
            "sim_threshold": d["sim_threshold"],
            "distance_km": d["distance_km"]}


@app.get("/api/agencies")
def agencies() -> dict:
    return {"agencies": _load_demo()["agencies"]}


@app.get("/api/fundflow/{project_id}")
def fundflow(project_id: str) -> dict:
    p = project_detail(project_id)
    return {"project_id": project_id,
            "work_description": p.get("work_description"),
            "fund_flow": p.get("fund_flow"),
            "risk": p["risk"]}


@app.get("/api/compliance/events")
def compliance_events(limit: int = 200) -> dict:
    return {"events": _load_demo()["compliance_events"][:limit]}


# --------------------------------------------------------------------------
# Bring-your-own dataset mode
# --------------------------------------------------------------------------
@app.post("/api/byod/projects")
async def byod_upload(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    try:
        ds = ByoDataset()
        meta = ds.ingest_projects_csv(content, file.filename or "upload.csv")
    except Exception as e:
        raise HTTPException(400, f"Could not parse CSV: {e}")
    with db.get_session() as s:
        s.add(db.DatasetUpload(dataset_id=ds.dataset_id, filename=meta["filename"],
                               kind="projects", n_rows=meta["n_rows"]))
        s.commit()
    return meta


class MappingConfirm(BaseModel):
    mapping: dict[str, str] = Field(default_factory=dict)  # field -> column


@app.post("/api/byod/{dataset_id}/analyze")
def byod_analyze(dataset_id: str, body: MappingConfirm) -> dict:
    if not os.path.exists(os.path.join(config.DATA_DIR, "uploads", dataset_id,
                                       "raw_projects.csv")):
        raise HTTPException(404, "dataset not found")
    ds = ByoDataset(dataset_id)
    try:
        return ds.analyze(body.mapping or None)
    except Exception as e:
        raise HTTPException(400, f"Analysis failed: {e}")


@app.post("/api/byod/{dataset_id}/ledger")
async def byod_ledger_upload(dataset_id: str, file: UploadFile = File(...)) -> dict:
    if not os.path.exists(os.path.join(config.DATA_DIR, "uploads", dataset_id,
                                       "raw_projects.csv")):
        raise HTTPException(404, "dataset not found — upload projects first")
    content = await file.read()
    ds = ByoDataset(dataset_id)
    try:
        return ds.ingest_ledger_csv(content, file.filename or "ledger.csv")
    except Exception as e:
        raise HTTPException(400, f"Could not parse ledger CSV: {e}")


@app.post("/api/byod/{dataset_id}/ledger/apply")
def byod_ledger_apply(dataset_id: str, body: MappingConfirm) -> dict:
    ds = ByoDataset(dataset_id)
    try:
        return ds.apply_ledger_mapping(body.mapping or None)
    except Exception as e:
        raise HTTPException(400, f"Ledger analysis failed: {e}")


@app.get("/api/byod/{dataset_id}/results")
def byod_results(dataset_id: str) -> dict:
    path = os.path.join(config.DATA_DIR, "uploads", dataset_id, "results.json")
    if not os.path.exists(path):
        raise HTTPException(404, "no results — run /analyze first")
    return JSONResponse(json_rolling_load(path))


def json_rolling_load(path: str) -> dict:
    import json
    with open(path) as f:
        return json.load(f)


@app.get("/api/byod/template.csv")
def byod_template() -> StreamingResponse:
    return StreamingResponse(iter([template_csv()]),
                             media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=mplaud_projects_template.csv"})


@app.get("/api/byod/ledger_template.csv")
def byod_ledger_template() -> StreamingResponse:
    return StreamingResponse(iter([ledger_template_csv()]),
                             media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=mplaud_ledger_template.csv"})


@app.get("/api/byod/sample_projects.csv")
def byod_sample_projects() -> StreamingResponse:
    """Sample 'previous year' (FY 2022-23) dataset with realistic messy
    headers and a few hidden dirty patterns — for trying BYO mode without a
    file of your own."""
    return StreamingResponse(iter([sample_projects_csv()]),
                             media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=MPLADS_FY2022-23_sample.csv"})


@app.get("/api/byod/sample_ledger.csv")
def byod_sample_ledger() -> StreamingResponse:
    """Sample payment ledger: 1 healthy chain + 1 structured-split pattern +
    1 missing-UC pattern linked to the sample projects."""
    return StreamingResponse(iter([sample_ledger_csv()]),
                             media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=MPLADS_FY2022-23_sample_ledger.csv"})


# --------------------------------------------------------------------------
# Human-in-the-loop feedback
# --------------------------------------------------------------------------
class FeedbackIn(BaseModel):
    project_id: str
    verdict: str                      # confirmed | false_positive | needs_more_info
    note: str = ""
    investigator: str = ""
    dataset_id: str = "demo"
    context: dict = Field(default_factory=dict)


@app.post("/api/feedback")
def submit_feedback(body: FeedbackIn) -> dict:
    if body.verdict not in ("confirmed", "false_positive", "needs_more_info"):
        raise HTTPException(400, "verdict must be confirmed | false_positive | needs_more_info")
    with db.get_session() as s:
        row = db.Feedback(project_id=body.project_id, verdict=body.verdict,
                          note=body.note, investigator=body.investigator,
                          dataset_id=body.dataset_id,
                          risk_score=body.context.get("risk_score"),
                          band=body.context.get("band"),
                          context=body.context)
        s.add(row)
        s.commit()
    return {"ok": True, "id": row.id,
            "note": "Feedback stored as labelled training data for future "
                    "model retraining."}


@app.get("/api/feedback")
def list_feedback() -> dict:
    with db.get_session() as s:
        rows = (s.query(db.Feedback).order_by(db.Feedback.created_at.desc())
                .all())
        return {"feedback": [
            {"id": r.id, "project_id": r.project_id, "verdict": r.verdict,
             "note": r.note, "investigator": r.investigator,
             "dataset_id": r.dataset_id, "risk_score": r.risk_score,
             "band": r.band,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows]}


@app.get("/api/feedback/export.csv")
def export_feedback() -> StreamingResponse:
    """Labelled data export for future model retraining."""
    with db.get_session() as s:
        rows = s.query(db.Feedback).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["project_id", "verdict", "risk_score", "band", "investigator",
                "note", "dataset_id", "created_at"])
    for r in rows:
        w.writerow([r.project_id, r.verdict, r.risk_score, r.band,
                    r.investigator, r.note, r.dataset_id,
                    r.created_at.isoformat() if r.created_at else ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition":
                                      "attachment; filename=mplaud_feedback_labels.csv"})


# --------------------------------------------------------------------------
# Static frontend
# --------------------------------------------------------------------------
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True),
              name="frontend")
