"""Backfill qqq_manifest.json from existing GCS files.

Reads every *_analysis_ready.json from GCS, extracts the accession_number
from the payload, and registers it in manifest["tickers"][ticker].

Run once after the initial dataset was generated without manifest support.
"""
from __future__ import annotations

import argparse
import json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill qqq_manifest.json from existing GCS analysis_ready files."
    )
    parser.add_argument("--gcs-bucket", required=True, help="GCS bucket name.")
    parser.add_argument("--gcs-prefix", default="qqq", help="GCS path prefix (default: qqq).")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be added without writing.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        from google.cloud import storage as gcs
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage required. Run: pip install google-cloud-storage") from exc

    client = gcs.Client()
    bucket = client.bucket(args.gcs_bucket)
    manifest_blob_name = f"{args.gcs_prefix}/qqq_manifest.json"

    # Load existing manifest
    manifest_blob = bucket.blob(manifest_blob_name)
    if manifest_blob.exists():
        manifest: dict = json.loads(manifest_blob.download_as_text())
        print(f"manifest_loaded existing tickers={len(manifest.get('tickers', {}))}")
    else:
        manifest = {"tickers": {}}
        print("manifest_not_found creating_fresh")

    if "tickers" not in manifest:
        manifest["tickers"] = {}

    # List all analysis_ready.json files (exclude narrative/ subfolder)
    prefix = f"{args.gcs_prefix}/"
    blobs = list(client.list_blobs(args.gcs_bucket, prefix=prefix))
    analysis_blobs = [
        b for b in blobs
        if b.name.endswith("_analysis_ready.json") and "/narrative/" not in b.name
    ]
    print(f"found {len(analysis_blobs)} analysis_ready files in GCS")

    added = 0
    for blob in analysis_blobs:
        # Extract ticker from path: qqq/AAPL/AAPL_2025_10K_analysis_ready.json
        parts = blob.name.split("/")
        if len(parts) < 3:
            continue
        ticker = parts[-2].upper()

        # Download and parse to get accession_number
        try:
            payload = json.loads(blob.download_as_text())
            accession = str(payload.get("selected_filing", {}).get("accession_number", ""))
        except Exception as exc:
            print(f"skip blob={blob.name} reason={exc}")
            continue

        if not accession:
            print(f"skip blob={blob.name} reason=no_accession_number")
            continue

        existing = set(manifest["tickers"].get(ticker, []))
        if accession not in existing:
            existing.add(accession)
            manifest["tickers"][ticker] = sorted(existing)
            added += 1

    print(f"backfill complete added={added} dry_run={args.dry_run}")

    if not args.dry_run:
        from datetime import datetime, timezone
        manifest["last_updated"] = datetime.now(timezone.utc).isoformat()
        manifest_json = json.dumps(manifest, indent=2)
        manifest_blob.upload_from_string(manifest_json, content_type="application/json")
        print(f"manifest_saved gs://{args.gcs_bucket}/{manifest_blob_name}")
        print(f"total tickers in manifest={len(manifest['tickers'])}")


if __name__ == "__main__":
    main()
