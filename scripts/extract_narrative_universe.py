from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tenk_anomaly import EdgarClient
from tenk_anomaly.narrative import extract_narrative_universe_filings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract narrative sections (MD&A, risk factors, business) from QQQ filings."
    )
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument(
        "--output-dir",
        default="data/processed/qqq_narrative",
        help="Local output directory for narrative JSON files.",
    )
    parser.add_argument(
        "--include-quarterly",
        action="store_true",
        help="Include 10-Q filings in addition to 10-K.",
    )
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=0,
        help="Limit tickers for test runs (0 = all).",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated ticker override; skips Nasdaq-100 auto-fetch.",
    )
    parser.add_argument(
        "--universe-cache",
        default="data/raw/qqq_tickers_latest.json",
        help="Cache file path for Nasdaq-100 ticker list.",
    )
    parser.add_argument(
        "--gcs-bucket",
        default="",
        help="GCS bucket to upload narrative files (e.g. qqq-anomaly-raw-sg).",
    )
    parser.add_argument(
        "--gcs-prefix",
        default="qqq",
        help="GCS object path prefix (default: qqq).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    email = os.getenv("SEC_API_EMAIL")
    if not email:
        raise RuntimeError("Set SEC_API_EMAIL before running narrative extraction.")

    client = EdgarClient(email=email, app_name=os.getenv("SEC_APP_NAME", "10k-anomaly"))

    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        cache_path = Path(args.universe_cache)
        if not cache_path.exists():
            raise RuntimeError(
                f"Ticker cache not found at {cache_path}. "
                "Run precompute_qqq_universe.py first or pass --tickers."
            )
        rows = json.loads(cache_path.read_text(encoding="utf-8"))
        tickers = sorted({str(row.get("ticker", "")).upper() for row in rows if row.get("ticker")})

    if args.max_tickers > 0:
        tickers = tickers[: args.max_tickers]
    if not tickers:
        raise RuntimeError("No tickers available.")

    summary = extract_narrative_universe_filings(
        client=client,
        tickers=tickers,
        start_year=args.start_year,
        end_year=args.end_year,
        include_quarterly=args.include_quarterly,
        output_dir=Path(args.output_dir),
        gcs_bucket=args.gcs_bucket or None,
        gcs_prefix=args.gcs_prefix,
    )

    print(f"ticker_count={summary['ticker_count']}")
    print(f"include_quarterly={summary['include_quarterly']}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
