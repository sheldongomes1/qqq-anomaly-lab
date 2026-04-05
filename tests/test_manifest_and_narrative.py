from __future__ import annotations

import json
from unittest.mock import MagicMock

from tenk_anomaly.narrative import extract_filing_sections
from tenk_anomaly.sec_ingest import _load_manifest, _save_manifest


# ---------------------------------------------------------------------------
# _load_manifest
# ---------------------------------------------------------------------------

def test_load_manifest_fresh_when_no_file_and_no_gcs(tmp_path):
    result = _load_manifest(tmp_path / "manifest.json", None, None, "qqq/manifest.json")
    assert result == {"tickers": {}}


def test_load_manifest_reads_local_file(tmp_path):
    manifest = {"tickers": {"AAPL": ["acc1", "acc2"]}}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    result = _load_manifest(path, None, None, "qqq/manifest.json")
    assert result["tickers"]["AAPL"] == ["acc1", "acc2"]


def test_load_manifest_prefers_gcs_over_local(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"tickers": {"AAPL": ["local_acc"]}}))

    blob = MagicMock()
    blob.exists.return_value = True
    blob.download_as_text.return_value = json.dumps({"tickers": {"AAPL": ["gcs_acc"]}})
    gcs_client = MagicMock()
    gcs_client.bucket.return_value.blob.return_value = blob

    result = _load_manifest(path, gcs_client, "my-bucket", "qqq/manifest.json")
    assert result["tickers"]["AAPL"] == ["gcs_acc"]


def test_load_manifest_falls_back_to_local_when_gcs_fails(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"tickers": {"MSFT": ["acc_local"]}}))

    gcs_client = MagicMock()
    gcs_client.bucket.side_effect = Exception("GCS unavailable")

    result = _load_manifest(path, gcs_client, "my-bucket", "qqq/manifest.json")
    assert result["tickers"]["MSFT"] == ["acc_local"]


def test_load_manifest_returns_fresh_when_gcs_blob_missing_and_no_local(tmp_path):
    blob = MagicMock()
    blob.exists.return_value = False
    gcs_client = MagicMock()
    gcs_client.bucket.return_value.blob.return_value = blob

    result = _load_manifest(tmp_path / "missing.json", gcs_client, "my-bucket", "qqq/manifest.json")
    assert result == {"tickers": {}}


# ---------------------------------------------------------------------------
# _save_manifest
# ---------------------------------------------------------------------------

def test_save_manifest_writes_local_file(tmp_path):
    path = tmp_path / "sub" / "manifest.json"  # parent dir doesn't exist yet
    _save_manifest({"tickers": {"NVDA": ["acc1"]}}, path, None, None, "qqq/manifest.json")
    saved = json.loads(path.read_text())
    assert saved["tickers"]["NVDA"] == ["acc1"]
    assert "last_updated" in saved


def test_save_manifest_uploads_to_gcs_when_client_provided(tmp_path):
    blob = MagicMock()
    gcs_client = MagicMock()
    gcs_client.bucket.return_value.blob.return_value = blob

    _save_manifest({"tickers": {}}, tmp_path / "manifest.json", gcs_client, "my-bucket", "qqq/manifest.json")
    blob.upload_from_string.assert_called_once()


def test_save_manifest_skips_gcs_upload_when_no_client(tmp_path):
    blob = MagicMock()
    _save_manifest({"tickers": {}}, tmp_path / "manifest.json", None, None, "qqq/manifest.json")
    blob.upload_from_string.assert_not_called()


# ---------------------------------------------------------------------------
# extract_filing_sections
# ---------------------------------------------------------------------------

_TENK_TEXT = """
Preamble content.

Item 1. Business
Apple designs iPhones and Mac computers. This is the business section.

Item 1A. Risk Factors
There are many risks including competition and supply chain issues.

Item 7. Management's Discussion and Analysis of Financial Condition
Revenue increased 12 percent year over year driven by iPhone sales.

Item 7A. Quantitative and Qualitative Disclosures About Market Risk
Interest rate exposure is managed through hedging instruments.

Item 8. Financial Statements and Supplementary Data
Consolidated Balance Sheet as of September 28, 2024.
"""

_TENQ_TEXT = """
Preamble.

Item 2. Management's Discussion and Analysis of Financial Condition
Revenue grew 8 percent this quarter compared to prior year.

Item 1A. Risk Factors
Market conditions remain volatile and unpredictable.

Item 3. Quantitative and Qualitative Disclosures About Market Risk
Foreign exchange risk is hedged using forward contracts.
"""


def test_extract_tenk_returns_expected_section_keys():
    sections = extract_filing_sections(_TENK_TEXT, form="10-K")
    assert "business" in sections
    assert "risk_factors" in sections
    assert "mda" in sections
    assert "quantitative_disclosures" in sections


def test_extract_tenk_business_contains_correct_content():
    sections = extract_filing_sections(_TENK_TEXT, form="10-K")
    assert "iPhones" in sections["business"]


def test_extract_tenk_mda_contains_correct_content():
    sections = extract_filing_sections(_TENK_TEXT, form="10-K")
    assert "Revenue increased" in sections["mda"]


def test_extract_tenk_risk_factors_does_not_bleed_into_mda():
    sections = extract_filing_sections(_TENK_TEXT, form="10-K")
    assert "Revenue increased" not in sections["risk_factors"]


def test_extract_tenq_uses_item_2_for_mda():
    sections = extract_filing_sections(_TENQ_TEXT, form="10-Q")
    assert "mda" in sections
    assert "Revenue grew" in sections["mda"]


def test_extract_sections_falls_back_to_full_text_when_no_headers():
    text = "This is a filing with no recognisable section headers at all."
    sections = extract_filing_sections(text, form="10-K")
    assert "full_text" in sections
    assert sections["full_text"] == text


def test_extract_sections_truncates_at_max_chars():
    long_text = "Item 1. Business\n" + "x" * 200_000
    sections = extract_filing_sections(long_text, form="10-K")
    assert len(sections["business"]) <= 100_000
