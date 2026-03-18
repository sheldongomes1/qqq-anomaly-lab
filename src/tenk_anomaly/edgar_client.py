from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests


def normalize_cik(cik: str | int) -> str:
    """Return a 10-digit, zero-padded CIK string."""
    digits = "".join(ch for ch in str(cik) if ch.isdigit())
    if not digits:
        raise ValueError("CIK must contain at least one digit.")
    if len(digits) > 10:
        raise ValueError("CIK cannot have more than 10 digits.")
    return digits.zfill(10)


@dataclass(frozen=True)
class EdgarAuth:
    filer_api_token: str | None = None
    user_api_token: str | None = None
    filer_token_header: str = "filer-api-token"
    user_token_header: str = "user-api-token"


class EdgarClient:
    """Client for SEC EDGAR public data APIs and filing APIs.

    This client supports:
    - Public EDGAR data endpoints via `https://data.sec.gov`
    - Filing endpoints via `https://api.edgarfiling.sec.gov`
    """

    def __init__(
        self,
        *,
        email: str,
        app_name: str = "10k-anomaly",
        organization: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 1.0,
        data_base_url: str = "https://data.sec.gov",
        filing_base_url: str = "https://api.edgarfiling.sec.gov",
        auth: EdgarAuth | None = None,
        session: requests.Session | None = None,
    ) -> None:
        if not email or "@" not in email:
            raise ValueError("A valid contact email is required for SEC User-Agent.")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")

        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.data_base_url = data_base_url.rstrip("/")
        self.filing_base_url = filing_base_url.rstrip("/")
        self.auth = auth or EdgarAuth()
        self.session = session or requests.Session()

        org_segment = f" {organization}" if organization else ""
        self.user_agent = f"{app_name}{org_segment} ({email})"
        self.default_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

    def _request_json(
        self,
        *,
        method: str,
        base_url: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any]:
        headers = dict(self.default_headers)
        if extra_headers:
            headers.update(extra_headers)

        url = f"{base_url}/{path.lstrip('/')}"
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise
                time.sleep(self.retry_backoff_seconds * attempt)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                time.sleep(self.retry_backoff_seconds * attempt)
                continue

            response.raise_for_status()
            return response.json()

        if last_error is not None:
            raise last_error
        raise RuntimeError("Request failed after retries.")

    def get_submissions(self, cik: str | int) -> dict[str, Any]:
        cik10 = normalize_cik(cik)
        return self._request_json(
            method="GET",
            base_url=self.data_base_url,
            path=f"submissions/CIK{cik10}.json",
        )

    def get_company_facts(self, cik: str | int) -> dict[str, Any]:
        cik10 = normalize_cik(cik)
        return self._request_json(
            method="GET",
            base_url=self.data_base_url,
            path=f"api/xbrl/companyfacts/CIK{cik10}.json",
        )

    def get_company_concept(
        self,
        *,
        cik: str | int,
        taxonomy: str,
        tag: str,
    ) -> dict[str, Any]:
        cik10 = normalize_cik(cik)
        return self._request_json(
            method="GET",
            base_url=self.data_base_url,
            path=f"api/xbrl/companyconcept/CIK{cik10}/{taxonomy}/{tag}.json",
        )

    def get_company_tickers(self) -> dict[str, Any]:
        return self._request_json(
            method="GET",
            base_url="https://www.sec.gov",
            path="files/company_tickers.json",
        )

    def get_nasdaq_100_constituents(self) -> list[dict[str, Any]]:
        """Return current Nasdaq-100 constituents from Nasdaq public API."""
        headers = dict(self.default_headers)
        headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nasdaq.com/",
            }
        )
        url = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(
                    method="GET",
                    url=url,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise
                time.sleep(self.retry_backoff_seconds * attempt)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                time.sleep(self.retry_backoff_seconds * attempt)
                continue

            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", {}).get("data", {}).get("rows", [])
            if not isinstance(rows, list):
                return []
            result: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol", "")).strip()
                company_name = str(row.get("companyName", "")).strip()
                if symbol:
                    result.append({"ticker": symbol, "company_name": company_name})
            return result

        if last_error is not None:
            raise last_error
        raise RuntimeError("Failed to fetch Nasdaq-100 constituents.")

    def get_text_at_url(self, url: str, *, accept: str = "text/html, text/plain;q=0.9, */*;q=0.8") -> str:
        headers = dict(self.default_headers)
        headers["Accept"] = accept
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(
                    method="GET",
                    url=url,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise
                time.sleep(self.retry_backoff_seconds * attempt)
                continue

            if response.status_code in {429, 500, 502, 503, 504} and attempt < self.max_retries:
                time.sleep(self.retry_backoff_seconds * attempt)
                continue

            response.raise_for_status()
            return response.text

        if last_error is not None:
            raise last_error
        raise RuntimeError("Text request failed after retries.")

    def filing_request(
        self,
        *,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        require_user_token: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any]:
        headers = dict(extra_headers or {})
        if self.auth.filer_api_token:
            headers[self.auth.filer_token_header] = self.auth.filer_api_token
        if require_user_token and self.auth.user_api_token:
            headers[self.auth.user_token_header] = self.auth.user_api_token
        if require_user_token and not self.auth.user_api_token:
            raise ValueError("This endpoint requires a user API token.")

        return self._request_json(
            method=method,
            base_url=self.filing_base_url,
            path=path,
            params=params,
            json_body=json_body,
            extra_headers=headers,
        )
