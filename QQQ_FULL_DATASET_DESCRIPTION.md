# qqq_full Folder Description (Project Handoff)

The `qqq_full` folder is a precomputed SEC filings dataset for the Nasdaq-100 universe (QQQ scope), generated for anomaly detection use cases.

## Root path

`data/processed/qqq_full`

## What this folder contains

1. One subfolder per ticker (e.g., `AAPL`, `MSFT`, `GOOG`)
2. One summary file:
   - `qqq_precompute_summary.json`

## Dataset scope and run settings

From `qqq_precompute_summary.json`:

- `start_year`: `2021`
- `end_year`: `2025`
- `include_quarterly`: `true` (10-Q included)
- `include_html`: `false` (raw filing HTML/text is not embedded in these bulk files)
- `ticker_count`: `101` (Nasdaq-100 constituent snapshot used at generation time)

Each ticker entry in summary includes:

- `ticker`
- `cik`
- `company_name`
- `files_generated` (number of JSON output files for that ticker)

## Per-ticker files

Inside each ticker folder, files follow this naming pattern:

- Annual:
  - `<TICKER>_<YEAR>_10K_analysis_ready.json`
- Quarterly:
  - `<TICKER>_<YEAR>_10Q_<N>_<REPORT_DATE>_analysis_ready.json`

Example:

- `AAPL_2025_10K_analysis_ready.json`
- `AAPL_2025_10Q_1_2025-12-27_analysis_ready.json`

For mature US issuers, expected max is around 20 files across 2021-2025:

- 5 x 10-K
- up to 15 x 10-Q

## JSON schema (per file)

Each `*_analysis_ready.json` in `qqq_full` includes core structured fields:

- `extraction_input`
  - (`ticker`, `year`)
- `selected_filing`
  - (form, accession number, filing/report dates, etc.)
- `selected_filing_url`
  - (SEC filing URL)
- `companyfacts_feature_history`
  - (long historical standardized financial features from SEC companyfacts)
- `engineered_anomaly_features`
  - (precomputed ratios and growth metrics such as debt/assets, net margin, YoY growth, accrual ratio)

Because `include_html=false` in this bulk run, these files do not include large raw text/iXBRL parsing blocks (`filing_text_clean`, `ixbrl_feature_history`, etc.).

## Important edge cases

Some tickers can have `files_generated = 0` in this pipeline if they do not file standard US 10-K/10-Q forms in the expected structure (common for certain foreign issuers/filing regimes).

Examples observed:

- `ARM`
- `ASML`
- `CCEP`
- `FER`
- `PDD`
- `TRI`

## Intended use in app architecture

Use `qqq_full` as a precomputed feature store:

- no live SEC fetch needed at user request time
- fast query/scoring in web app
- periodic offline refresh

Recommended ingestion target:

- Cloud Storage for raw JSON
- BigQuery flattened tables for API queries and ranking/anomaly scoring
