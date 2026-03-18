import pandas as pd

from tenk_anomaly import IsolationForestDetector


def test_detector_predicts_expected_columns() -> None:
    df = pd.DataFrame(
        {
            "x": [0.0, 0.1, 0.2, 10.0],
            "y": [0.0, -0.1, 0.2, 9.5],
        }
    )
    detector = IsolationForestDetector(contamination=0.25, random_state=7).fit(df)
    scored = detector.predict(df)

    assert "anomaly_label" in scored.columns
    assert "anomaly_score" in scored.columns
    assert set(scored["anomaly_label"].unique()).issubset({-1, 1})
