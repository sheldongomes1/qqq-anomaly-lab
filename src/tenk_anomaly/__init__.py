"""tenk_anomaly package."""

from .edgar_client import EdgarAuth, EdgarClient, normalize_cik
from .narrative import extract_narrative_universe_filings
from .narrative_preformat import preformat_narrative
from .sec_ingest import (
    extract_10k_filing_by_ticker_year,
    ingest_companies,
    precompute_universe_filings,
    write_ingest_outputs,
)

__all__ = [
    "EdgarAuth",
    "EdgarClient",
    "normalize_cik",
    "extract_narrative_universe_filings",
    "preformat_narrative",
    "extract_10k_filing_by_ticker_year",
    "ingest_companies",
    "precompute_universe_filings",
    "write_ingest_outputs",
]
