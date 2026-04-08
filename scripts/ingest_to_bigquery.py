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
from pathlib import Path

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
    # Engineered features — nullable because not every filing has all 7
    bigquery.SchemaField("debt_to_assets", "FLOAT"),
    bigquery.SchemaField("equity_to_assets", "FLOAT"),
    bigquery.SchemaField("net_margin", "FLOAT"),
    bigquery.SchemaField("ocf_to_net_income", "FLOAT"),
    bigquery.SchemaField("accrual_ratio", "FLOAT"),
    bigquery.SchemaField("revenue_growth_yoy", "FLOAT"),
    bigquery.SchemaField("assets_growth_yoy", "FLOAT"),
    bigquery.SchemaField("net_income_growth_yoy", "FLOAT"),
]

_FEATURE_COLS = [
    "debt_to_assets",
    "equity_to_assets",
    "net_margin",
    "ocf_to_net_income",
    "accrual_ratio",
    "revenue_growth_yoy",
    "assets_growth_yoy",
    "net_income_growth_yoy",
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

    # Build rows
    rows: list[dict] = []
    skipped = 0
    for ticker in tickers:
        for f in sorted((input_root / ticker).glob("*.json")):
            payload = json.loads(f.read_text(encoding="utf-8"))
            row = _build_row(payload)
            if row is None:
                skipped += 1
                continue
            rows.append(row)

    print(f"rows_built={len(rows)} skipped={skipped}")

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
