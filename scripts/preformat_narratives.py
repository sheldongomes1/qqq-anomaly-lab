"""Pre-format all *_narrative.json files into *_narrative_ready.json.

Reads from data/processed/qqq_narrative/{TICKER}/, writes to
data/processed/qqq_narrative_ready/{TICKER}/ (and optionally GCS).

Idempotent — safe to re-run, overwrites existing ready files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tenk_anomaly.narrative_preformat import preformat_narrative


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-format narrative JSON files into analysis-ready format."
    )
    parser.add_argument(
        "--input-dir",
        default="data/processed/qqq_narrative",
        help="Root directory containing per-ticker narrative JSON files.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed/qqq_narrative_ready",
        help="Root directory for output narrative_ready JSON files.",
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated ticker subset, e.g. AAPL,MSFT. Default: all.",
    )
    parser.add_argument(
        "--gcs-bucket",
        default="",
        help="GCS bucket to upload outputs (e.g. qqq-anomaly-raw-sg).",
    )
    parser.add_argument(
        "--gcs-prefix",
        default="qqq",
        help="GCS path prefix (default: qqq). Output path: {prefix}/narrative_ready/{ticker}/{file}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_root = Path(args.input_dir)
    output_root = Path(args.output_dir)

    if not input_root.exists():
        raise RuntimeError(f"Input directory not found: {input_root}")

    # GCS setup
    gcs_client = None
    if args.gcs_bucket:
        try:
            from google.cloud import storage as gcs_mod  # type: ignore[import]
            gcs_client = gcs_mod.Client()
            print(f"gcs_enabled bucket={args.gcs_bucket} prefix={args.gcs_prefix}/narrative_ready")
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-storage required. Run: pip install google-cloud-storage"
            ) from exc

    # Resolve tickers
    if args.tickers.strip():
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = sorted(p.name for p in input_root.iterdir() if p.is_dir())

    total_files = total_deferred = total_flagged = total_missing = 0

    for ticker in tickers:
        ticker_in_dir = input_root / ticker
        if not ticker_in_dir.exists():
            print(f"skip ticker={ticker} reason=no_input_dir")
            continue

        ticker_out_dir = output_root / ticker
        ticker_out_dir.mkdir(parents=True, exist_ok=True)

        narrative_files = sorted(ticker_in_dir.glob("*_narrative.json"))
        if not narrative_files:
            print(f"skip ticker={ticker} reason=no_narrative_files")
            continue

        ticker_deferred = ticker_flagged = 0

        for in_path in narrative_files:
            payload = json.loads(in_path.read_text(encoding="utf-8"))
            ready = preformat_narrative(payload)

            # Derive output filename: replace _narrative.json → _narrative_ready.json
            out_name = in_path.name.replace("_narrative.json", "_narrative_ready.json")
            out_path = ticker_out_dir / out_name
            out_json = json.dumps(ready, indent=2)
            out_path.write_text(out_json, encoding="utf-8")

            if gcs_client:
                blob_name = f"{args.gcs_prefix}/narrative_ready/{ticker}/{out_name}"
                bucket = gcs_client.bucket(args.gcs_bucket)
                bucket.blob(blob_name).upload_from_string(out_json, content_type="application/json")

            flags = ready["pre_formatting_flags"]
            if flags["risk_factors_deferred"]:
                ticker_deferred += 1
            if flags["mda_very_short"] or flags["mda_boilerplate_heavy"] or flags["sections_missing"]:
                ticker_flagged += 1
            if flags["sections_missing"]:
                total_missing += len(flags["sections_missing"])

            total_files += 1

        total_deferred += ticker_deferred
        total_flagged += ticker_flagged
        print(
            f"ticker={ticker} files={len(narrative_files)}"
            f" deferred={ticker_deferred} flagged={ticker_flagged}"
        )

    print()
    print(f"done total_files={total_files} deferred={total_deferred}"
          f" quality_flags={total_flagged} missing_sections={total_missing}")
    if gcs_client:
        print(f"uploaded to gs://{args.gcs_bucket}/{args.gcs_prefix}/narrative_ready/")


if __name__ == "__main__":
    main()
