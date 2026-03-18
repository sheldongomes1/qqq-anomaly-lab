# 10k-anomaly

A fresh, standalone project for anomaly detection workflows.

## What is included

- Python package layout under `src/tenk_anomaly`
- Baseline anomaly detector using Isolation Forest
- EDGAR API client for SEC data and filing APIs
- Script entrypoint for quick local runs
- Basic tests
- Common data-science directories (`data`, `notebooks`, `models`, `reports`)

## Quick start

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -e ".[dev]"
```

3. Run tests:

```bash
pytest
```

4. Run baseline script:

```bash
python scripts/train_baseline.py
```

5. Check EDGAR API connectivity:

```bash
export SEC_API_EMAIL="you@example.com"
export SEC_APP_NAME="10k-anomaly"
python scripts/check_edgar_connection.py
```

6. Ingest 10-K filing rows + features to CSV:

```bash
export SEC_API_EMAIL="you@example.com"
python scripts/sec_ingest.py --ciks "320193,789019,1652044"
```

7. Extract a specific company/year 10-K by ticker:

```bash
export SEC_API_EMAIL="you@example.com"
python scripts/extract_10k_by_ticker_year.py --ticker GOOG --year 2025
```

8. Precompute QQQ universe JSON bundles:

```bash
export SEC_API_EMAIL="you@example.com"
python scripts/precompute_qqq_universe.py --start-year 2021 --end-year 2025 --include-quarterly
```

Fast verification run (first 5 tickers):

```bash
python scripts/precompute_qqq_universe.py --start-year 2025 --end-year 2025 --include-quarterly --max-tickers 5
```

Refresh Nasdaq-100 universe cache explicitly:

```bash
python scripts/precompute_qqq_universe.py --start-year 2025 --end-year 2025 --max-tickers 5 --refresh-universe
```

Manual ticker override (bypass universe auto-fetch):

```bash
python scripts/precompute_qqq_universe.py --start-year 2025 --end-year 2025 --include-quarterly --tickers "AAPL,MSFT,GOOG"
```

## EDGAR client usage

```python
from tenk_anomaly import EdgarAuth, EdgarClient

client = EdgarClient(
    email="you@example.com",
    app_name="10k-anomaly",
    auth=EdgarAuth(
        filer_api_token="optional-filer-token",
        user_api_token="optional-user-token",
    ),
)

submissions = client.get_submissions("320193")
facts = client.get_company_facts("320193")
```

For filing APIs:

```python
result = client.filing_request(
    method="POST",
    path="/submissions",
    json_body={"example": "payload"},
    require_user_token=True,
)
```

## SEC ingest outputs

The ingest script writes:

- `data/processed/tenk_recent_filings.csv`
- `data/processed/tenk_features.csv`

These are ready for feature QA and downstream anomaly detection workflows.

Ticker/year extraction writes:

- `data/processed/GOOG_2025_10k_metadata.json`
- `data/processed/GOOG_2025_10k_filing.html`
- `data/processed/GOOG_2025_10k_candidate_filings.csv`
- `data/processed/GOOG_2025_10k_analysis_ready.json`

The analysis-ready JSON now includes robust anomaly inputs:

- `companyfacts_feature_history` (multi-year standardized SEC facts)
- `ixbrl_feature_history` (facts parsed directly from the filing HTML/iXBRL)
- `combined_feature_history` (merged history with source-aware priority)
- `engineered_anomaly_features` (ratios and year-over-year growth metrics)

QQQ precompute outputs are written under:

- `data/processed/qqq/<TICKER>/*.json`
- `data/processed/qqq/qqq_precompute_summary.json`

By default the bulk run skips raw filing HTML fetch for speed and smaller output sizes.
Use `--include-html` if you want full filing text and iXBRL-parsed fields for every file.

## Project structure

```text
10k-anomaly/
  data/
    raw/
    processed/
  models/
  notebooks/
  reports/
  scripts/
  src/
    tenk_anomaly/
  tests/
```

## Next steps

- Plug in your real dataset in `data/raw`
- Add feature engineering modules
- Add experiment tracking (MLflow/W&B) if needed
- Add CI for tests and linting
