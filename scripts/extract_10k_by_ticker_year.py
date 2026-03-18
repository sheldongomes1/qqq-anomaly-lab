from __future__ import annotations

import argparse
import os
from pathlib import Path

from tenk_anomaly import EdgarClient, extract_10k_filing_by_ticker_year


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract one 10-K filing by ticker and year, then save to data/processed."
    )
    parser.add_argument("--ticker", required=True, help="Company ticker symbol, e.g. GOOG")
    parser.add_argument("--year", required=True, type=int, help="Target year, e.g. 2025")
    parser.add_argument("--output-dir", default="data/processed", help="Output directory path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    email = os.getenv("SEC_API_EMAIL")
    app_name = os.getenv("SEC_APP_NAME", "10k-anomaly")
    if not email:
        raise RuntimeError("Set SEC_API_EMAIL before running extraction.")

    client = EdgarClient(email=email, app_name=app_name)
    result_paths = extract_10k_filing_by_ticker_year(
        client=client,
        ticker=args.ticker,
        year=args.year,
        output_dir=Path(args.output_dir),
    )

    for name, path in result_paths.items():
        print(f"{name}={path}")


if __name__ == "__main__":
    main()
