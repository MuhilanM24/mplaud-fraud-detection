"""Isolation-Forest anomaly detection over engineered project features.

The model is unsupervised and trains on whatever feature columns the dataset
provides (>= 2 required). Scores are converted to within-dataset percentiles
so the ML component is comparable across datasets and scales.
"""
from __future__ import annotations

import numpy as np
import sklearn.ensemble as sk_ensemble
from sklearn.preprocessing import StandardScaler


class AnomalyEngine:
    def __init__(self, n_estimators: int = 300, contamination: float = 0.10,
                 random_state: int = 42):
        self.n_estimators = n_estimators
        self.contamination = contamination
        self.random_state = random_state
        self.model = None
        self.scaler = None
        self.columns: list[str] = []
        self.fitted = False

    def fit(self, matrix) -> "AnomalyEngine":
        X = np.asarray(matrix, dtype=float)
        if X.shape[0] < 5 or X.shape[1] < 1:
            raise ValueError("Need >= 5 rows and >= 1 feature to fit IsolationForest")
        self.columns = list(matrix.columns) if hasattr(matrix, "columns") else \
            [f"f{i}" for i in range(X.shape[1])]
        self.scaler = StandardScaler().fit(X)
        self.model = sk_ensemble.IsolationForest(
            n_estimators=self.n_estimators, contamination=self.contamination,
            random_state=self.random_state, n_jobs=-1).fit(self.scaler.transform(X))
        self.fitted = True
        return self

    def score(self, matrix) -> dict:
        """Return {index -> {ml_score (0-100 percentile), raw_decision}}."""
        if not self.fitted:
            raise RuntimeError("AnomalyEngine not fitted")
        X = np.asarray(matrix, dtype=float)
        # align columns if needed
        if hasattr(matrix, "columns") and list(matrix.columns) != self.columns:
            matrix = matrix[[c for c in self.columns if c in matrix.columns]]
            X = np.asarray(matrix, dtype=float)
        raw = self.model.decision_function(self.scaler.transform(X))  # higher = more normal
        # percentile rank, oriented so the MOST anomalous project -> ~100
        order = raw.argsort().argsort()          # rank of raw (0 = most anomalous)
        pct = (len(raw) - 1 - order) / max(len(raw) - 1, 1) * 100.0
        return {i: {"ml_score": float(pct[i]), "raw_decision": float(raw[i])}
                for i in range(len(raw))}

    def top_contributing_features(self, row: dict, all_rows_median: dict) -> list[tuple[str, float]]:
        """Rough per-feature extremeness (|robust z|) — used for BYO deviation
        explanations, not for the demo (which uses SHAP/tree attribution)."""
        import pandas as pd
        s = pd.Series({c: row.get(c) for c in self.columns}, dtype=float)
        med = pd.Series(all_rows_median, dtype=float)
        mad = (pd.Series({c: row.get(c) for c in self.columns}, dtype=float) - med).abs()
        # use the full dataset MADs if provided via stored medians
        out = []
        for c in self.columns:
            v = row.get(c)
            if v is None or (isinstance(v, float) and v != v):
                continue
            out.append((c, abs(float(v) - float(med.get(c, v))) /
                        (abs(float(mad.get(c, 1.0))) + 1e-9)))
        out.sort(key=lambda t: t[1], reverse=True)
        return out
