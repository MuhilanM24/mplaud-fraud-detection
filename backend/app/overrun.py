"""Cost-overrun prediction: regression on expected final cost vs sanctioned.

A GradientBoosting regressor predicts the final-cost/sanctioned-amount ratio
from features available while the project is still running (size, work type,
agency history, current cost-per-unit signal, pace). Projects whose predicted
ratio exceeds OVERRUN_FLAG_RATIO are flagged as trending over budget EARLY —
before the money is spent.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split

from . import config


class OverrunModel:
    def __init__(self):
        self.model = GradientBoostingRegressor(random_state=42,
                                               n_estimators=300, max_depth=2,
                                               min_samples_leaf=12,
                                               subsample=0.8,
                                               learning_rate=0.05)
        self.r2: float | None = None
        self.mae: float | None = None
        self.trained = False
        self.features: list[str] = []

    def fit(self, df: pd.DataFrame) -> "OverrunModel":
        amt = pd.to_numeric(df.get("sanctioned_amount"), errors="coerce")
        final = pd.to_numeric(df.get("final_cost"), errors="coerce")
        y = (final / amt).replace([np.inf, -np.inf], np.nan).dropna()
        if len(y) < 30:
            return self
        idx = y.index
        X = self._design(df.loc[idx])
        self.features = list(X.columns)
        y = y.loc[idx].values
        Xtr, Xte, ytr, yte = train_test_split(X.values, y, test_size=0.25,
                                              random_state=42)
        self.model.fit(Xtr, ytr)
        pred = self.model.predict(Xte)
        ss = ((yte - yte.mean()) ** 2).sum() or 1e-9
        self.r2 = float(1 - ((yte - pred) ** 2).sum() / ss)
        self.mae = float(np.abs(yte - pred).mean())
        self.trained = True
        return self

    def _design(self, df: pd.DataFrame) -> pd.DataFrame:
        parts = [pd.DataFrame(index=df.index)]
        for col in ("sanctioned_amount", "cost_per_unit_ratio",
                    "agency_prior_flagged_count", "days_sanction_to_payment",
                    "completion_pct_at_payment", "expected_duration_days"):
            if col in df.columns:
                parts.append(pd.to_numeric(df[col], errors="coerce")
                             .rename(col).fillna(0))
        if "work_type" in df.columns:
            parts.append(pd.get_dummies(df["work_type"].fillna("?"),
                                        prefix="wt").astype(float))
        if "agency" in df.columns:
            parts.append(pd.get_dummies(df["agency"].fillna("?"),
                                        prefix="ag").astype(float))
        if "actual_delay_days" in df.columns:
            # pace signal known mid-project: delay so far vs expected duration
            d = pd.to_numeric(df["actual_delay_days"], errors="coerce").fillna(0)
            e = pd.to_numeric(df.get("expected_duration_days", 0), errors="coerce").fillna(1)
            parts.append((d / e.replace(0, 1)).rename("pace_ratio"))
        return pd.concat(parts, axis=1)

    def predict(self, project: pd.Series, sanctioned_amount: float) -> dict | None:
        if not self.trained or not sanctioned_amount:
            return None
        X = self._design(project.to_frame().T)
        X = X.reindex(columns=self.features, fill_value=0.0)
        ratio = float(self.model.predict(X.values)[0])
        predicted_final = sanctioned_amount * ratio
        flag = ratio >= config.OVERRUN_FLAG_RATIO
        return {
            "predicted_final_to_sanctioned_ratio": round(ratio, 3),
            "sanctioned_amount": sanctioned_amount,
            "predicted_final_cost": round(predicted_final, 0),
            "predicted_overrun_amount": round(predicted_final - sanctioned_amount, 0),
            "trending_over_budget": flag,
            "model_r2": None if self.r2 is None else round(self.r2, 3),
            "model_mae": None if self.mae is None else round(self.mae, 3),
            "plain_language": (
                f"Model expects the final cost to reach about "
                f"{ratio:.2f}x the sanctioned amount "
                f"(Rs {predicted_final/1e5:.1f} lakh vs Rs "
                f"{sanctioned_amount/1e5:.1f} lakh sanctioned)"
                + (" — trending over budget." if flag else
                   " — within expected range.")),
        }
