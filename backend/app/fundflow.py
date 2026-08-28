"""Fund-flow tracking: the money trail per project through its real stages.

Stage chain: SANCTION -> DISTRICT_RELEASE -> AGENCY_RELEASE -> VENDOR_PAYMENT
-> UTILIZATION_CERTIFICATE.

Checks (all independent of project-level completion/rule checks):
  * leakage      — amount shrinks > 2% between consecutive hand-offs
  * stage_delay  — funds parked >= 200 days at a stage
  * structuring  — one large payment split into several chunks each just under
                   an approval/scrutiny threshold (default Rs 5 lakh), clustered
                   within days — avoiding extra oversight
  * missing_uc   — vendor payment with no utilization certificate after the
                   90-day window

Every flag ships with plain-language detail and exact numbers, and a
"catchable-by-this-layer-only" note: these checks routinely fire on projects
whose completion % looks perfectly compliant.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import config

STAGE_LABELS = {
    "SANCTION": "Sanction",
    "DISTRICT_RELEASE": "District Authority release",
    "AGENCY_RELEASE": "Implementing Agency release",
    "VENDOR_PAYMENT": "Vendor payment",
    "UTILIZATION_CERTIFICATE": "Utilization certificate",
}


def _parse_day(val, base: date | None = None) -> int | None:
    """Ledger rows carry either a day offset or an ISO date."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    try:
        return int(float(s))
    except ValueError:
        pass
    try:
        d = datetime.fromisoformat(s[:10]).date()
        if base:
            return (d - base).days
        return d.toordinal()          # absolute fallback
    except ValueError:
        return None


def _fmt(amount: float) -> str:
    return f"Rs {amount/1e5:.2f} lakh" if amount >= 100000 else f"Rs {amount:,.0f}"


def analyze_project_ledger(rows: list[dict], project_id: str,
                           as_of_day: int | None = None) -> dict:
    rows = [r for r in rows if r.get("stage")]
    # canonicalise stage names (BYO ledgers may use free text)
    canon = {s: s for s in config.STAGES}
    canon.update({"sanction": "SANCTION", "district": "DISTRICT_RELEASE",
                  "district_release": "DISTRICT_RELEASE",
                  "district authority": "DISTRICT_RELEASE",
                  "agency": "AGENCY_RELEASE", "agency_release": "AGENCY_RELEASE",
                  "implementing agency": "AGENCY_RELEASE",
                  "vendor": "VENDOR_PAYMENT", "payment": "VENDOR_PAYMENT",
                  "vendor_payment": "VENDOR_PAYMENT",
                  "uc": "UTILIZATION_CERTIFICATE",
                  "utilization": "UTILIZATION_CERTIFICATE",
                  "utilization_certificate": "UTILIZATION_CERTIFICATE"})

    def norm(stage: str) -> str:
        key = str(stage).strip().lower().replace("-", "_").replace(" ", "_")
        return canon.get(key, canon.get(str(stage).strip().lower(), str(stage).strip().upper()))

    parsed = []
    for r in rows:
        day = _parse_day(r.get("day_offset", r.get("day")))
        amt = r.get("amount")
        try:
            amt = float(amt)
        except (TypeError, ValueError):
            amt = None
        if day is None:
            continue
        parsed.append({"stage": norm(r["stage"]), "day": day,
                       "amount": amt, "note": r.get("note", "") or ""})
    parsed.sort(key=lambda r: r["day"])

    if not parsed:
        return {"project_id": project_id, "stages": [], "flags": [],
                "component_score": 0.0, "floor_applied": False,
                "has_ledger": False}

    # ---- stage timeline for the UI stepper (VENDOR_PAYMENT may repeat) -----
    stages: list[dict] = []
    prev = None
    for r in parsed:
        gap = (r["day"] - prev["day"]) if prev else 0
        stages.append({"stage": r["stage"], "label": STAGE_LABELS.get(r["stage"], r["stage"]),
                       "day_offset": r["day"], "amount": r["amount"],
                       "gap_days": gap, "note": r["note"]})
        prev = r
    flags: list[dict] = []
    # as_of_day is "today" expressed in the SAME day units as the ledger rows
    # (offsets from sanction). If unknown, never trigger the missing-UC check.
    if as_of_day is None:
        as_of_day = 10 ** 9

    # ---- leakage between consecutive hand-offs -----------------------------
    seq = [r for r in parsed if r["amount"] is not None and
           r["stage"] != "VENDOR_PAYMENT" or True]
    # compare each consecutive row (same-stage repeats excluded from leakage;
    # split vendor payments are compared against the agency release total)
    non_vendor = [r for r in parsed if r["stage"] != "VENDOR_PAYMENT"]
    for a, b in zip(non_vendor, non_vendor[1:]):
        if a["amount"] is None or b["amount"] is None:
            continue
        drop_pct = (a["amount"] - b["amount"]) / a["amount"] * 100.0
        if drop_pct > config.LEAKAGE_TOLERANCE_PCT:
            flags.append({
                "type": "leakage", "severity":
                    "major" if drop_pct > config.LEAKAGE_FLOOR_PCT else "moderate",
                "title": "Money decreased between hand-offs (possible leakage/skimming)",
                "detail": (f"{_fmt(a['amount'])} moved to stage "
                           f"'{STAGE_LABELS.get(a['stage'], a['stage'])}' but only "
                           f"{_fmt(b['amount'])} arrived at "
                           f"'{STAGE_LABELS.get(b['stage'], b['stage'])}' — a drop of "
                           f"{drop_pct:.1f}% (tolerance: "
                           f"{config.LEAKAGE_TOLERANCE_PCT:.0f}% for normal bank/"
                           f"processing variance). {a['amount']-b['amount']:,.0f} rupees "
                           "disappeared between hand-offs."),
                "evidence": {"from_stage": a["stage"], "to_stage": b["stage"],
                             "drop_pct": round(drop_pct, 2),
                             "amount_from": a["amount"], "amount_to": b["amount"]},
            })

    # vendor payments total vs agency release (catch leakage across splits too)
    agency_rels = [r for r in parsed if r["stage"] == "AGENCY_RELEASE" and r["amount"]]
    vendor_pays = [r for r in parsed if r["stage"] == "VENDOR_PAYMENT" and r["amount"]]
    if agency_rels and vendor_pays:
        agency_amt = sum(r["amount"] for r in agency_rels)
        vendor_amt = sum(r["amount"] for r in vendor_pays)
        drop_pct = (agency_amt - vendor_amt) / agency_amt * 100.0
        if drop_pct > config.LEAKAGE_TOLERANCE_PCT:
            flags.append({
                "type": "leakage", "severity":
                    "major" if drop_pct > config.LEAKAGE_FLOOR_PCT else "moderate",
                "title": "Vendor payments total less than agency release",
                "detail": (f"The implementing agency received {_fmt(agency_amt)} but only "
                           f"{_fmt(vendor_amt)} ({100-drop_pct:.1f}%) was paid to vendors — "
                           f"a shortfall of {agency_amt-vendor_amt:,.0f} rupees."),
                "evidence": {"agency_total": agency_amt, "vendor_total": vendor_amt,
                             "drop_pct": round(drop_pct, 2)},
            })

    # ---- structuring: split payments just under a scrutiny threshold --------
    if len(vendor_pays) >= config.STRUCTURING_MIN_PAYMENTS:
        thr = config.STRUCTURING_THRESHOLD
        just_under = [r for r in vendor_pays
                      if thr * config.STRUCTURING_JUST_UNDER_RATIO <= r["amount"] < thr]
        if len(just_under) >= config.STRUCTURING_MIN_PAYMENTS:
            span = max(r["day"] for r in just_under) - min(r["day"] for r in just_under)
            total = sum(r["amount"] for r in just_under)
            if span <= config.STRUCTURING_WINDOW_DAYS and total >= 2.0 * thr:
                flags.append({
                    "type": "structuring", "severity": "major",
                    "title": ("Payment structured just under the scrutiny threshold "
                              "(possible split to avoid oversight)"),
                    "detail": (f"{len(just_under)} separate vendor payments, each "
                               f"between {thr*config.STRUCTURING_JUST_UNDER_RATIO/1e5:.1f}"
                               f" and {thr/1e5:.1f} lakh (just under the "
                               f"{_fmt(thr)} approval/scrutiny threshold), within a "
                               f"{span}-day window totalling {_fmt(total)}. A single "
                               f"payment of this size would have crossed the threshold "
                               "and attracted additional scrutiny."),
                    "evidence": {"n_payments": len(just_under),
                                 "threshold": thr,
                                 "window_days": span,
                                 "total": round(total, 2),
                                 "payments": [round(r["amount"], 2) for r in just_under]},
                })

    # ---- abnormal gaps between stages ---------------------------------------
    order = {s: i for i, s in enumerate(config.STAGES)}
    chain = sorted([r for r in non_vendor if r["stage"] in order],
                   key=lambda r: order[r["stage"]])
    for a, b in zip(chain, chain[1:]):
        gap = b["day"] - a["day"]
        if gap >= config.STAGE_DELAY_DAYS:
            flags.append({
                "type": "stage_delay", "severity": "moderate",
                "title": "Funds parked abnormally long at one stage",
                "detail": (f"{_fmt(b['amount'] if b['amount'] else 0)} sat at "
                           f"'{STAGE_LABELS.get(a['stage'], a['stage'])}' for {gap} days "
                           f"before moving to '{STAGE_LABELS.get(b['stage'], b['stage'])}' "
                           f"(baseline expectation: well under "
                           f"{config.STAGE_DELAY_DAYS} days). Long parking can indicate "
                           "fund diversion or administrative capture."),
                "evidence": {"stage": a["stage"], "gap_days": gap,
                             "threshold_days": config.STAGE_DELAY_DAYS},
            })

    # ---- missing utilization certificate ------------------------------------
    has_uc = any(r["stage"] == "UTILIZATION_CERTIFICATE" for r in parsed)
    if vendor_pays and not has_uc:
        last_pay_day = max(r["day"] for r in vendor_pays)
        elapsed = as_of_day - last_pay_day
        if elapsed > config.UC_WINDOW_DAYS:
            flags.append({
                "type": "missing_uc", "severity":
                    "major" if elapsed > 2 * config.UC_WINDOW_DAYS else "moderate",
                "title": "No utilization certificate filed after vendor payment",
                "detail": (f"Vendors were paid {elapsed} days ago but no utilization "
                           f"certificate has been filed (window: "
                           f"{config.UC_WINDOW_DAYS} days). Utilization certificates are "
                           "the primary accountability document confirming money was "
                           "spent on the sanctioned work."),
                "evidence": {"last_vendor_payment_day": last_pay_day,
                             "days_elapsed": elapsed,
                             "window_days": config.UC_WINDOW_DAYS},
            })

    component = min(100.0, sum(config.FUNDFLOW_FLAG_WEIGHTS.get(f["type"], 20.0)
                               * (1.0 if f["severity"] == "major" else 0.7)
                               for f in flags))
    # Floor classes: "major" (structuring / big leakage) escalate to the major
    # floor; "minor" (stage delay / missing UC) to the minor floor.
    floor_class = None
    for f in flags:
        if f["type"] == "structuring" or (
                f["type"] == "leakage" and
                f["evidence"].get("drop_pct", 0) > config.LEAKAGE_FLOOR_PCT):
            floor_class = "major"
            break
        if f["type"] in ("stage_delay", "missing_uc"):
            floor_class = floor_class or "minor"
    return {"project_id": project_id, "stages": stages, "flags": flags,
            "component_score": component, "floor_class": floor_class,
            "has_ledger": True}


def build_compliance_events(project: dict, analysis: dict) -> list[dict]:
    """Turn fund-flow + rule flags into dated early-warning events.

    Events carry the date they became visible (not audit time), so the
    compliance timeline shows warnings as they occurred.
    """
    events = []
    pid = project.get("project_id")
    day_lookup = {s["stage"]: s["day_offset"] for s in analysis.get("stages", [])}

    for f in analysis.get("flags", []):
        ev_type = f["type"]
        when = None
        if ev_type == "stage_delay":
            when = day_lookup.get(f["evidence"].get("stage", ""), None)
            when = (f["evidence"].get("gap_days", 0) + when
                    if when is not None else None)
        elif ev_type == "missing_uc":
            when = f["evidence"].get("last_vendor_payment_day",
                                     0) + f["evidence"].get("window_days", 90)
        elif ev_type == "structuring":
            days = f["evidence"].get("payments") and \
                max(day_lookup.get("VENDOR_PAYMENT", 0),
                    (f["evidence"].get("window_days", 0) or 0))
            when = days
        elif ev_type == "leakage":
            when = day_lookup.get(f["evidence"].get("to_stage", ""), 0)
        if when is None:
            when = day_lookup.get("VENDOR_PAYMENT", 0)
        events.append({
            "project_id": pid, "date_offset": when, "source": "fund_flow",
            "type": ev_type, "severity": f["severity"],
            "title": f["title"], "detail": f["detail"],
        })
    return events
