"""Load analysis_ready.json files into BigQuery.

Reads all *_analysis_ready.json files from the local processed directory
and upserts them into BigQuery as a flat `filings` table — one row per
filing with all engineered features as columns.

Usage:
    python3 scripts/ingest_to_bigquery.py \\
        [--input-dir data/processed/qqq] \\
        [--project qqq-anomaly-lab] \\
        [--dataset qqq_anomaly] \\
        [--table filings] \\
        [--tickers AAPL,MSFT]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.scoring_exclusions import SCORING_EXCLUSIONS

from google.cloud import bigquery

# ---------------------------------------------------------------------------
# Schema — explicit so BQ types are predictable.
# All feature columns are FLOAT (nullable) so rows with partial data load.
# ---------------------------------------------------------------------------

_SCHEMA = [
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("company_name", "STRING"),
    bigquery.SchemaField("cik", "STRING"),
    bigquery.SchemaField("form", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("year", "INTEGER", mode="REQUIRED"),
    bigquery.SchemaField("accession_number", "STRING"),
    bigquery.SchemaField("filing_date", "DATE"),
    bigquery.SchemaField("report_date", "DATE"),
    bigquery.SchemaField("filing_url", "STRING"),
    bigquery.SchemaField("feature_count", "INTEGER"),
    # Engineered features — nullable because not every filing has all features
    bigquery.SchemaField("debt_to_assets", "FLOAT"),
    bigquery.SchemaField("equity_to_assets", "FLOAT"),
    bigquery.SchemaField("net_margin", "FLOAT"),
    bigquery.SchemaField("ocf_to_net_income", "FLOAT"),
    bigquery.SchemaField("ocf_to_assets", "FLOAT"),
    bigquery.SchemaField("accrual_ratio", "FLOAT"),
    bigquery.SchemaField("equity_multiplier", "FLOAT"),
    bigquery.SchemaField("revenue_growth_yoy", "FLOAT"),
    bigquery.SchemaField("assets_growth_yoy", "FLOAT"),
    bigquery.SchemaField("net_income_growth_yoy", "FLOAT"),
    # Beneish M-Score raw inputs — current period (b_curr_*) and prior year
    # same period (b_prior_*). Raw USD values, not ratios. Null when not reported.
    bigquery.SchemaField("b_curr_accounts_receivable", "FLOAT"),
    bigquery.SchemaField("b_curr_revenue", "FLOAT"),
    bigquery.SchemaField("b_curr_cost_of_revenue", "FLOAT"),
    bigquery.SchemaField("b_curr_current_assets", "FLOAT"),
    bigquery.SchemaField("b_curr_ppe_net", "FLOAT"),
    bigquery.SchemaField("b_curr_total_assets", "FLOAT"),
    bigquery.SchemaField("b_curr_depreciation_amortization", "FLOAT"),
    bigquery.SchemaField("b_curr_sga_expense", "FLOAT"),
    bigquery.SchemaField("b_curr_long_term_debt", "FLOAT"),
    bigquery.SchemaField("b_curr_current_liabilities", "FLOAT"),
    bigquery.SchemaField("b_curr_net_income", "FLOAT"),
    bigquery.SchemaField("b_curr_operating_cash_flow", "FLOAT"),
    bigquery.SchemaField("b_prior_accounts_receivable", "FLOAT"),
    bigquery.SchemaField("b_prior_revenue", "FLOAT"),
    bigquery.SchemaField("b_prior_cost_of_revenue", "FLOAT"),
    bigquery.SchemaField("b_prior_current_assets", "FLOAT"),
    bigquery.SchemaField("b_prior_ppe_net", "FLOAT"),
    bigquery.SchemaField("b_prior_total_assets", "FLOAT"),
    bigquery.SchemaField("b_prior_depreciation_amortization", "FLOAT"),
    bigquery.SchemaField("b_prior_sga_expense", "FLOAT"),
    bigquery.SchemaField("b_prior_long_term_debt", "FLOAT"),
    bigquery.SchemaField("b_prior_current_liabilities", "FLOAT"),
    bigquery.SchemaField("b_prior_net_income", "FLOAT"),
    bigquery.SchemaField("b_prior_operating_cash_flow", "FLOAT"),
]

_FEATURE_COLS = [
    "debt_to_assets",
    "equity_to_assets",
    "net_margin",
    "ocf_to_net_income",
    "ocf_to_assets",
    "accrual_ratio",
    "equity_multiplier",
    "revenue_growth_yoy",
    "assets_growth_yoy",
    "net_income_growth_yoy",
]

_BENEISH_FIELDS = [
    "accounts_receivable",
    "revenue",
    "cost_of_revenue",
    "current_assets",
    "ppe_net",
    "total_assets",
    "depreciation_amortization",
    "sga_expense",
    "long_term_debt",
    "current_liabilities",
    "net_income",
    "operating_cash_flow",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load analysis_ready files into BigQuery.")
    p.add_argument("--input-dir", default="data/processed/qqq")
    p.add_argument("--project", default="qqq-anomaly-lab")
    p.add_argument("--dataset", default="qqq_anomaly")
    p.add_argument("--table", default="filings")
    p.add_argument("--tickers", default="", help="Comma-separated subset; default: all.")
    return p.parse_args()


def _build_row(payload: dict) -> dict | None:
    """Flatten one analysis_ready payload into a BQ row dict."""
    sf = payload.get("selected_filing", {})
    eng = payload.get("engineered_anomaly_features", {})

    ticker = (
        payload.get("extraction_input", {}).get("ticker")
        or sf.get("ticker")
    )
    form = eng.get("target_form") or sf.get("form")
    year = eng.get("target_year") or payload.get("extraction_input", {}).get("year")

    if not ticker or not form or year is None:
        return None

    row: dict = {
        "ticker": str(ticker).upper(),
        "company_name": sf.get("company_name"),
        "cik": sf.get("cik"),
        "form": str(form),
        "year": int(year),
        "accession_number": sf.get("accession_number"),
        "filing_date": sf.get("filing_date") or None,
        "report_date": eng.get("target_period_end") or sf.get("report_date") or None,
        "filing_url": payload.get("selected_filing_url"),
        "feature_count": eng.get("feature_count"),
    }
    for col in _FEATURE_COLS:
        val = eng.get(col)
        row[col] = float(val) if val is not None else None

    # Flatten Beneish raw inputs from beneish_raw_features.current / .prior_year_same_period
    beneish = payload.get("beneish_raw_features", {})
    curr = beneish.get("current", {})
    prior = beneish.get("prior_year_same_period", {})
    for field in _BENEISH_FIELDS:
        c_val = curr.get(field)
        p_val = prior.get(field)
        row[f"b_curr_{field}"] = float(c_val) if c_val is not None else None
        row[f"b_prior_{field}"] = float(p_val) if p_val is not None else None

    return row


def main() -> None:
    args = _parse_args()
    client = bigquery.Client(project=args.project)
    dataset_ref = bigquery.DatasetReference(args.project, args.dataset)
    table_ref = dataset_ref.table(args.table)

    # Create dataset if needed (location matches GCS bucket: US)
    try:
        client.get_dataset(dataset_ref)
        print(f"dataset exists: {args.dataset}")
    except Exception:
        ds = bigquery.Dataset(dataset_ref)
        ds.location = "US"
        client.create_dataset(ds)
        print(f"dataset created: {args.dataset}")

    # Create or replace table with explicit schema
    table = bigquery.Table(table_ref, schema=_SCHEMA)
    table = client.create_table(table, exists_ok=True)
    print(f"table ready: {args.project}.{args.dataset}.{args.table}")

    # Resolve tickers
    input_root = Path(args.input_dir)
    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = sorted(p.name for p in input_root.iterdir() if p.is_dir())

    # Log scoring exclusions
    if SCORING_EXCLUSIONS:
        print(f"scoring_exclusions={list(SCORING_EXCLUSIONS.keys())}")
        for t, reason in SCORING_EXCLUSIONS.items():
            print(f"  excluded {t}: {reason[:80]}...")

    # Build rows
    rows: list[dict] = []
    skipped = 0
    excluded = 0
    for ticker in tickers:
        if ticker in SCORING_EXCLUSIONS:
            excluded += 1
            continue
        for f in sorted((input_root / ticker).glob("*.json")):
            payload = json.loads(f.read_text(encoding="utf-8"))
            row = _build_row(payload)
            if row is None:
                skipped += 1
                continue
            rows.append(row)

    print(f"rows_built={len(rows)} skipped={skipped} excluded_tickers={excluded}")

    if not rows:
        print("Nothing to load.")
        return

    # Load — truncate and reload for simplicity (idempotent full refresh)
    job_config = bigquery.LoadJobConfig(
        schema=_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    job = client.load_table_from_json(rows, table_ref, job_config=job_config)
    job.result()  # wait for completion

    loaded = client.get_table(table_ref).num_rows
    print(f"done rows_in_table={loaded}")


if __name__ == "__main__":
    main()
