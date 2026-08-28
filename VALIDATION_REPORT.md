# MPLAUD Validation Report

Dataset: 203 projects, 1023 ledger rows, as_of=2024-06-30
Pattern mix: {'normal': 180, 'assam_scam': 6, 'structuring': 4, 'stage_delay': 3, 'leakage': 2, 'missing_uc': 2, 'duplicate_pair': 6}

### PASS — V1 Assam-pattern recall
- assam_scam projects: 6
- ranks of assam projects (1 = riskiest): [1, 2, 3, 4, 5, 6]
- recall@10 = 6/6, recall@15 = 6/6
- bands: ['Critical', 'Critical', 'Critical', 'Critical', 'Critical', 'High']; all flagged for investigation: True
- scores: [78.1, 78.3, 77.9, 78.5, 75.2, 74.8]
- top-10 riskiest overall:
    1. AS-2023-0184 score=78.5 band=Critical pattern=assam_scam
    2. AS-2023-0182 score=78.3 band=Critical pattern=assam_scam
    3. AS-2023-0181 score=78.1 band=Critical pattern=assam_scam
    4. AS-2023-0183 score=77.9 band=Critical pattern=assam_scam
    5. AS-2023-0185 score=75.2 band=Critical pattern=assam_scam
    6. AS-2023-0186 score=74.8 band=High pattern=assam_scam
    7. AS-2023-0187 score=60.0 band=High pattern=structuring
    8. AS-2023-0188 score=60.0 band=High pattern=structuring
    9. AS-2023-0189 score=60.0 band=High pattern=structuring
    10. AS-2023-0190 score=60.0 band=High pattern=structuring

### PASS — V2 Fund-flow catches ledger-only risk invisible to project checks
- 11 ledger-only dirty projects (clean project features; risk only in the payment ledger)
- requirement per project: no rule violations, ML anomaly component < 60 (passes project-level checks), yet >= 1 fund-flow flag and final status Flagged for investigation
  - AS-2023-0187 (structuring): rule_violations=0 score_without_ledger=3.0 (Not flagged), with_ledger=60.0 (Flagged for investigation) fundflow_flags=['structuring'] -> CAUGHT by fund-flow only
  - AS-2023-0188 (structuring): rule_violations=0 score_without_ledger=4.3 (Not flagged), with_ledger=60.0 (Flagged for investigation) fundflow_flags=['structuring'] -> CAUGHT by fund-flow only
  - AS-2023-0189 (structuring): rule_violations=0 score_without_ledger=9.1 (Not flagged), with_ledger=60.0 (Flagged for investigation) fundflow_flags=['structuring'] -> CAUGHT by fund-flow only
  - AS-2023-0190 (structuring): rule_violations=0 score_without_ledger=6.0 (Not flagged), with_ledger=60.0 (Flagged for investigation) fundflow_flags=['structuring'] -> CAUGHT by fund-flow only
  - AS-2023-0191 (stage_delay): rule_violations=0 score_without_ledger=12.0 (Not flagged), with_ledger=55.0 (Flagged for investigation) fundflow_flags=['stage_delay'] -> CAUGHT by fund-flow only
  - AS-2023-0192 (stage_delay): rule_violations=0 score_without_ledger=2.0 (Not flagged), with_ledger=55.0 (Flagged for investigation) fundflow_flags=['stage_delay'] -> CAUGHT by fund-flow only
  - AS-2023-0193 (stage_delay): rule_violations=0 score_without_ledger=3.3 (Not flagged), with_ledger=55.0 (Flagged for investigation) fundflow_flags=['stage_delay'] -> CAUGHT by fund-flow only
  - AS-2023-0194 (leakage): rule_violations=0 score_without_ledger=21.2 (Not flagged), with_ledger=60.0 (Flagged for investigation) fundflow_flags=['leakage'] -> CAUGHT by fund-flow only
  - AS-2023-0195 (leakage): rule_violations=0 score_without_ledger=31.8 (Not flagged), with_ledger=60.0 (Flagged for investigation) fundflow_flags=['leakage'] -> CAUGHT by fund-flow only
  - AS-2023-0196 (missing_uc): rule_violations=0 score_without_ledger=19.3 (Not flagged), with_ledger=55.0 (Flagged for investigation) fundflow_flags=['missing_uc'] -> CAUGHT by fund-flow only
  - AS-2023-0197 (missing_uc): rule_violations=0 score_without_ledger=25.9 (Not flagged), with_ledger=55.0 (Flagged for investigation) fundflow_flags=['missing_uc'] -> CAUGHT by fund-flow only

### PASS — V3 Duplicate-work detection
- planted duplicate projects: 6; detected: 6
- NLP backend: TF-IDF (word 1-2 gram + char 3-5 gram) cosine similarity — offline fallback backend (similarity threshold 0.66, geo proximity 1.5 km)
  - sim=1.0 dist=0.232km: AS-2023-0049 <-> AS-2023-0195
  - sim=0.803 dist=0.154km: AS-2023-0202 <-> AS-2023-0203
  - sim=0.742 dist=0.675km: AS-2023-0198 <-> AS-2023-0199
  - sim=0.685 dist=0.261km: AS-2023-0200 <-> AS-2023-0201

### PASS — V4 Explainability coverage
- flagged projects: 19; with >= 3 direction-labelled explanation factors: 19
- method: SHAP (TreeExplainer) on a RandomForest surrogate trained to reproduce the fused risk score (surrogate R2=0.893)
- every rule violation carries a plain-language detail: True

### PASS — V5 Guardrail: no automated fraud verdicts
- distinct statuses emitted: ['Flagged for investigation', 'Not flagged']
- system guardrail text: This system never declares fraud. Every output is a risk signal for human investigation. All alerts route to investigators who make the final call.

### PASS — V6 Model quality reported
- surrogate fidelity: R2=0.893, MAE=3.32
- delay model: trained=True, AUC=0.874
- overrun model: trained=True, R2=0.319, MAE=0.051
- anomaly model: IsolationForest (10 features)

---
## Result: ALL CHECKS PASSED

> Ground-truth note: the assam_scam pattern replicates the documented 2023 Barpeta (Assam) MPLAD fund case (Rs 28 lakh sanctioned for 3 roads under RS MP Ajit Bhuyan's fund, roads never built, bills paid before the mandatory 75% completion threshold, officials suspended and chargesheeted). All other detectors are general-purpose heuristics, not derived from that case.
