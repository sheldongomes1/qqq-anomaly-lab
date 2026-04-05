from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tenk_anomaly import EdgarClient, precompute_universe_filings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Precompute QQQ annual/quarterly SEC filing JSON bundles for a year range."
    )
    parser.add_argument("--start-year", type=int, required=True, help="Start year, e.g. 2021")
    parser.add_argument("--end-year", type=int, required=True, help="End year, e.g. 2025")
    parser.add_argument(
        "--output-dir",
        default="data/processed/qqq",
        help="Output directory for per-company JSON files.",
    )
    parser.add_argument(
        "--include-quarterly",
        action="store_true",
        help="Include 10-Q filings in addition to 10-K.",
    )
    parser.add_argument(
        "--include-html",
        action="store_true",
        help="Fetch and parse filing HTML/iXBRL for each file (slower, larger outputs).",
    )
    parser.add_argument(
        "--max-tickers",
        type=int,
        default=0,
        help="Limit tickers for test runs (0 means all constituents).",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Optional comma-separated ticker override; skips Nasdaq-100 auto-fetch.",
    )
    parser.add_argument(
        "--universe-cache",
        default="data/raw/qqq_tickers_latest.json",
        help="Cache file path for Nasdaq-100 ticker list.",
    )
    parser.add_argument(
        "--refresh-universe",
        action="store_true",
        help="Force refresh Nasdaq-100 constituents from Nasdaq API.",
    )
    parser.add_argument(
        "--gcs-bucket",
        default="",
        help="GCS bucket to upload outputs to (e.g. qqq-anomaly-raw-sg). Omit to skip GCS upload.",
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
    app_name = os.getenv("SEC_APP_NAME", "10k-anomaly")
    if not email:
        raise RuntimeError("Set SEC_API_EMAIL before running QQQ precompute.")

    client = EdgarClient(email=email, app_name=app_name)

    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        cache_path = Path(args.universe_cache)
        if cache_path.exists() and not args.refresh_universe:
            rows = json.loads(cache_path.read_text(encoding="utf-8"))
            tickers = sorted({str(row.get("ticker", "")).upper() for row in rows if row.get("ticker")})
            print(f"universe_source=cache path={cache_path}")
        else:
            try:
                rows = client.get_nasdaq_100_constituents()
                tickers = sorted({str(row.get("ticker", "")).upper() for row in rows if row.get("ticker")})
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
                print(f"universe_source=nasdaq_api cache_written={cache_path}")
            except Exception as exc:
                if cache_path.exists():
                    rows = json.loads(cache_path.read_text(encoding="utf-8"))
                    tickers = sorted({str(row.get("ticker", "")).upper() for row in rows if row.get("ticker")})
                    print(f"universe_source=cache path={cache_path} reason={type(exc).__name__}")
                else:
                    raise RuntimeError(
                        "Unable to fetch Nasdaq-100 constituents and no cache available. "
                        "Pass --tickers or rerun when network is healthy."
                    ) from exc

    if args.max_tickers > 0:
        tickers = tickers[: args.max_tickers]
    if not tickers:
        raise RuntimeError("No tickers available for precompute.")

    summary = precompute_universe_filings(
        client=client,
        tickers=tickers,
        start_year=args.start_year,
        end_year=args.end_year,
        include_quarterly=args.include_quarterly,
        include_html=args.include_html,
        output_dir=Path(args.output_dir),
        gcs_bucket=args.gcs_bucket or None,
        gcs_prefix=args.gcs_prefix,
    )

    print(f"ticker_count={summary['ticker_count']}")
    print(f"include_quarterly={summary['include_quarterly']}")
    print(f"include_html={summary['include_html']}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
