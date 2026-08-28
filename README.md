# MPLAUD — MPLADS Risk Intelligence & Early Warning System

An AI-powered platform that analyses MPLADS (Members of Parliament Local Area Development Scheme)
project, financial, payment, progress, geographic and asset data to surface **fraud risk, cost
overruns, delays, duplicate works and compliance violations**.

> **Guardrail (non-negotiable):** MPLAUD **never declares fraud automatically**. Every output is a
> 0–100 risk score with a Low / Moderate / High / Critical band, plain-language reasons, and a
> routing status of **"Flagged for investigation"** or **"Not flagged"** — decisions belong to human
> investigators.

---

## Ground truth: the 2023 Assam MPLAD fund case

The system is validated against the documented **2023 Barpeta (Assam) MPLAD fund scam**: Rs 28 lakh
was sanctioned for 3 roads under Rajya Sabha MP **Ajit Bhuyan's** fund; the roads were **never
built**; bills were **paid before the mandatory 75% physical-completion threshold**; officials were
suspended and chargesheeted. The synthetic demo dataset reproduces this exact pattern (near-zero
completion at payment, no site photos, geo-tag mismatch, repeat-flagged agency, round-number bills,
suspiciously fast payment), and the validation harness proves the system ranks those projects as
**top-risk (recall@10 = 6/6)** — see [`VALIDATION_REPORT.md`](VALIDATION_REPORT.md).

**Transparency:** only the 75%-completion rule and the evidence stack are anchored in that case.
Fund-flow thresholds (leakage/structuring/delay), duplicate cutoffs, and the overrun/delay models
are **general-purpose heuristics**, labelled as such in the UI (Methods tab) and API metadata.

## Architecture

```
MPLADS Data → Ingestion & Validation → Feature Engineering
   → Rule Engine + ML Engine (IsolationForest) + NLP Engine
   → Risk Fusion (0–100, banded) → Explainable AI (SHAP / tree-path)
   → Alerts + Dashboard + GIS → Human Investigation → Feedback Loop (labelled data)
```

| Layer | Choice |
|---|---|
| Backend | Python + FastAPI (`backend/app/`) |
| ML | Pandas, NumPy, scikit-learn (IsolationForest, GradientBoosting), SHAP |
| NLP | sentence-transformers (when cached) with a labelled offline TF-IDF fallback |
| Frontend | Vanilla JS + Leaflet (GIS) + Plotly (charts) |
| DB | SQLAlchemy — SQLite by default, PostgreSQL/MySQL via `DATABASE_URL` |
| Deploy | Docker / docker-compose (Postgres profile included) |

## Quick start

```bash
# local
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000
# open http://localhost:8000

# docker
docker compose up --build          # SQLite
docker compose --profile postgres up   # with PostgreSQL (DATABASE_URL env)

# validation harness (writes VALIDATION_REPORT.md)
cd backend && python validation/validate.py
```

## The engines

1. **Anomaly detection** — IsolationForest (unsupervised) over completion-at-payment,
   sanction-to-payment days, geo-tag match confidence, site photos, cost-per-unit vs regional
   benchmark, agency prior flags, round-number bills, nearby duplicate works.
2. **Rule engine** — deterministic and independent of ML: the MPLADS **75% completion-before-payment**
   rule and an **insufficient-evidence** check (weak geo-tag + no photos). Violations explain
   themselves; rules whose inputs are missing are reported *not evaluable*, never silently passed.
3. **Risk fusion** — rule + ML + agency history + fund-flow + duplicate components → single 0–100
   score, bands Low/Moderate/High/Critical, status Flagged/Not flagged (thresholds env-configurable).
   A policy floor escalates serious money-trail findings (structuring, big leakage) into the High
   band even when project-level indicators look clean.
4. **Explainable AI** — every scored project ships top 3–5 factors with direction. Real **SHAP
   (TreeExplainer)** on a RandomForest surrogate reproducing the fused score; a clearly-labelled
   from-scratch Saabas-style tree-path attribution when SHAP is unavailable; robust statistical
   deviation ranking (explicitly marked less rigorous) for small uploaded datasets.
5. **Cost-overrun prediction** — GradientBoosting regression on expected final cost vs sanctioned;
   flags projects trending over budget early.
6. **Delay prediction** — GradientBoosting classifier for schedule slippage from sanction date,
   work type, agency history and district baselines.
7. **Duplicate-work detection** — NLP semantic similarity (sentence embeddings or labelled
   TF-IDF fallback) + DBSCAN haversine clustering (≤1.5 km).
8. **Payment anomaly detection** — see fund flow below; independent of project-level risk.
9. **Agency risk profiling** — running per-agency score from flagged/delayed/overrun history so
   repeat offenders surface on new projects before those projects look individually suspicious.
10. **GIS heatmap** — Leaflet map, circles sized by risk, coloured by band.
11. **Alert Center** — filterable/sortable alerts with drill-down: risk gauge, rule callouts,
    explainability breakdown, fund-flow trail, predictions, agency profile, feedback capture.
12. **Human-in-the-loop feedback** — confirmed / false-positive / needs-more-info verdicts stored
    as labelled data and exportable as a retraining CSV (`/api/feedback/export.csv`).
13. **Compliance monitoring** — dated early-warning feed: violations surface as they occur
    (payment date, lapsed UC window), not at audit time.

## Fund-flow tracking (money trail)

Per project: `Sanction → District Authority release → Implementing Agency release → Vendor payment →
Utilization certificate`, with a visual stage tracker (amount + elapsed days at each hand-off) and
four detectors:

- **Leakage/skimming** — amount drop > 2% between consecutive hand-offs (tolerance for normal
  bank variance);
- **Delay** — funds parked ≥ 200 days at a stage;
- **Structuring** — several vendor payments each just under the Rs 5-lakh scrutiny threshold,
  clustered within days (splitting to avoid oversight);
- **Missing UC** — no utilization certificate within 90 days of vendor payment.

These checks catch risk the completion-percentage rule **cannot see**: the validation harness
demonstrates projects that are 82–99% compliant at payment, pass every rule and score low on the
ML anomaly component, yet are flagged purely through structured/parked/leaked/UC-less ledgers.

## Bring-your-own-dataset mode

Upload your own project CSV in the **Upload Your Data** tab:

1. CSV upload with auto-guessed **column mapping** (fuzzy header matching, with a
   date-column guard so date fields never snap to numeric fields) — confirm or
   override every mapping; sensible defaults for missing optional fields with
   visible reduced-confidence notes;
2. The same rule engine + IsolationForest + risk fusion runs server-side via the API;
3. Results render in the same Alert-Center-style UI with an explicit **Flagged / Not Flagged**
   status and plain-language reason list per project;
4. Explainability honesty: datasets with ≥ 50 rows get surrogate SHAP; smaller ones get
   statistical deviation ranking **explicitly labelled as less rigorous** — the UI never overclaims;
5. Optional second upload — a **payment ledger CSV** (project_id, stage, date/day-offset, amount)
   with its own mapping step — activates fund-flow analytics and re-scores every project;
6. Downloadable CSV templates for both files (buttons in the tab).

**No file of your own?** The tab includes **"Load sample previous-year data"** — a realistic
FY 2022-23 sample CSV (45 works, messy real-world-style headers like *Work Code*, *Physical
Achievement at Payment (%)*, *Photographs of Site Uploaded*) with **3 hidden high-risk works** and
2 borderline ones, so you can watch the auto-mapping and detection end-to-end. A matching
**sample payment ledger** (1 healthy chain + 1 structured-split pattern + 1 missing-UC pattern on
otherwise clean projects) demonstrates the fund-flow tracker on uploaded data.

The UI follows a simple, light government-portal style (tricolor strip, navy header, plain
tables). It is clearly labelled a **demonstration prototype — not an official Government portal**.

Required-at-minimum: `project_id`, `completion_pct_at_payment`, `geo_tag_match_score`,
`site_photos_uploaded`. Optional: `sanctioned_amount`, `days_sanction_to_payment`,
`cost_per_unit_ratio`, `agency_prior_flagged_count`, `district`, `agency`, `work_type`, `mp_name`,
and more (see template).

## API overview

`GET /api/meta` · `GET /api/summary` · `GET /api/projects` (filters: band/district/agency/flagged/
rule/fund-flow/search) · `GET /api/projects/{id}` (full drill-down) · `GET /api/map/projects` ·
`GET /api/duplicates` · `GET /api/agencies` · `GET /api/fundflow/{id}` ·
`GET /api/compliance/events` · `POST /api/byod/projects` → `POST /api/byod/{id}/analyze` ·
`POST /api/byod/{id}/ledger` → `POST /api/byod/{id}/ledger/apply` · `GET /api/byod/template.csv` ·
`POST /api/feedback` · `GET /api/feedback/export.csv` · Interactive docs at `/docs`.

## Configuration

Every threshold is env-tunable (`backend/app/config.py`): completion threshold, geo/photo minimums,
fusion weights, band boundaries, leakage tolerance, stage-delay days, structuring threshold,
UC window, NLP backend (`MPLAUD_NLP_BACKEND=sbert|tfidf|auto`), demo seed, `DATABASE_URL`.

## Repository layout

```
backend/app/          engines (rules, anomaly, risk, surrogate, fundflow, duplicates,
                      overrun, delay, agency, byodataset, pipeline, db, main)
backend/data/demo/    generated deterministic demo CSVs (projects / ledger / truth)
backend/validation/   validation harness (validate.py)
frontend/             vanilla JS SPA (Leaflet + Plotly, vendored — works offline)
VALIDATION_REPORT.md  reproducible validation results
```
