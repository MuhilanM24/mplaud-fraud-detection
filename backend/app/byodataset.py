"""Bring-your-own-dataset mode.

Users upload their own MPLADS project CSV (and optionally a payment-ledger
CSV). A column-mapping step auto-guesses which uploaded column maps to each
required/optional field via fuzzy header matching; the user confirms or
overrides every mapping in the UI; sensible defaults apply to missing
optional fields, with visible reduced-confidence notes.

The same rule engine + Isolation Forest + risk fusion then runs on the
uploaded data, rendered in the same Alert Center UI, with an explicit
Flagged / Not Flagged status plus a plain-language reason list per project.

Analysis runs server-side via the API (documented); nothing about the
uploaded data is persisted beyond the working directory unless the user
submits feedback.
"""
from __future__ import annotations

import difflib
import io
import json
import os
import re
import uuid
from datetime import date, datetime

import numpy as np
import pandas as pd

from . import config
from .pipeline import run_pipeline

UPLOAD_DIR = os.path.join(config.DATA_DIR, "uploads")

# Canonical field -> list of fuzzy header candidates (normalised tokens)
FIELD_SYNONYMS = {
    "project_id": ["project id", "projectid", "id", "work id", "workid",
                   "sanction id", "code", "sl no"],
    "completion_pct_at_payment": [
        "completion pct at payment", "completion percentage at payment",
        "physical completion at payment", "completion at payment",
        "physical progress at payment", "progress at payment pct",
        "completion percent at payment"],
    "geo_tag_match_score": [
        "geo tag match score", "geo tag score", "geotag score",
        "geo tag match", "geo match score", "geotag confidence",
        "geo tag confidence", "geo match"],
    "site_photos_uploaded": [
        "site photos uploaded", "photos uploaded", "site photos",
        "no of photos", "number of photos", "photos count", "photo count",
        "site photographs"],
    "work_description": ["work description", "description", "work name",
                         "name of work", "work details", "work",
                         "description of work", "subject"],
    "sanctioned_amount": ["sanctioned amount", "amount sanctioned",
                          "sanction amount", "amount", "sanctioned cost",
                          "total amount", "cost"],
    "days_sanction_to_payment": [
        "days sanction to payment", "sanction to payment days",
        "days from sanction to payment", "payment lag days",
        "days to payment"],
    "cost_per_unit_ratio": [
        "cost per unit ratio", "cost per unit", "cpu ratio",
        "unit cost ratio", "cost per unit vs benchmark", "benchmark ratio"],
    "agency_prior_flagged_count": [
        "agency prior flagged count", "prior flagged count",
        "agency prior flags", "prior flags", "agency flags",
        "previous flags"],
    "district": ["district", "distt", "district name"],
    "agency": ["agency", "implementing agency", "implementing agency name",
               "contractor", "executing agency", "agency name", "vendor"],
    "work_type": ["work type", "type of work", "category", "work category"],
    "mp_name": ["mp name", "member of parliament", "mp", "mp fund",
                "sanctioned by mp", "parliament member name"],
    "geo_lat": ["geo lat", "latitude", "lat"],
    "geo_lon": ["geo lon", "longitude", "lon", "lng", "long"],
    "sanctioned_date": ["sanctioned date", "date of sanction", "sanction date"],
    "payment_date": ["payment date", "date of payment", "paid date",
                     "payment released on"],
    "completion_pct_final": ["completion pct final", "final completion",
                             "current completion", "completion percentage",
                             "physical completion"],
    "final_cost": ["final cost", "actual cost", "expenditure", "actual "
                   "expenditure", "amount spent"],
    "round_number_bill": ["round number bill", "round bill", "is round amount",
                          "round amount flag"],
    "expected_duration_days": ["expected duration days", "expected duration",
                               "sanctioned duration", "planned duration days"],
    "actual_delay_days": ["actual delay days", "delay days", "actual delay",
                          "slippage days"],
}

LEDGER_FIELDS = {
    "project_id": FIELD_SYNONYMS["project_id"],
    "stage": ["stage", "fund flow stage", "phase", "transaction stage",
              "payment stage"],
    "date": ["date", "transaction date", "stage date", "payment date"],
    "day_offset": ["day offset", "day", "days from sanction", "offset",
                   "day number"],
    "amount": ["amount", "stage amount", "transaction amount", "value",
               "release amount"],
    "note": ["note", "remarks", "comment", "description", "details"],
}

REQUIRED_FIELDS = ["project_id", "completion_pct_at_payment",
                   "geo_tag_match_score", "site_photos_uploaded"]


def _norm(h: str) -> str:
    h = str(h).strip().lower()
    h = re.sub(r"[^a-z0-9% ]+", " ", h)
    return re.sub(r"\s+", " ", h).strip()


def propose_mapping(headers: list[str], fields: dict[str, list[str]]) -> dict:
    """Auto-guess a header -> canonical field mapping (fuzzy)."""
    normed = {h: _norm(h) for h in headers}
    proposal: dict[str, dict] = {}
    used_headers: set[str] = set()
    for field, synonyms in fields.items():
        best = None
        # pass 1: exact synonym hit
        for h, nh in normed.items():
            if h in used_headers:
                continue
            if nh in synonyms:
                best = (h, 1.0, "exact match")
                break
        # pass 2: contains / startswith
        if best is None:
            for h, nh in normed.items():
                if h in used_headers:
                    continue
                for syn in synonyms:
                    if syn in nh or nh in syn:
                        best = (h, 0.8, "substring match")
                        break
                if best:
                    break
        # pass 3: fuzzy ratio
        if best is None:
            for h, nh in normed.items():
                if h in used_headers:
                    continue
                ratio = max(difflib.SequenceMatcher(None, nh, syn).ratio()
                            for syn in synonyms)
                if ratio >= 0.62 and (best is None or ratio > best[1]):
                    best = (h, ratio, f"fuzzy match ({ratio:.0%})")
        if best:
            proposal[field] = {"column": best[0], "confidence": round(best[1], 2),
                               "method": best[2], "required": field in REQUIRED_FIELDS}
            used_headers.add(best[0])
        else:
            proposal[field] = {"column": None, "confidence": 0.0,
                               "method": "not found — pick a column or leave blank",
                               "required": field in REQUIRED_FIELDS}
    return proposal


# Sensible defaults for optional fields missing from an upload
FIELD_DEFAULTS = {
    "days_sanction_to_payment": ("skip", "ML feature dropped; anomaly detection "
                                 "runs without payment-lag signal"),
    "cost_per_unit_ratio": ("skip", "ML feature dropped; no benchmark-inflation "
                            "signal"),
    "agency_prior_flagged_count": ("skip", "agency component computed from the "
                                   "uploaded data itself (rule-violation share "
                                   "and mean risk per agency)"),
    "sanctioned_amount": ("skip", "rule text omits amounts; overrun prediction "
                          "disabled"),
    "district": ("skip", "no district grouping / district baselines"),
    "agency": ("skip", "no agency risk profiling"),
    "work_type": ("skip", "prediction models lose work-type signal"),
    "mp_name": ("skip", "MP attribution unavailable"),
    "geo_lat": ("skip", "map view and geo duplicate detection disabled"),
    "geo_lon": ("skip", "map view and geo duplicate detection disabled"),
    "work_description": ("skip", "duplicate-work NLP detection disabled"),
    "sanctioned_date": ("skip", "compliance timeline uses payment dates only"),
    "payment_date": ("skip", "rule events undated in compliance timeline"),
    "completion_pct_final": ("skip", "ignored"),
    "final_cost": ("skip", "cost-overrun model cannot train"),
    "round_number_bill": (0, "treated as 0 (no round-number signal)"),
    "expected_duration_days": ("skip", "delay model loses duration context"),
    "actual_delay_days": ("skip", "delay model cannot train"),
}


def apply_mapping(df: pd.DataFrame, mapping: dict[str, dict]) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Rename columns per confirmed mapping; fill defaults; return
    (df, missing_required, confidence_notes)."""
    out = pd.DataFrame(index=df.index)
    missing_required: list[str] = []
    notes: list[str] = []
    for field, spec in mapping.items():
        col = (spec or {}).get("column")
        if col and col in df.columns:
            out[field] = df[col]
        elif field in FIELD_DEFAULTS:
            default, note = FIELD_DEFAULTS[field]
            if default != "skip":
                out[field] = default
            notes.append(f"Optional field '{field}' missing: {note}.")
        elif field in REQUIRED_FIELDS:
            missing_required.append(field)
    if missing_required:
        raise ValueError("Required fields without a mapped column: " +
                         ", ".join(missing_required))
    n_missing = sum(1 for f, s in mapping.items() if not (s or {}).get("column"))
    if n_missing:
        notes.append(f"{n_missing} optional field(s) defaulted or skipped — "
                     "confidence in risk scores is reduced accordingly; "
                     "fewer signals means anomalies are harder to separate "
                     "from noise.")
    return out, missing_required, notes


class ByoDataset:
    """Persists an uploaded dataset + confirmed mapping + analysis results."""

    def __init__(self, dataset_id: str | None = None):
        self.dataset_id = dataset_id or uuid.uuid4().hex[:12]
        self.dir = os.path.join(UPLOAD_DIR, self.dataset_id)
        os.makedirs(self.dir, exist_ok=True)

    # ---------------- projects CSV -------------------------------------
    def ingest_projects_csv(self, content: bytes, filename: str) -> dict:
        df = pd.read_csv(io.BytesIO(content))
        df.to_csv(os.path.join(self.dir, "raw_projects.csv"), index=False)
        proposal = propose_mapping(list(df.columns), FIELD_SYNONYMS)
        meta = {"dataset_id": self.dataset_id, "filename": filename,
                "n_rows": len(df), "headers": list(df.columns),
                "proposal": proposal,
                "required_fields": REQUIRED_FIELDS,
                "fields": list(FIELD_SYNONYMS.keys())}
        with open(os.path.join(self.dir, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
        return meta

    def analyze(self, confirmed: dict[str, str] | None = None) -> dict:
        with open(os.path.join(self.dir, "meta.json")) as f:
            meta = json.load(f)
        raw = pd.read_csv(os.path.join(self.dir, "raw_projects.csv"))
        proposal = meta["proposal"]
        if confirmed:
            for field, col in confirmed.items():
                if field in proposal:
                    proposal[field] = {
                        "column": col or None,
                        "confidence": 1.0 if col else 0.0,
                        "method": "user-confirmed",
                        "required": field in REQUIRED_FIELDS}
        mapped, _, notes = apply_mapping(raw, proposal)
        mapped.to_csv(os.path.join(self.dir, "mapped_projects.csv"), index=False)
        with open(os.path.join(self.dir, "meta.json"), "w") as f:
            json.dump(meta, f, indent=2)

        as_of = date.today()
        ledger_path = os.path.join(self.dir, "mapped_ledger.csv")
        ledger = None
        if os.path.exists(ledger_path):
            ledger = pd.read_csv(ledger_path)
            notes.append("Payment ledger linked: fund-flow analytics active "
                         "(leakage / structuring / stage delay / missing UC).")

        result = run_pipeline(mapped, ledger, as_of=as_of,
                              dataset_label=meta["filename"],
                              confidence_notes=notes)
        # every uploaded project gets explicit reasons; guarantee non-empty
        for p in result["projects"]:
            if not p["risk"]["reasons"]:
                p["risk"]["reasons"].append(
                    "No rule violations and no strong statistical outliers "
                    "detected in the provided fields.")
        result["byo"] = {
            "dataset_id": self.dataset_id,
            "filename": meta["filename"],
            "n_rows": meta["n_rows"],
            "mapping": proposal,
            "missing_optional": [f for f, s in proposal.items()
                                 if not (s or {}).get("column")],
            "explainability_note": result["meta"]["explainer"],
        }
        with open(os.path.join(self.dir, "results.json"), "w") as f:
            json.dump(_jsonable(result), f, indent=2, default=str)
        return result

    # ---------------- ledger CSV ---------------------------------------
    def ingest_ledger_csv(self, content: bytes, filename: str) -> dict:
        df = pd.read_csv(io.BytesIO(content))
        df.to_csv(os.path.join(self.dir, "raw_ledger.csv"), index=False)
        proposal = propose_mapping(list(df.columns), LEDGER_FIELDS)
        meta = {"filename": filename, "n_rows": len(df),
                "headers": list(df.columns), "proposal": proposal}
        with open(os.path.join(self.dir, "ledger_meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
        return meta

    def apply_ledger_mapping(self, confirmed: dict[str, str] | None = None) -> dict:
        with open(os.path.join(self.dir, "ledger_meta.json")) as f:
            meta = json.load(f)
        raw = pd.read_csv(os.path.join(self.dir, "raw_ledger.csv"))
        proposal = meta["proposal"]
        if confirmed:
            for field, col in confirmed.items():
                if field in proposal:
                    proposal[field] = {"column": col or None, "confidence": 1.0,
                                       "method": "user-confirmed",
                                       "required": False}
        mapped = pd.DataFrame(index=raw.index)
        for field, spec in proposal.items():
            col = (spec or {}).get("column")
            if col and col in raw.columns:
                mapped[field] = raw[col]
        need = [c for c in ("project_id", "stage", "amount")
                if c not in mapped.columns]
        if need:
            raise ValueError("Ledger mapping missing required column(s): " +
                             ", ".join(need))
        if "day_offset" not in mapped.columns and "date" in mapped.columns:
            # convert dates to offsets per project using projects' sanction date
            proj = pd.read_csv(os.path.join(self.dir, "mapped_projects.csv"))
            if "sanctioned_date" in proj.columns:
                sdates = proj.set_index("project_id")["sanctioned_date"].to_dict()
                sd = pd.to_datetime(pd.Series(
                    [sdates.get(p) for p in mapped["project_id"]]),
                    errors="coerce")
                ld = pd.to_datetime(mapped["date"], errors="coerce")
                mapped["day_offset"] = (ld - sd.values).dt.days
        mapped.to_csv(os.path.join(self.dir, "mapped_ledger.csv"), index=False)
        with open(os.path.join(self.dir, "ledger_meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
        return self.analyze(None)  # re-run full analysis with ledger


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (date, datetime, pd.Timestamp)):
        return obj.isoformat()
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return str(obj)


def template_csv() -> str:
    """Downloadable template showing the exact expected columns."""
    header = (["project_id,work_description,district,mp_name,agency,work_type,",
               "sanctioned_amount,sanctioned_date,payment_date,",
               "days_sanction_to_payment,completion_pct_at_payment,",
               "geo_tag_match_score,site_photos_uploaded,geo_lat,geo_lon,",
               "cost_per_unit_ratio,agency_prior_flagged_count,",
               "round_number_bill"].index("") if False else "")
    cols = ["project_id", "work_description", "district", "mp_name", "agency",
            "work_type", "sanctioned_amount", "sanctioned_date", "payment_date",
            "days_sanction_to_payment", "completion_pct_at_payment",
            "completion_pct_final", "final_cost", "geo_tag_match_score",
            "site_photos_uploaded", "geo_lat", "geo_lon", "cost_per_unit_ratio",
            "agency_prior_flagged_count", "round_number_bill",
            "expected_duration_days", "actual_delay_days"]
    rows = [
        ["AS-EX-0001", "Construction of CC road from A to B", "Barpeta",
         "Ajit Bhuyan (RS)", "Barpeta PWD Division (Roads)", "Road", 2500000,
         "2023-01-10", "2023-07-15", 186, 85.0, 100, 2550000, 0.91, 18,
         26.3221, 91.0053, 1.05, 0, "False", 210, 12],
        ["AS-EX-0002", "Installation of 20 solar street lights at B",
         "Nagaon", "Example MP (RS)", "Nagaon Municipal Board",
         "Electrification", 980000, "2023-02-01", "2023-05-20", 108, 90.0,
         100, 1000000, 0.88, 22, 26.3464, 92.6836, 0.98, 1, "False", 120, 0],
    ]
    lines = [",".join(cols)]
    for r in rows:
        vals = []
        for v in r:
            if isinstance(v, str) and ("," in v or v.count('"')):
                vals.append(f'"{v}"')
            else:
                vals.append(str(v))
        lines.append(",".join(vals))
    return "\n".join(lines) + "\n"


def ledger_template_csv() -> str:
    cols = ["project_id", "stage", "date", "day_offset", "amount", "note"]
    lines = [",".join(cols)]
    d = ["AS-EX-0001"]
    for stage, off, amt in [("SANCTION", 0, 2500000), ("DISTRICT_RELEASE", 20, 2495000),
                            ("AGENCY_RELEASE", 45, 2490000), ("VENDOR_PAYMENT", 90, 2480000),
                            ("UTILIZATION_CERTIFICATE", 150, 2480000)]:
        lines.append(f"{d[0]},{stage},,{off},{amt},")
    return "\n".join(lines) + "\n"
