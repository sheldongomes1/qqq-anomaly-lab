"""Re-compute engineered features and companyfacts history for existing analysis_ready files.

This script patches stored analysis_ready.json files WITHOUT re-fetching filing HTML.
It only hits the EDGAR company-facts API (lightweight JSON), making it much faster than
a full pipeline re-run.

Use this after updating DEFAULT_FEATURE_TAGS (e.g. adding new XBRL concept fallbacks).

Usage:
    SEC_API_EMAIL=sheldon.gomes@gmail.com python3 scripts/recompute_features.py \\
        --input-dir data/processed/qqq \\
        [--tickers AAPL,MSFT] \\
        [--gcs-bucket qqq-anomaly-raw-sg --gcs-prefix qqq]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from tenk_anomaly import EdgarClient
from tenk_anomaly.sec_ingest import (
    build_engineered_anomaly_features,
    combine_feature_histories,
    extract_companyfacts_feature_history,
    ticker_to_cik,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Re-compute features from company-facts API.")
    parser.add_argument("--input-dir", default="data/processed/qqq")
    parser.add_argument("--tickers", default="", help="Comma-separated subset; default: all.")
    parser.add_argument("--gcs-bucket", default="")
    parser.add_argument("--gcs-prefix", default="qqq")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    email = os.getenv("SEC_API_EMAIL")
    if not email:
        raise RuntimeError("Set SEC_API_EMAIL before running.")

    client = EdgarClient(email=email)
    input_root = Path(args.input_dir)

    gcs_client = None
    if args.gcs_bucket:
        from google.cloud import storage as gcs_mod  # type: ignore[import]
        gcs_client = gcs_mod.Client()
        print(f"gcs_enabled bucket={args.gcs_bucket} prefix={args.gcs_prefix}")

    company_tickers = client.get_company_tickers()

    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = sorted(p.name for p in input_root.iterdir() if p.is_dir())

    total_updated = total_skipped = 0

    for ticker in tickers:
        ticker_dir = input_root / ticker
        if not ticker_dir.exists():
            print(f"skip ticker={ticker} reason=no_dir")
            continue

        try:
            cik = ticker_to_cik(company_tickers, ticker)
            company_facts = client.get_company_facts(cik)
        except Exception as exc:
            print(f"skip ticker={ticker} reason=api_error err={exc}")
            continue

        companyfacts_history = extract_companyfacts_feature_history(
            company_facts=company_facts
        )

        files = sorted(ticker_dir.glob("*.json"))
        updated = 0
        for f in files:
            payload = json.loads(f.read_text(encoding="utf-8"))
            eng_input = payload.get("extraction_input", {})
            eng_features = payload.get("engineered_anomaly_features", {})
            target_year = (
                eng_input.get("target_year")
                or eng_features.get("target_year")
                or eng_input.get("year")
            )
            target_period_end = eng_features.get("target_period_end")
            target_form = eng_features.get("target_form") or eng_input.get("form")
            if target_year is None:
                total_skipped += 1
                continue

            # Use companyfacts only (no iXBRL re-fetch)
            import pandas as pd
            feature_history = combine_feature_histories(
                companyfacts_history=companyfacts_history,
                ixbrl_history=pd.DataFrame(),
                target_year=int(target_year),
            )

            engineered = build_engineered_anomaly_features(
                feature_history=feature_history,
                target_year=int(target_year),
                target_period_end=target_period_end,
                target_form=target_form,
            )

            # Patch the stored file
            payload["companyfacts_feature_history"] = json.loads(
                companyfacts_history.to_json(orient="records")
            )
            payload["engineered_anomaly_features"] = engineered

            out_json = json.dumps(payload, indent=2)
            f.write_text(out_json, encoding="utf-8")

            if gcs_client:
                blob = f"{args.gcs_prefix}/{ticker}/{f.name}"
                gcs_client.bucket(args.gcs_bucket).blob(blob).upload_from_string(
                    out_json, content_type="application/json"
                )
            updated += 1

        total_updated += updated
        print(f"ticker={ticker} updated={updated}")

    print(f"\ndone total_updated={total_updated} total_skipped={total_skipped}")
    if gcs_client:
        print(f"uploaded to gs://{args.gcs_bucket}/{args.gcs_prefix}/")


if __name__ == "__main__":
    main()
