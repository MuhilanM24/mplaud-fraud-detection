"""Explainable AI for every scored project.

Two tiers, auto-selected and ALWAYS labelled in output:
  1. Real SHAP (TreeExplainer) on a surrogate RandomForestRegressor trained to
     reproduce the fused risk score from the engineered features — used when
     the `shap` package imports cleanly (it is a pinned dependency).
  2. From-scratch tree-path attribution ("Saabas" method): walk each decision
     path in the surrogate forest, credit every split's feature with the
     change in expected prediction across that split. Used if SHAP is
     unavailable. Labelled clearly as an approximation, not SHAP.

For small bring-your-own datasets (< SURROGATE_MIN_ROWS rows) neither tree
method is used; the BYO module falls back to robust statistical deviation
ranking and labels the reduced rigor explicitly.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from . import config
from .features import FEATURE_LABELS


class SurrogateModel:
    """RandomForest surrogate trained to reproduce the fused risk score."""

    def __init__(self, n_estimators: int = 400, random_state: int = 42):
        self.model = RandomForestRegressor(
            n_estimators=n_estimators, min_samples_leaf=2,
            random_state=random_state, n_jobs=-1)
        self.columns: list[str] = []
        self.r2: float | None = None
        self.mae: float | None = None
        self.explainer_kind: str | None = None
        self._shap_explainer = None
        self._baseline = None

    def fit(self, matrix: pd.DataFrame, y: np.ndarray) -> "SurrogateModel":
        self.columns = list(matrix.columns)
        self.model.fit(matrix.values, y)
        preds = self.model.predict(matrix.values)
        ss_res = float(((y - preds) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum()) or 1e-9
        self.r2 = 1 - ss_res / ss_tot
        self.mae = float(np.abs(y - preds).mean())
        try:
            import shap  # noqa
            self._shap_explainer = shap.TreeExplainer(self.model)
            self.explainer_kind = "shap"
        except Exception:
            self._shap_explainer = None
            self.explainer_kind = "treewalk"
            self._baseline = None
        return self

    @property
    def method_label(self) -> str:
        if self.explainer_kind == "shap":
            return ("SHAP (TreeExplainer) on a RandomForest surrogate trained to "
                    "reproduce the fused risk score")
        return ("From-scratch tree-path attribution (Saabas-style decision-path "
                "credits) on a RandomForest surrogate — SHAP unavailable")

    def explain(self, row: pd.Series) -> dict:
        x = np.asarray([float(row[c]) for c in self.columns], dtype=float).reshape(1, -1)
        if self.explainer_kind == "shap":
            sv = np.asarray(self._shap_explainer.shap_values(x))
            sv = sv.reshape(-1)
            base = float(np.asarray(self._shap_explainer.expected_value).reshape(-1)[0])
            values = sv
        else:
            values, base = self._treewalk_attributions(x[0])
        contribs = {c: float(values[i]) for i, c in enumerate(self.columns)}
        return {"contributions": contribs, "baseline": base,
                "method": self.method_label, "kind": self.explainer_kind}

    # ------------------------------------------------------------------
    # From-scratch Saabas-style tree-path attribution (fallback)
    # ------------------------------------------------------------------
    def _treewalk_attributions(self, x: np.ndarray) -> tuple[np.ndarray, float]:
        total = np.zeros(len(self.columns))
        trees = self.model.estimators_
        for tree in trees:
            t = tree.tree_
            node = 0
            base_val = float(t.value[node][0][0])
            while t.children_left[node] != -1:
                f = int(t.feature[node])
                thr = float(t.threshold[node])
                child = t.children_left[node] if x[f] <= thr else t.children_right[node]
                delta = float(t.value[child][0][0]) - float(t.value[node][0][0])
                total[f] += delta
                node = child
            # normalise so leaf prediction is fully explained from tree mean
            leaf_val = float(t.value[node][0][0])
            explained = total.sum() / len(trees)
            # scale this tree's contributions so they sum to (leaf - forest behaviour)
            tree_explained = delta_sum = None
            node = 0
            path_sum = 0.0
            contrib = np.zeros(len(self.columns))
            while t.children_left[node] != -1:
                f = int(t.feature[node])
                thr = float(t.threshold[node])
                child = t.children_left[node] if x[f] <= thr else t.children_right[node]
                d = float(t.value[child][0][0]) - float(t.value[node][0][0])
                contrib[f] += d
                path_sum += d
                node = child
            leaf = float(t.value[node][0][0])
            if abs(path_sum) > 1e-12:
                contrib *= (leaf - base_val) / path_sum
            else:
                contrib[:] = 0.0
            total += contrib
        baseline = float(np.mean([tr.tree_.value[0][0][0] for tr in trees]))
        return total / len(trees), baseline

    def top_factors(self, row: pd.Series, k: int = 5) -> list[dict]:
        """Top-k factors with direction + plain-language labels."""
        exp = self.explain(row)
        items = sorted(exp["contributions"].items(),
                       key=lambda kv: abs(kv[1]), reverse=True)[:k]
        out = []
        for feat, val in items:
            if abs(val) < 1e-6:
                continue
            label, hint = FEATURE_LABELS.get(feat, (feat, ""))
            out.append({
                "feature": feat, "label": label, "hint": hint,
                "direction": "increases_risk" if val > 0 else "decreases_risk",
                "shap_value": round(val, 3),
                "feature_value": (None if row.get(feat) is None or
                                  (isinstance(row.get(feat), float) and
                                   row.get(feat) != row.get(feat))
                                  else float(row.get(feat))),
            })
        return out


def deviation_ranking(row: pd.Series, matrix: pd.DataFrame, k: int = 5) -> tuple[list[dict], str]:
    """Robust statistical deviation ranking (no surrogate; small datasets).

    Ranks the project's features by |robust z-score| (deviation from the
    dataset median, scaled by MAD) against the rest of the uploaded dataset.
    Clearly labelled as less rigorous than surrogate SHAP.
    """
    med = matrix.median(numeric_only=True)
    mad = (matrix - med).abs().median(numeric_only=True).replace(0, np.nan)
    out = []
    for c in matrix.columns:
        v = row.get(c)
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if v != v:
            continue
        m = float(mad.get(c, np.nan)) if mad.get(c) == mad.get(c) else None
        z = (v - float(med.get(c, v))) / (1.4826 * m) if m else 0.0
        if abs(z) < 0.3:
            continue
        label, hint = FEATURE_LABELS.get(c, (c, ""))
        # direction: for "higher-is-safer" features, low values increase risk
        higher_safer = c in ("completion_pct_at_payment", "geo_tag_match_score",
                             "site_photos_uploaded")
        increases_risk = (z < 0) if higher_safer else (z > 0)
        out.append({
            "feature": c, "label": label, "hint": hint,
            "direction": "increases_risk" if increases_risk else "decreases_risk",
            "z_score": round(float(z), 2), "feature_value": v,
            "dataset_median": round(float(med.get(c, v)), 3),
        })
    out.sort(key=lambda d: abs(d["z_score"]), reverse=True)
    method = ("Statistical deviation ranking (robust z-scores vs this dataset) — "
              "less rigorous than SHAP on a trained surrogate; shown because the "
              "dataset is too small to train a trustworthy surrogate")
    return out[:k], method
