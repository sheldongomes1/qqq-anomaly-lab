from __future__ import annotations

import argparse
import os
from pathlib import Path

from tenk_anomaly import EdgarClient
from tenk_anomaly.sec_ingest import ingest_companies, write_ingest_outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch SEC EDGAR 10-K filings and company facts into CSV outputs."
    )
    parser.add_argument(
        "--ciks",
        required=True,
        help="Comma-separated CIKs, e.g. 320193,789019,1652044",
    )
    parser.add_argument(
        "--max-filings",
        type=int,
        default=8,
        help="Maximum recent 10-K rows per company in filings output.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed",
        help="Directory for output CSV files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    email = os.getenv("SEC_API_EMAIL")
    app_name = os.getenv("SEC_APP_NAME", "10k-anomaly")
    if not email:
        raise RuntimeError("Set SEC_API_EMAIL before running SEC ingest.")

    ciks = [item.strip() for item in args.ciks.split(",") if item.strip()]
    if not ciks:
        raise RuntimeError("No CIKs provided. Pass --ciks with at least one CIK.")

    client = EdgarClient(email=email, app_name=app_name)
    filings_df, features_df = ingest_companies(
        client=client,
        ciks=ciks,
        max_10k_filings_per_company=args.max_filings,
    )
    filings_path, features_path = write_ingest_outputs(
        filings_df=filings_df,
        features_df=features_df,
        output_dir=Path(args.output_dir),
    )

    print(f"filings_rows={len(filings_df)} path={filings_path}")
    print(f"features_rows={len(features_df)} path={features_path}")


if __name__ == "__main__":
    main()
