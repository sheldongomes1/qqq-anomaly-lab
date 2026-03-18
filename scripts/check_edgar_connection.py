from __future__ import annotations

import os

from tenk_anomaly import EdgarAuth, EdgarClient


def main() -> None:
    email = os.getenv("SEC_API_EMAIL")
    if not email:
        raise RuntimeError("Set SEC_API_EMAIL before running this script.")

    app_name = os.getenv("SEC_APP_NAME", "10k-anomaly")
    filer_token = os.getenv("SEC_FILER_API_TOKEN")
    user_token = os.getenv("SEC_USER_API_TOKEN")

    client = EdgarClient(
        email=email,
        app_name=app_name,
        auth=EdgarAuth(
            filer_api_token=filer_token,
            user_api_token=user_token,
        ),
    )

    # Apple CIK: 0000320193
    submissions = client.get_submissions("320193")
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])

    print(f"company={submissions.get('name')}")
    if forms and accessions:
        print(f"latest_form={forms[0]} accession={accessions[0]}")
    else:
        print("No recent forms found in response.")


if __name__ == "__main__":
    main()
