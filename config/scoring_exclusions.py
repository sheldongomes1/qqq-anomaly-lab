"""
Scoring pipeline exclusion list.

Tickers listed here are still processed by the ingestion pipeline (GCS files
exist and features are computed), but they are excluded from the final BigQuery
filings table that feeds the scoring pipeline.

Use this for companies whose financial structure makes their metrics
analytically incompatible with the rest of the QQQ universe — not for
data quality issues (those are handled upstream with nulls and flags).

Format: { "TICKER": "reason for exclusion" }
"""

SCORING_EXCLUSIONS: dict[str, str] = {
    "MSTR": (
        "Bitcoin holding company. Balance sheet dominated by BTC holdings (~$40B+), "
        "not operating assets. Metrics like debt_to_assets, equity_multiplier, and "
        "accrual_ratio reflect crypto treasury strategy, not business operations. "
        "Distorts cohort-wide z-score distributions and Mahalanobis covariance."
    ),
}
