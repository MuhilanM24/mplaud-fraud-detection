"""Synthetic MPLADS dataset generator (deterministic, seeded).

Ground truth anchored in the documented 2023 Assam MPLAD fund scam (Barpeta
district): Rs 28 lakh sanctioned for 3 roads under Rajya Sabha MP Ajit Bhuyan's
MPLADS fund; the roads were never built; bills were paid before the mandatory
75% physical-completion threshold; officials were suspended and chargesheeted.

The generator produces:
  * projects.csv       — one row per sanctioned work (analytical features only,
                         NO pattern labels — the pipeline never sees labels)
  * ledger.csv         — fund-flow rows (stage / day / amount) per project
  * truth.csv          — pattern labels + per-pattern expected behaviours,
                         used ONLY by the validation harness to score recall.

Pattern mix (validation criteria):
  * ~180 normal projects (a minority with single gray-area deviations so the
    bands are populated with realistic noise, but nothing pathological)
  * 6 "assam_scam" projects — the 3 documented Barpeta roads (~Rs 28 lakh total,
    paid at ~0-12% completion, zero photos, geo-tag mismatch, repeat-flagged
    agency, round-number bills, paid suspiciously fast) + 3 replication
    pattern-copies in neighbouring districts.
  * 11 "ledger-only" dirty projects (structuring x4, stage-delay x3, leakage x2,
    missing-UC x2) whose PROJECT-level features look completely clean — risk
    exists only in the payment ledger.
  * 3 planted duplicate-work pairs (same asset sanctioned twice, paraphrased
    descriptions, <800 m apart).
"""
from __future__ import annotations

import csv
import json
import os
import random
from datetime import date, timedelta

from . import config

DISTRICTS = {
    # district: (lat, lon, baseline delay-rate)
    "Barpeta":   (26.322, 91.005, 0.22),
    "Kamrup":    (26.145, 91.736, 0.18),
    "Nagaon":    (26.346, 92.684, 0.25),
    "Dibrugarh": (27.473, 94.912, 0.15),
    "Sonitpur":  (26.683, 92.790, 0.20),
    "Cachar":    (24.820, 92.799, 0.30),
    "Jorhat":    (26.751, 94.204, 0.17),
    "Golaghat":  (26.512, 93.965, 0.21),
    "Sivasagar": (26.983, 94.643, 0.16),
    "Darrang":   (26.511, 92.000, 0.24),
}

# Implementing agencies: (prior flagged count, delay-prone?)
AGENCIES = {
    "Barpeta PWD Division (Roads)":            (1, False),
    "DRDA Kamrup":                             (0, False),
    "Nagaon Municipal Board":                  (1, True),
    "Public Health Engineering Div. Jorhat":   (0, False),
    "Sonitpur DRDA":                           (0, True),
    "Dibrugarh Zilla Parishad":                (1, False),
    "Cachar PWD Division":                     (2, True),
    "Golaghat Irrigation Division":            (0, False),
    "Sivasagar Municipal Board":               (1, False),
    "Darrang Rural Works Division":            (0, True),
    # The repeat-offender agency used for the Assam-pattern projects:
    "Sewa Constructions & Suppliers (Guwahati)": (5, True),
    "Pragati Associates (Nagaon)":              (3, False),
}

MPS = [
    "Ajit Bhuyan (RS)", "Pabitra Margherita (RS)", "Ripun Bora (RS)",
    "Kamakhya Prasad Tasa (RS)", "Queen Ojha (RS)", "Birendra Prasad Baishya (RS)",
    "Gaurav Gogoi (LS, Kaliabor)", "Pradan Baruah (LS, Lakhimpur)",
    "Rameswar Teli (LS, Dibrugarh)", "Mission Ranjan Das (LS, Karimganj)",
    "Sushmita Dev (LS, Silchar)", "Rajdeep Roy (LS, Karimganj)",
]

WORK_TYPES = {
    "Road": [
        "Construction of CC road from {a} to {b}",
        "Widening and metalling of road from {a} to {b}",
        "Construction of RCC road at {a} village",
    ],
    "Building": [
        "Construction of 2-room school building at {a}",
        "Construction of community hall at {a}",
        "Construction of anganwadi centre building at {a}",
    ],
    "Water": [
        "Construction of deep tube well with platform at {a}",
        "Installation of ring wells at {a} and {b}",
        "Flood protection embankment work near {a}",
    ],
    "Electrification": [
        "Installation of 20 solar street lights at {a} village",
        "Electrification of {a} village approach roads",
        "High-mast light installation at {a} market",
    ],
    "Sanitation": [
        "Construction of public toilet block at {a}",
        "Construction of RCC drain along {a} road",
        "Solid waste shed construction at {a}",
    ],
}

VILLAGES = [
    "Sarbhog", "Chenga", "Baghbar", "Jania", "Simlunguri", "Barpeta Road",
    "Howly", "Pathsala", "Bajali", "Mandia", "Sorbhet", "Rupshi",
    "Kamalabari", "Dakhin Gaon", "Beltola", "Sonapur", "Chaygaon", "Rangiya",
    "Puranigudam", "Samaguri", "Kampur", "Raha", "Jamunamukh", "Lumding",
    "Chabua", "Tengakhat", "Naharkatia", "Moran", "Biswanath", "Gohpur",
    "Silchar", "Lakhipur", "Udarbond", "Dholai", "Titabor", "Mariani",
    "Bokakhat", "Numaligarh", "Gaurisagar", "Nazira", "Mangaldai", "Kharupetia",
]

AS_OF = date.fromisoformat(config.DEMO_AS_OF)

# Canonical stage names in the ledger
S_SANCTION = "SANCTION"
S_DISTRICT = "DISTRICT_RELEASE"
S_AGENCY = "AGENCY_RELEASE"
S_VENDOR = "VENDOR_PAYMENT"
S_UC = "UTILIZATION_CERTIFICATE"


def _d(offset_days: int, base: date) -> str:
    return (base + timedelta(days=offset_days)).isoformat()


def generate(seed: int = config.DEMO_SEED,
             out_dir: str | None = None) -> tuple[str, str, str]:
    """Generate the demo dataset. Returns (projects_csv, ledger_csv, truth_csv)."""
    rng = random.Random(seed)
    out_dir = out_dir or os.path.join(config.DATA_DIR, "demo")
    os.makedirs(out_dir, exist_ok=True)

    projects: list[dict] = []
    ledger: list[dict] = []
    truth: list[dict] = []
    seq = 0

    def pid() -> str:
        nonlocal seq
        seq += 1
        return f"AS-2023-{seq:04d}"

    def san_date() -> date:
        # sanctions spread across 2022-01 .. 2023-10
        start = date(2022, 1, 1).toordinal()
        end = date(2023, 10, 31).toordinal()
        return date.fromordinal(rng.randint(start, end))

    def add_ledger_row(p_id: str, stage: str, day: int, amount: float,
                       base: date, note: str = "") -> None:
        ledger.append({
            "project_id": p_id, "stage": stage,
            "date": _d(day, base), "day_offset": day,
            "amount": round(amount, 2), "note": note,
        })

    def normal_ledger(p_id: str, base: date, amount: float,
                      rng_: random.Random) -> dict:
        """Typical healthy fund-flow; returns stage day offsets + uc flag."""
        d0 = 0
        d1 = d0 + rng_.randint(12, 55)                       # district release
        d2 = d1 + rng_.randint(8, 40)                        # agency release
        d3 = d2 + rng_.randint(15, 80)                       # vendor payment
        d4 = d3 + rng_.randint(20, 85)                       # UC
        amts = [amount,
                amount * rng_.uniform(0.995, 1.0),
                amount * rng_.uniform(0.99, 1.0),
                amount * rng_.uniform(0.985, 1.0),
                amount * rng_.uniform(0.985, 1.0)]
        for stage, day, amt in zip(config.STAGES, [d0, d1, d2, d3, d4], amts):
            add_ledger_row(p_id, stage, day, amt, base)
        return {"days": {S_DISTRICT: d1, S_AGENCY: d2, S_VENDOR: d3, S_UC: d4},
                "amounts": dict(zip(config.STAGES, amts))}

    # ------------------------------------------------------------------
    # 1) ~180 normal projects
    # ------------------------------------------------------------------
    for _ in range(config.N_NORMAL_PROJECTS):
        p = pid()
        district = rng.choice(list(DISTRICTS))
        dlat, dlon, _ = DISTRICTS[district]
        agency = rng.choice(list(AGENCIES))
        prior_flags, slow_agency = AGENCIES[agency]
        wtype = rng.choice(list(WORK_TYPES))
        desc = rng.choice(WORK_TYPES[wtype]).format(
            a=rng.choice(VILLAGES), b=rng.choice(VILLAGES))
        amount = round(rng.uniform(6, 75) * 100000, -3)      # Rs 6-75 lakh
        sdate = san_date()

        # ~14% single gray-area deviation (populates Moderate band) — but
        # never the full pathological stack.
        gray = rng.random()
        if gray < 0.07:      # paid slightly under 75% (borderline breach)
            comp_at_pay = rng.uniform(60, 74)
            n_rules = 1
        elif gray < 0.12:    # thin evidence (weak geo, 0-1 photos) but paid late & compliant
            comp_at_pay = rng.uniform(78, 100)
            n_rules = 1
        else:
            comp_at_pay = rng.uniform(76, 100)
            n_rules = 0
        thin_evidence = 0.07 <= gray < 0.12

        days_to_pay = rng.randint(95, 420) if not thin_evidence else rng.randint(150, 420)
        photos = rng.randint(0, 1) if thin_evidence else rng.randint(4, 42)
        geo = rng.uniform(0.20, 0.45) if thin_evidence else rng.uniform(0.62, 0.99)
        pay_day = days_to_pay
        cpu = rng.uniform(0.75, 1.25)
        # final cost ratio is partly predictable from observable mid-project
        # signals (current cost-per-unit estimate, agency pace) + noise — this
        # gives the overrun model a learnable signal.
        final_ratio = 0.55 + 0.45 * cpu + rng.gauss(0, 0.035)
        if slow_agency and rng.random() < 0.5:
            final_ratio += rng.uniform(0.06, 0.16)
        final_ratio = max(0.82, min(1.4, final_ratio))
        delay_days = rng.choice([0, 0, rng.randint(10, 60),
                                 rng.randint(95, 260) if (slow_agency or DISTRICTS[district][2] > 0.22) and rng.random() < 0.5 else rng.randint(10, 80)])
        round_bill = rng.random() < 0.06
        if round_bill:
            amount = round(amount / 100000) * 100000

        projects.append({
            "project_id": p, "work_description": desc, "district": district,
            "mp_name": rng.choice(MPS), "agency": agency, "work_type": wtype,
            "sanctioned_amount": amount,
            "sanctioned_date": sdate.isoformat(),
            "payment_date": _d(pay_day, sdate),
            "days_sanction_to_payment": days_to_pay,
            "completion_pct_at_payment": round(comp_at_pay, 1),
            "completion_pct_final": rng.uniform(88, 100),
            "final_cost": round(amount * final_ratio, 2),
            "geo_tag_match_score": round(geo, 3),
            "site_photos_uploaded": photos,
            "geo_lat": round(dlat + rng.uniform(-0.28, 0.28), 5),
            "geo_lon": round(dlon + rng.uniform(-0.28, 0.28), 5),
            "cost_per_unit_ratio": round(cpu, 3),
            "agency_prior_flagged_count": prior_flags,
            "round_number_bill": round_bill,
            "expected_duration_days": rng.randint(120, 300),
            "actual_delay_days": delay_days,
        })
        truth.append({"project_id": p, "pattern": "normal",
                      "expected": "no pathological stack; gray single-deviation ok",
                      "n_rule_violations": n_rules})
        normal_ledger(p, sdate, amount, rng)

    # ------------------------------------------------------------------
    # 2) The 6 Assam-pattern projects (ground truth: Barpeta 2023 case)
    # ------------------------------------------------------------------
    scam_agency = "Sewa Constructions & Suppliers (Guwahati)"
    scam_agency2 = "Pragati Associates (Nagaon)"
    assam_specs = [
        # The 3 documented Barpeta roads under Ajit Bhuyan (RS): ~Rs 28 lakh total
        dict(district="Barpeta", mp="Ajit Bhuyan (RS)", agency=scam_agency,
             amount=950000, desc="Construction of CC road from Sarbhog to Jania (Phase I)"),
        dict(district="Barpeta", mp="Ajit Bhuyan (RS)", agency=scam_agency,
             amount=930000, desc="Construction of CC road from Chenga to Baghbar village"),
        dict(district="Barpeta", mp="Ajit Bhuyan (RS)", agency=scam_agency,
             amount=920000, desc="Construction of CC road at Simlunguri village road"),
        # Replication pattern-copies in neighbouring districts
        dict(district="Kamrup", mp="Queen Ojha (RS)", agency=scam_agency,
             amount=1450000, desc="Construction of CC road from Belsor to Hahara"),
        dict(district="Nagaon", mp="Birendra Prasad Baishya (RS)", agency=scam_agency2,
             amount=1750000, desc="Construction of village RCC road at Puranigudam"),
        dict(district="Nagaon", mp="Birendra Prasad Baishya (RS)", agency=scam_agency2,
             amount=1580000, desc="Widening and metalling of road from Raha to Jamunamukh"),
    ]
    for spec in assam_specs:
        p = pid()
        dlat, dlon, _ = DISTRICTS[spec["district"]]
        sdate = date(2023, 2, rng.randint(1, 20))  # early 2023, like the case
        days_to_pay = rng.randint(16, 42)          # paid suspiciously fast
        projects.append({
            "project_id": p, "work_description": spec["desc"],
            "district": spec["district"], "mp_name": spec["mp"],
            "agency": spec["agency"], "work_type": "Road",
            "sanctioned_amount": spec["amount"],
            "sanctioned_date": sdate.isoformat(),
            "payment_date": _d(days_to_pay, sdate),
            "days_sanction_to_payment": days_to_pay,
            "completion_pct_at_payment": round(rng.uniform(0, 12), 1),  # never built
            "completion_pct_final": round(rng.uniform(0, 12), 1),
            "final_cost": round(spec["amount"] * rng.uniform(0.95, 1.05), 2),
            "geo_tag_match_score": round(rng.uniform(0.05, 0.28), 3),
            "site_photos_uploaded": 0,
            "geo_lat": round(dlat + rng.uniform(-0.15, 0.15), 5),
            "geo_lon": round(dlon + rng.uniform(-0.15, 0.15), 5),
            "cost_per_unit_ratio": round(rng.uniform(1.85, 2.60), 3),
            "agency_prior_flagged_count": AGENCIES[spec["agency"]][0],  # repeat-flagged
            "round_number_bill": True,               # 9.5L / 9.3L / 9.2L style
            "expected_duration_days": rng.randint(150, 240),
            "actual_delay_days": rng.randint(280, 420),
        })
        truth.append({
            "project_id": p, "pattern": "assam_scam",
            "expected": "must rank in top risk (top-10) of the whole dataset",
            "n_rule_violations": 2,
        })
        # Ledger looks financially complete (money moved, UC even filed) —
        # the crime is project-level: paid with nothing on the ground.
        normal_ledger(p, sdate, spec["amount"], rng)

    # ------------------------------------------------------------------
    # 3) Ledger-only dirty projects (clean project features)
    # ------------------------------------------------------------------
    def clean_project(district: str, amount: float, wtype: str, desc: str,
                      agency: str) -> dict:
        p = pid()
        dlat, dlon, _ = DISTRICTS[district]
        sdate = san_date()
        days_to_pay = rng.randint(120, 300)
        return {
            "project_id": p, "work_description": desc, "district": district,
            "mp_name": rng.choice(MPS), "agency": agency, "work_type": wtype,
            "sanctioned_amount": amount, "sanctioned_date": sdate.isoformat(),
            "payment_date": _d(days_to_pay, sdate),
            "days_sanction_to_payment": days_to_pay,
            "completion_pct_at_payment": round(rng.uniform(82, 99), 1),
            "completion_pct_final": rng.uniform(95, 100),
            "final_cost": round(amount * rng.uniform(0.92, 1.10), 2),
            "geo_tag_match_score": round(rng.uniform(0.75, 0.98), 3),
            "site_photos_uploaded": rng.randint(8, 40),
            "geo_lat": round(dlat + rng.uniform(-0.2, 0.2), 5),
            "geo_lon": round(dlon + rng.uniform(-0.2, 0.2), 5),
            "cost_per_unit_ratio": round(rng.uniform(0.85, 1.2), 3),
            "agency_prior_flagged_count": AGENCIES[agency][0],
            "round_number_bill": False,
            "expected_duration_days": rng.randint(140, 280),
            "actual_delay_days": rng.randint(0, 40),
        }, sdate

    clean_agencies = [a for a in AGENCIES if a not in (scam_agency, scam_agency2)]

    # 3a. Structuring x4: vendor payment split into chunks just under Rs 5 lakh
    for i in range(4):
        district = rng.choice(list(DISTRICTS))
        agency = rng.choice(clean_agencies)
        n_splits = rng.choice([3, 4, 4])
        amount = round(n_splits * rng.uniform(4.35, 4.95) * 100000, -3)
        desc = rng.choice(WORK_TYPES["Electrification" if i % 2 else "Sanitation"]).format(
            a=rng.choice(VILLAGES), b=rng.choice(VILLAGES))
        proj, sdate = clean_project(district, amount,
                                    "Electrification" if i % 2 else "Sanitation",
                                    desc, agency)
        projects.append(proj)
        truth.append({"project_id": proj["project_id"], "pattern": "structuring",
                      "expected": "passes project-level rule/ML; caught by fund-flow",
                      "n_rule_violations": 0})
        d0 = 0; d1 = d0 + rng.randint(15, 40); d2 = d1 + rng.randint(10, 35)
        add_ledger_row(proj["project_id"], S_SANCTION, d0, amount, sdate)
        add_ledger_row(proj["project_id"], S_DISTRICT, d1, amount * 0.998, sdate)
        add_ledger_row(proj["project_id"], S_AGENCY, d2, amount * 0.995, sdate)
        base_split_day = d2 + rng.randint(20, 60)
        splits = sorted(rng.sample(range(0, 22), n_splits))
        # splits sum to ~99% of the agency release (vendor total stays within
        # leakage tolerance) — the anomaly here is the SPLIT pattern itself
        agency_amt = amount * 0.995
        w = [rng.uniform(0.92, 1.08) for _ in range(n_splits)]
        target_total = agency_amt * 0.99
        amts = [target_total * wi / sum(w) for wi in w]
        # nudge each into the just-under-threshold band, then rescale to keep sum
        lo, hi = (config.STRUCTURING_THRESHOLD * 0.87,
                  config.STRUCTURING_THRESHOLD * 0.995)
        amts = [min(max(a, lo), hi) for a in amts]
        scale = target_total / sum(amts)
        amts = [a * scale for a in amts]
        for j, off in enumerate(splits):
            add_ledger_row(proj["project_id"], S_VENDOR, base_split_day + off,
                           round(amts[j], 2), sdate,
                           note=f"vendor payment part {j+1}/{n_splits}")
        total_paid = sum(r["amount"] for r in ledger[-n_splits:])
        uc_day = base_split_day + splits[-1] + rng.randint(25, 70)
        add_ledger_row(proj["project_id"], S_UC, uc_day, round(total_paid, 2), sdate)

    # 3b. Stage delay x3: funds parked 240-380 days at a stage
    for _ in range(3):
        district = rng.choice(list(DISTRICTS))
        agency = rng.choice([a for a, (_, slow) in AGENCIES.items() if slow])
        amount = round(rng.uniform(12, 40) * 100000, -3)
        desc = rng.choice(WORK_TYPES["Water"]).format(
            a=rng.choice(VILLAGES), b=rng.choice(VILLAGES))
        proj, sdate = clean_project(district, amount, "Water", desc, agency)
        projects.append(proj)
        truth.append({"project_id": proj["project_id"], "pattern": "stage_delay",
                      "expected": "passes project-level rule/ML; caught by fund-flow",
                      "n_rule_violations": 0})
        d0 = 0; d1 = d0 + rng.randint(15, 40)
        d2 = d1 + rng.randint(240, 380)              # parked at district stage
        d3 = d2 + rng.randint(20, 70)
        d4 = d3 + rng.randint(30, 80)
        for stage, day in zip(config.STAGES, [d0, d1, d2, d3, d4]):
            add_ledger_row(proj["project_id"], stage, day,
                           amount * rng.uniform(0.99, 1.0), sdate)

    # 3c. Leakage x2: amount drops >10% between hand-offs (skimming)
    for _ in range(2):
        district = rng.choice(list(DISTRICTS))
        agency = rng.choice(clean_agencies)
        amount = round(rng.uniform(15, 45) * 100000, -3)
        desc = rng.choice(WORK_TYPES["Building"]).format(a=rng.choice(VILLAGES), b=rng.choice(VILLAGES))
        proj, sdate = clean_project(district, amount, "Building", desc, agency)
        projects.append(proj)
        truth.append({"project_id": proj["project_id"], "pattern": "leakage",
                      "expected": "passes project-level rule/ML; caught by fund-flow",
                      "n_rule_violations": 0})
        d0 = 0; d1 = d0 + rng.randint(15, 45); d2 = d1 + rng.randint(10, 35)
        d3 = d2 + rng.randint(25, 70); d4 = d3 + rng.randint(25, 70)
        leaked = amount * rng.uniform(0.72, 0.88)
        for stage, day, amt in zip(config.STAGES, [d0, d1, d2, d3, d4],
                                   [amount, amount * 0.997, leaked,
                                    leaked * 0.99, leaked * 0.995]):
            add_ledger_row(proj["project_id"], stage, day, amt, sdate)

    # 3d. Missing UC x2: vendor paid long ago, no utilization certificate ever
    for _ in range(2):
        district = rng.choice(list(DISTRICTS))
        agency = rng.choice(clean_agencies)
        amount = round(rng.uniform(8, 30) * 100000, -3)
        desc = rng.choice(WORK_TYPES["Road"]).format(
            a=rng.choice(VILLAGES), b=rng.choice(VILLAGES))
        proj, sdate = clean_project(district, amount, "Road", desc, agency)
        # force payment far enough in the past for the UC window to have elapsed
        vendor_day = (AS_OF - sdate).days - rng.randint(150, 400)
        if vendor_day < 60:
            sdate = AS_OF - timedelta(days=rng.randint(330, 500))
            vendor_day = rng.randint(150, 300)
        proj["sanctioned_date"] = sdate.isoformat()
        proj["days_sanction_to_payment"] = vendor_day
        proj["payment_date"] = _d(vendor_day, sdate)
        projects.append(proj)
        truth.append({"project_id": proj["project_id"], "pattern": "missing_uc",
                      "expected": "passes project-level rule/ML; caught by fund-flow",
                      "n_rule_violations": 0})
        d0 = 0; d1 = d0 + rng.randint(15, 45); d2 = d1 + rng.randint(10, 35)
        for stage, day, amt in [(S_SANCTION, d0, amount),
                                (S_DISTRICT, d1, amount * 0.998),
                                (S_AGENCY, d2, amount * 0.995),
                                (S_VENDOR, vendor_day, amount * 0.99)]:
            add_ledger_row(proj["project_id"], stage, day, amt, sdate)
        # deliberately NO utilization certificate row

    # ------------------------------------------------------------------
    # 4) Duplicate-work pairs x3 (same asset claimed twice)
    # ------------------------------------------------------------------
    dup_templates = [
        ("Construction of CC drain along Sarbhog market road",
         "Construction of RCC drain at Sarbhog market approach"),
        ("Installation of 20 solar street lights at Chenga village",
         "Providing and installation of twenty solar street lights in Chenga"),
        ("Construction of community hall at Puranigudam",
         "Construction of community hall building in Puranigudam area"),
    ]
    for desc_a, desc_b in dup_templates:
        district = rng.choice(list(DISTRICTS))
        dlat, dlon, _ = DISTRICTS[district]
        lat = dlat + rng.uniform(-0.15, 0.15)
        lon = dlon + rng.uniform(-0.15, 0.15)
        amount = round(rng.uniform(10, 35) * 100000, -3)
        agencies = rng.sample(clean_agencies, 2)
        for k, (desc, ag) in enumerate(zip([desc_a, desc_b], agencies)):
            p = pid()
            sdate = san_date()
            days_to_pay = rng.randint(120, 300)
            base = {
                "project_id": p, "work_description": desc, "district": district,
                "mp_name": rng.sample(MPS, 2)[k], "agency": ag,
                "work_type": "Sanitation" if "drain" in desc.lower() else
                             ("Electrification" if "solar" in desc.lower() else "Building"),
                "sanctioned_amount": round(amount * rng.uniform(0.95, 1.05), -3),
                "sanctioned_date": sdate.isoformat(),
                "payment_date": _d(days_to_pay, sdate),
                "days_sanction_to_payment": days_to_pay,
                "completion_pct_at_payment": round(rng.uniform(78, 96), 1),
                "completion_pct_final": rng.uniform(90, 100),
                "final_cost": round(amount * rng.uniform(0.95, 1.1), 2),
                "geo_tag_match_score": round(rng.uniform(0.7, 0.97), 3),
                "site_photos_uploaded": rng.randint(6, 30),
                # nearly identical coordinates (<800 m apart)
                "geo_lat": round(lat + rng.uniform(-0.004, 0.004), 5),
                "geo_lon": round(lon + rng.uniform(-0.004, 0.004), 5),
                "cost_per_unit_ratio": round(rng.uniform(0.8, 1.15), 3),
                "agency_prior_flagged_count": AGENCIES[ag][0],
                "round_number_bill": False,
                "expected_duration_days": rng.randint(130, 260),
                "actual_delay_days": rng.randint(0, 60),
            }
            projects.append(base)
            truth.append({"project_id": p, "pattern": "duplicate_pair",
                          "expected": "detected by NLP similarity + geo proximity",
                          "n_rule_violations": 0})
            normal_ledger(p, sdate, base["sanctioned_amount"], rng)

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    proj_path = os.path.join(out_dir, "projects.csv")
    ledger_path = os.path.join(out_dir, "ledger.csv")
    truth_path = os.path.join(out_dir, "truth.csv")
    meta_path = os.path.join(out_dir, "meta.json")

    fields = list(projects[0].keys())
    with open(proj_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(projects)
    with open(ledger_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(ledger[0].keys()))
        w.writeheader()
        w.writerows(ledger)
    with open(truth_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["project_id", "pattern", "expected",
                                          "n_rule_violations"])
        w.writeheader()
        w.writerows(truth)
    with open(meta_path, "w") as f:
        json.dump({
            "seed": seed, "as_of": config.DEMO_AS_OF,
            "n_projects": len(projects), "n_ledger_rows": len(ledger),
            "pattern_counts": _count_patterns(truth),
            "ground_truth_note": (
                "assam_scam pattern replicates the documented 2023 Barpeta, Assam "
                "MPLAD fund case (Rs 28 lakh / 3 roads / Rajya Sabha MP Ajit "
                "Bhuyan's fund / paid before 75% completion / roads never built)."),
        }, f, indent=2)
    return proj_path, ledger_path, truth_path


def _count_patterns(truth: list[dict]) -> dict:
    out: dict[str, int] = {}
    for t in truth:
        out[t["pattern"]] = out.get(t["pattern"], 0) + 1
    return out


if __name__ == "__main__":
    p, l, t = generate()
    print("projects:", p)
    print("ledger:  ", l)
    print("truth:   ", t)
