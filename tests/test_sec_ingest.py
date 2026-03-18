from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from tenk_anomaly.sec_ingest import (
    build_filing_document_url,
    build_engineered_anomaly_features,
    build_company_feature_row,
    extract_recent_form_filings,
    extract_10k_filing_by_ticker_year,
    extract_recent_10k_filings,
    html_to_clean_text,
    ingest_companies,
    latest_company_fact_value,
    precompute_universe_filings,
    select_form_filings_for_year,
    select_10k_for_year,
    ticker_to_cik,
)


class StubClient:
    def get_company_tickers(self) -> dict[str, Any]:
        return {"0": {"cik_str": 1652044, "ticker": "GOOG", "title": "Alphabet Inc."}}

    def get_submissions(self, cik: str) -> dict[str, Any]:
        return {
            "cik": cik,
            "name": "Example Co",
            "filings": {
                "recent": {
                    "form": ["8-K", "10-K", "10-Q", "10-K"],
                    "accessionNumber": ["a1", "a2", "a3", "a4"],
                    "filingDate": ["2025-01-10", "2024-02-10", "2024-05-10", "2023-02-11"],
                    "reportDate": ["2025-01-09", "2023-12-31", "2024-03-31", "2022-12-31"],
                    "primaryDocument": ["x.htm", "k1.htm", "q1.htm", "k2.htm"],
                }
            },
        }

    def get_company_facts(self, cik: str) -> dict[str, Any]:
        return {
            "facts": {
                "us-gaap": {
                    "Assets": {
                        "units": {
                            "USD": [
                                {"val": 100.0, "end": "2022-12-31", "filed": "2023-02-11", "fy": 2022, "fp": "FY"},
                                {"val": 150.0, "end": "2023-12-31", "filed": "2024-02-10", "fy": 2023, "fp": "FY"},
                            ]
                        }
                    },
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"val": 42.0, "end": "2023-12-31", "filed": "2024-02-10", "fy": 2023, "fp": "FY"}
                            ]
                        }
                    },
                }
            }
        }

    def get_text_at_url(self, url: str, *, accept: str = "text/html, text/plain;q=0.9, */*;q=0.8") -> str:
        _ = accept
        return f"<html><body>stub filing for {url}</body></html>"


def test_extract_recent_10k_filings_filters_to_10k() -> None:
    submissions = StubClient().get_submissions("320193")
    df = extract_recent_10k_filings(submissions, cik="320193", max_filings=5)
    assert isinstance(df, pd.DataFrame)
    assert set(df["form"].unique()) == {"10-K"}
    assert len(df) == 2


def test_latest_company_fact_value_picks_latest_entry() -> None:
    company_facts = StubClient().get_company_facts("320193")
    value, metadata = latest_company_fact_value(company_facts, tag="Assets")
    assert value == 150.0
    assert metadata is not None
    assert metadata["fy"] == 2023


def test_build_company_feature_row_contains_expected_fields() -> None:
    client = StubClient()
    row = build_company_feature_row(
        cik="320193",
        submissions=client.get_submissions("320193"),
        company_facts=client.get_company_facts("320193"),
    )
    assert row["cik"] == "0000320193"
    assert row["assets_usd"] == 150.0
    assert row["revenue_usd"] == 42.0
    assert row["latest_10k_accession_number"] == "a2"


def test_ingest_companies_returns_dataframes() -> None:
    filings_df, features_df = ingest_companies(client=StubClient(), ciks=["320193"])
    assert len(filings_df) == 2
    assert len(features_df) == 1


def test_ticker_to_cik_and_url_builder() -> None:
    company_tickers = StubClient().get_company_tickers()
    cik = ticker_to_cik(company_tickers, "goog")
    assert cik == "0001652044"
    url = build_filing_document_url(
        cik=cik,
        accession_number="0001652044-25-000001",
        primary_document="annual10k.htm",
    )
    assert "/1652044/000165204425000001/annual10k.htm" in url


def test_select_10k_for_year_prefers_report_date_then_filing_date() -> None:
    submissions = StubClient().get_submissions("320193")
    tenk_df = extract_recent_10k_filings(submissions, cik="320193", max_filings=10)
    selected_2023 = select_10k_for_year(tenk_df, year=2023)
    assert selected_2023["year_match_basis"] == "report_date"
    assert selected_2023["accession_number"] == "a2"

    selected_fallback = select_10k_for_year(tenk_df, year=2024)
    assert selected_fallback["year_match_basis"] == "filing_date"
    assert selected_fallback["accession_number"] == "a2"


def test_extract_10k_filing_by_ticker_year_writes_outputs(tmp_path: Path) -> None:
    result = extract_10k_filing_by_ticker_year(
        client=StubClient(),
        ticker="GOOG",
        year=2024,
        output_dir=tmp_path,
    )
    assert result["metadata_path"].exists()
    assert result["filing_path"].exists()
    assert result["candidate_filings_path"].exists()
    assert result["analysis_ready_path"].exists()

    payload = json.loads(result["analysis_ready_path"].read_text(encoding="utf-8"))
    assert payload["extraction_input"]["ticker"] == "GOOG"
    assert payload["resolved_company"]["cik"] == "0001652044"
    assert "financial_features_latest" in payload
    assert "filing_text_clean" in payload


def test_html_to_clean_text_strips_tags() -> None:
    html = "<html><body><script>x=1;</script><h1>Title</h1><p>Alpha&nbsp;Beta</p></body></html>"
    cleaned = html_to_clean_text(html)
    assert "Title" in cleaned
    assert "Alpha Beta" in cleaned
    assert "x=1" not in cleaned


def test_extract_recent_form_filings_and_year_selector() -> None:
    submissions = StubClient().get_submissions("320193")
    tenq = extract_recent_form_filings(submissions, form="10-Q", cik="320193")
    assert len(tenq) == 1
    selected_2024 = select_form_filings_for_year(tenq, year=2024)
    assert len(selected_2024) == 1
    assert selected_2024.iloc[0]["form"] == "10-Q"


def test_precompute_universe_filings_creates_company_outputs(tmp_path: Path) -> None:
    summary = precompute_universe_filings(
        client=StubClient(),
        tickers=["GOOG"],
        start_year=2024,
        end_year=2024,
        include_quarterly=True,
        include_html=False,
        output_dir=tmp_path,
    )
    assert summary["ticker_count"] == 1
    assert summary["include_quarterly"] is True
    files = list((tmp_path / "GOOG").glob("*.json"))
    assert any("10K" in f.name for f in files)
    assert any("10Q" in f.name for f in files)


def test_engineered_features_use_target_period_for_quarters() -> None:
    feature_history = pd.DataFrame(
        [
            {"feature_name": "assets_usd", "value": 100.0, "period_end": "2024-06-30"},
            {"feature_name": "assets_usd", "value": 120.0, "period_end": "2025-06-30"},
            {"feature_name": "liabilities_usd", "value": 40.0, "period_end": "2024-06-30"},
            {"feature_name": "liabilities_usd", "value": 48.0, "period_end": "2025-06-30"},
            {"feature_name": "equity_usd", "value": 60.0, "period_end": "2024-06-30"},
            {"feature_name": "equity_usd", "value": 72.0, "period_end": "2025-06-30"},
            {"feature_name": "revenue_usd", "value": 20.0, "period_end": "2024-06-30"},
            {"feature_name": "revenue_usd", "value": 30.0, "period_end": "2025-06-30"},
            {"feature_name": "net_income_usd", "value": 4.0, "period_end": "2024-06-30"},
            {"feature_name": "net_income_usd", "value": 6.0, "period_end": "2025-06-30"},
            {"feature_name": "operating_cash_flow_usd", "value": 5.0, "period_end": "2024-06-30"},
            {"feature_name": "operating_cash_flow_usd", "value": 7.0, "period_end": "2025-06-30"},
        ]
    )
    engineered = build_engineered_anomaly_features(
        feature_history=feature_history,
        target_year=2025,
        target_period_end="2025-06-30",
        target_form="10-Q",
    )
    assert engineered["target_period_end"] == "2025-06-30"
    assert engineered["debt_to_assets"] == 0.4
    assert engineered["revenue_growth_yoy"] == 0.5
