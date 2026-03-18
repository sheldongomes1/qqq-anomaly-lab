from __future__ import annotations

from typing import Any

import pytest

from tenk_anomaly import EdgarAuth, EdgarClient, normalize_cik


class DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


class DummySession:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, **kwargs: Any) -> DummyResponse:
        self.calls.append(kwargs)
        return DummyResponse(
            status_code=200,
            payload={"ok": True, "url": kwargs["url"], "headers": kwargs["headers"]},
        )


def test_normalize_cik() -> None:
    assert normalize_cik("320193") == "0000320193"
    assert normalize_cik("0000320193") == "0000320193"
    with pytest.raises(ValueError):
        normalize_cik("no-digits")


def test_get_submissions_builds_expected_url() -> None:
    session = DummySession()
    client = EdgarClient(email="dev@example.com", session=session)
    payload = client.get_submissions("320193")

    assert payload["ok"] is True
    assert payload["url"].endswith("/submissions/CIK0000320193.json")
    assert "User-Agent" in payload["headers"]


def test_filing_request_includes_tokens() -> None:
    session = DummySession()
    client = EdgarClient(
        email="dev@example.com",
        auth=EdgarAuth(
            filer_api_token="filer-token",
            user_api_token="user-token",
        ),
        session=session,
    )

    payload = client.filing_request(
        method="POST",
        path="/submissions",
        json_body={"hello": "world"},
        require_user_token=True,
    )

    headers = payload["headers"]
    assert headers["filer-api-token"] == "filer-token"
    assert headers["user-api-token"] == "user-token"
