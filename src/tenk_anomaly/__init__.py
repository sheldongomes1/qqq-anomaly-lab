"""tenk_anomaly package."""

from .detector import IsolationForestDetector
from .edgar_client import EdgarAuth, EdgarClient, normalize_cik
from .sec_ingest import (
    extract_10k_filing_by_ticker_year,
    ingest_companies,
    precompute_universe_filings,
    write_ingest_outputs,
)

__all__ = [
    "IsolationForestDetector",
    "EdgarAuth",
    "EdgarClient",
    "normalize_cik",
    "extract_10k_filing_by_ticker_year",
    "ingest_companies",
    "precompute_universe_filings",
    "write_ingest_outputs",
]
