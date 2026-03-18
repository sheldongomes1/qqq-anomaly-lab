from __future__ import annotations

import pandas as pd
from sklearn.ensemble import IsolationForest


class IsolationForestDetector:
    """Small wrapper around sklearn IsolationForest for tabular data."""

    def __init__(self, contamination: float = 0.05, random_state: int = 42) -> None:
        self.model = IsolationForest(
            contamination=contamination,
            random_state=random_state,
            n_estimators=200,
        )
        self.feature_columns: list[str] = []

    def fit(self, df: pd.DataFrame) -> "IsolationForestDetector":
        numeric_df = df.select_dtypes(include=["number"]).dropna()
        if numeric_df.empty:
            raise ValueError("No numeric rows available for fitting.")
        self.feature_columns = numeric_df.columns.tolist()
        self.model.fit(numeric_df)
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        if not self.feature_columns:
            raise ValueError("Model is not fit yet. Call fit() first.")
        feature_frame = df[self.feature_columns].copy()
        labels = self.model.predict(feature_frame)  # -1 anomaly, 1 normal
        scores = self.model.decision_function(feature_frame)
        scored = feature_frame.copy()
        scored["anomaly_label"] = labels
        scored["anomaly_score"] = scores
        return scored
