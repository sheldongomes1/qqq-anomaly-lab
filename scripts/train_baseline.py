from __future__ import annotations

import numpy as np
import pandas as pd

from tenk_anomaly import IsolationForestDetector


def build_sample_data(n_rows: int = 1000, random_state: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(random_state)
    normal = rng.normal(loc=0, scale=1, size=(n_rows - 20, 3))
    anomalies = rng.normal(loc=8, scale=0.8, size=(20, 3))
    data = np.vstack([normal, anomalies])
    df = pd.DataFrame(data, columns=["feature_a", "feature_b", "feature_c"])
    return df.sample(frac=1.0, random_state=random_state).reset_index(drop=True)


def main() -> None:
    df = build_sample_data()
    detector = IsolationForestDetector(contamination=0.02).fit(df)
    scored = detector.predict(df)
    anomaly_count = int((scored["anomaly_label"] == -1).sum())
    print(f"rows={len(scored)} anomalies={anomaly_count}")


if __name__ == "__main__":
    main()
