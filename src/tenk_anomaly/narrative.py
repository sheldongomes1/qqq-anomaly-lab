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


_MIN_SECTION_CHARS = 500  # positions yielding less content are likely TOC entries

# Used by _try_mda_fallback to detect TOC-style content (many standalone page numbers).
_TOC_NUMBER_RE = re.compile(r"\b\d{1,3}\b")
_TOC_NUMBER_THRESHOLD = 4  # more than this many standalone 1-3-digit numbers in 500 chars → TOC


def _try_mda_fallback(text: str) -> str | None:
    """Find MDA content when the standard 'Item 7 / Item 2' pattern yields nothing.

    Some filers (e.g. INTC, HON) use a standalone 'Management's Discussion and
    Analysis' heading without an 'Item X' prefix.  Their primary filing document
    is a hyperlinked TOC, so all standard Item-X matches hit short TOC entries
    and are rejected.  This fallback searches for the standalone heading and
    returns the first prose match (not TOC-like) with substantial content.
    """
    pattern = r"management.s\s+discussion\s+and\s+analysis"
    matches = list(re.finditer(pattern, text.lower()))
    if not matches:
        return None

    # Try from last to first; return first non-TOC-like match with enough content.
    for m in reversed(matches):
        pos = m.start()
        sample = text[pos : pos + 500]
        if len(_TOC_NUMBER_RE.findall(sample)) > _TOC_NUMBER_THRESHOLD:
            continue  # skip TOC entries (high page-number density)
        if len(text) - pos >= _MIN_SECTION_CHARS:
            return text[pos : pos + _MAX_SECTION_CHARS]

    return None


def extract_filing_sections(text: str, form: str) -> dict[str, str]:
    """Split cleaned filing text into named narrative sections.

    For each section header, finds the candidate position that yields the most
    content — this avoids mis-selecting table-of-contents entries or inline
    cross-references that appear after the actual section in the document.

    Falls back to a truncated full_text block if no section headers are found.
    """
    headers = _TENK_HEADERS if "10-K" in form.upper() else _TENQ_HEADERS
    text_lower = text.lower()

    # Collect all candidate positions for each section.
    all_candidates: dict[str, list[int]] = {}
    for name, pattern in headers:
        matches = list(re.finditer(pattern, text_lower))
        if matches:
            all_candidates[name] = [m.start() for m in matches]

    if not all_candidates:
        return {"full_text": text[:_MAX_SECTION_CHARS]}

    # Pick the best candidate for each section.
    # Strategy: try candidates from last to first; accept the first one whose
    # content length (to the nearest following section candidate) exceeds the
    # minimum threshold.  Fall back to the last candidate if none qualify.
    def _pick_best(name: str, candidates: list[int]) -> int:
        other_starts = [
            pos
            for other_name, cands in all_candidates.items()
            if other_name != name
            for pos in cands
        ]
        for pos in reversed(candidates):
            # Compute tentative content length: distance to the nearest
            # section start that comes after this position.
            after = [s for s in other_starts if s > pos]
            content_len = (min(after) - pos) if after else (len(text) - pos)
            if content_len >= _MIN_SECTION_CHARS:
                return pos
        return candidates[-1]  # fallback: last candidate

    selected: dict[str, int] = {
        name: _pick_best(name, cands)
        for name, cands in all_candidates.items()
    }

    # 10-K domain sanity: Item 1A (risk_factors) must precede Item 7 (mda).
    # If the selected risk_factors position falls after mda, it is almost certainly
    # an inline cross-reference captured mid-sentence (e.g. NVDA: "should be read in
    # conjunction with 'Item 1A. Risk Factors'").  Fall back to the latest
    # risk_factors candidate that precedes the mda start.
    if "10-K" in form.upper() and "risk_factors" in selected and "mda" in selected:
        if selected["risk_factors"] > selected["mda"]:
            pre_mda = [p for p in all_candidates["risk_factors"] if p < selected["mda"]]
            if pre_mda:
                selected["risk_factors"] = max(pre_mda)

    positions: list[tuple[str, int]] = sorted(selected.items(), key=lambda x: x[1])

    sections: dict[str, str] = {}
    for i, (name, start) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else len(text)
        sections[name] = text[start:end][:_MAX_SECTION_CHARS]

    # If the MDA section is very short (likely a TOC entry was selected), try the
    # standalone-heading fallback.  This handles filers like INTC/HON whose primary
    # document is a cross-referenced TOC with the actual narrative under a bare
    # "Management's Discussion and Analysis" heading.
    if len(sections.get("mda", "")) < _MIN_SECTION_CHARS:
        fallback = _try_mda_fallback(text)
        if fallback:
            sections["mda"] = fallback

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
