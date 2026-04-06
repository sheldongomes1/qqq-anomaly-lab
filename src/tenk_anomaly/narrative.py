from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .edgar_client import EdgarClient
from .sec_ingest import (
    _load_manifest,
    _safe_filename_segment,
    _save_manifest,
    _upload_to_gcs,
    build_filing_document_url,
    extract_recent_form_filings,
    html_to_clean_text,
    select_form_filings_for_year,
    ticker_to_cik,
)

_MAX_SECTION_CHARS = 100_000

# Section header patterns applied to lowercased cleaned text.
# Ordered by expected position in the document.
_TENK_HEADERS: list[tuple[str, str]] = [
    ("business", r"item\s+1[^\w]+business"),
    ("risk_factors", r"item\s+1a[^\w]+risk\s+factor"),
    ("mda", r"item\s+7[^\w]+management"),
    ("quantitative_disclosures", r"item\s+7a[^\w]+quantitative"),
    ("financial_statements", r"item\s+8[^\w]+financial\s+statement"),
]

_TENQ_HEADERS: list[tuple[str, str]] = [
    ("mda", r"item\s+2[^\w]+management"),
    ("risk_factors", r"item\s+1a[^\w]+risk\s+factor"),
    ("quantitative_disclosures", r"item\s+3[^\w]+quantitative"),
]


def extract_filing_sections(text: str, form: str) -> dict[str, str]:
    """Split cleaned filing text into named narrative sections.

    Falls back to a truncated full_text block if no section headers are found.
    """
    headers = _TENK_HEADERS if "10-K" in form.upper() else _TENQ_HEADERS
    text_lower = text.lower()

    positions: list[tuple[str, int]] = []
    for name, pattern in headers:
        # Use the last match to skip table-of-contents entries.
        matches = list(re.finditer(pattern, text_lower))
        if matches:
            positions.append((name, matches[-1].start()))

    if not positions:
        return {"full_text": text[:_MAX_SECTION_CHARS]}

    positions.sort(key=lambda x: x[1])

    sections: dict[str, str] = {}
    for i, (name, start) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else len(text)
        sections[name] = text[start:end][:_MAX_SECTION_CHARS]

    return sections


def extract_narrative_universe_filings(
    *,
    client: EdgarClient,
    tickers: list[str],
    start_year: int,
    end_year: int,
    include_quarterly: bool,
    output_dir: str | Path,
    gcs_bucket: str | None = None,
    gcs_prefix: str = "qqq",
) -> dict[str, Any]:
    """Fetch filing HTML, extract narrative sections, and store as separate JSON files.

    GCS path: {gcs_prefix}/narrative/{TICKER}/{TICKER}_{YEAR}_{FORM}_narrative.json
    Manifest key: manifest["narrative"][ticker] = [accession_number, ...]
    """
    if end_year < start_year:
        raise ValueError("end_year must be >= start_year")

    years = list(range(start_year, end_year + 1))
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    _gcs_client: Any = None
    if gcs_bucket:
        try:
            from google.cloud import storage as _gcs_mod  # type: ignore[import]
            _gcs_client = _gcs_mod.Client()
            print(f"gcs_enabled bucket={gcs_bucket} prefix={gcs_prefix}")
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-storage is required. Run: pip install google-cloud-storage"
            ) from exc

    manifest_local = out_dir / "qqq_manifest.json"
    manifest_blob = f"{gcs_prefix}/qqq_manifest.json"
    manifest = _load_manifest(manifest_local, _gcs_client, gcs_bucket, manifest_blob)
    if "narrative" not in manifest:
        manifest["narrative"] = {}

    company_tickers = client.get_company_tickers()
    summary_rows: list[dict[str, Any]] = []

    for raw_ticker in tickers:
        ticker = raw_ticker.upper().strip()
        cik = ticker_to_cik(company_tickers, ticker)
        submissions = client.get_submissions(cik)

        tenk_df = extract_recent_form_filings(
            submissions, form="10-K", cik=cik, max_filings=50, include_amendments=False,
        )
        tenq_df: pd.DataFrame = (
            extract_recent_form_filings(
                submissions, form="10-Q", cik=cik, max_filings=80, include_amendments=False,
            )
            if include_quarterly
            else pd.DataFrame()
        )

        narrative_dir = out_dir / ticker
        narrative_dir.mkdir(parents=True, exist_ok=True)

        seen: set[str] = set(manifest["narrative"].get(ticker, []))
        processed = 0
        skipped = 0

        for year in years:
            # --- Annual ---
            annual_selected = select_form_filings_for_year(tenk_df, year=year)
            if not annual_selected.empty:
                row = annual_selected.iloc[0].to_dict()
                accession = str(row["accession_number"])
                if accession in seen:
                    skipped += 1
                else:
                    filing_url = build_filing_document_url(
                        cik=cik,
                        accession_number=accession,
                        primary_document=str(row["primary_document"]),
                    )
                    raw_html = client.get_text_at_url(filing_url) or ""
                    clean_text = html_to_clean_text(raw_html) if raw_html else ""
                    sections = extract_filing_sections(clean_text, form="10-K") if clean_text else {}
                    payload = {
                        "ticker": ticker,
                        "year": year,
                        "form": "10-K",
                        "accession_number": accession,
                        "filing_date": str(row.get("filing_date") or ""),
                        "report_date": str(row.get("report_date") or ""),
                        "sections": sections,
                    }
                    stem = f"{ticker}_{year}_10K_narrative.json"
                    payload_json = json.dumps(payload, indent=2)
                    (narrative_dir / stem).write_text(payload_json, encoding="utf-8")
                    if _gcs_client:
                        _upload_to_gcs(
                            _gcs_client, gcs_bucket,  # type: ignore[arg-type]
                            f"{gcs_prefix}/narrative/{ticker}/{stem}", payload_json,
                        )
                    seen.add(accession)
                    processed += 1

            # --- Quarterly ---
            if include_quarterly and not tenq_df.empty:
                quarterly_selected = select_form_filings_for_year(tenq_df, year=year)
                for _, q_row in quarterly_selected.iterrows():
                    q = q_row.to_dict()
                    accession = str(q["accession_number"])
                    if accession in seen:
                        skipped += 1
                        continue
                    filing_url = build_filing_document_url(
                        cik=cik,
                        accession_number=accession,
                        primary_document=str(q["primary_document"]),
                    )
                    raw_html = client.get_text_at_url(filing_url) or ""
                    clean_text = html_to_clean_text(raw_html) if raw_html else ""
                    sections = extract_filing_sections(clean_text, form="10-Q") if clean_text else {}
                    report_date_seg = _safe_filename_segment(
                        str(q.get("report_date") or f"{year}")
                    )
                    payload = {
                        "ticker": ticker,
                        "year": year,
                        "form": "10-Q",
                        "accession_number": accession,
                        "filing_date": str(q.get("filing_date") or ""),
                        "report_date": str(q.get("report_date") or ""),
                        "sections": sections,
                    }
                    stem = f"{ticker}_{year}_10Q_{report_date_seg}_narrative.json"
                    payload_json = json.dumps(payload, indent=2)
                    (narrative_dir / stem).write_text(payload_json, encoding="utf-8")
                    if _gcs_client:
                        _upload_to_gcs(
                            _gcs_client, gcs_bucket,  # type: ignore[arg-type]
                            f"{gcs_prefix}/narrative/{ticker}/{stem}", payload_json,
                        )
                    seen.add(accession)
                    processed += 1

        manifest["narrative"][ticker] = sorted(seen)
        _save_manifest(manifest, manifest_local, _gcs_client, gcs_bucket, manifest_blob)
        print(f"ticker={ticker} new={processed} skipped={skipped}")

        summary_rows.append({
            "ticker": ticker,
            "cik": cik,
            "company_name": submissions.get("name"),
            "files_generated": processed,
            "files_skipped": skipped,
        })

    summary = {
        "start_year": start_year,
        "end_year": end_year,
        "include_quarterly": include_quarterly,
        "ticker_count": len(tickers),
        "companies": summary_rows,
    }
    summary_json = json.dumps(summary, indent=2)
    (out_dir / "qqq_narrative_summary.json").write_text(summary_json, encoding="utf-8")
    if _gcs_client:
        _upload_to_gcs(
            _gcs_client, gcs_bucket,  # type: ignore[arg-type]
            f"{gcs_prefix}/narrative/qqq_narrative_summary.json", summary_json,
        )
    return summary
