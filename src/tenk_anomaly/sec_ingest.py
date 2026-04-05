from __future__ import annotations

import json
import re
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .edgar_client import EdgarClient, normalize_cik


DEFAULT_FEATURE_TAGS: dict[str, str] = {
    "assets_usd": "Assets",
    "liabilities_usd": "Liabilities",
    "equity_usd": "StockholdersEquity",
    "revenue_usd": "Revenues",
    "net_income_usd": "NetIncomeLoss",
    "operating_cash_flow_usd": "NetCashProvidedByUsedInOperatingActivities",
    "shares_outstanding": "CommonStockSharesOutstanding",
}


def _safe_list(mapping: dict[str, Any], *keys: str) -> list[Any]:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, dict):
            return []
        cur = cur.get(key)
    if isinstance(cur, list):
        return cur
    return []


def extract_recent_10k_filings(
    submissions: dict[str, Any],
    *,
    cik: str | int | None = None,
    max_filings: int = 8,
) -> pd.DataFrame:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = _safe_list(recent, "form")
    accession_numbers = _safe_list(recent, "accessionNumber")
    filing_dates = _safe_list(recent, "filingDate")
    report_dates = _safe_list(recent, "reportDate")
    primary_documents = _safe_list(recent, "primaryDocument")

    rows: list[dict[str, Any]] = []
    for idx, form in enumerate(forms):
        if form != "10-K":
            continue
        rows.append(
            {
                "cik": normalize_cik(cik or submissions.get("cik", "")),
                "company_name": submissions.get("name"),
                "form": form,
                "accession_number": accession_numbers[idx] if idx < len(accession_numbers) else None,
                "filing_date": filing_dates[idx] if idx < len(filing_dates) else None,
                "report_date": report_dates[idx] if idx < len(report_dates) else None,
                "primary_document": primary_documents[idx] if idx < len(primary_documents) else None,
            }
        )
        if len(rows) >= max_filings:
            break

    return pd.DataFrame(rows)


def extract_recent_form_filings(
    submissions: dict[str, Any],
    *,
    form: str,
    cik: str | int | None = None,
    max_filings: int = 40,
    include_amendments: bool = False,
) -> pd.DataFrame:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = _safe_list(recent, "form")
    accession_numbers = _safe_list(recent, "accessionNumber")
    filing_dates = _safe_list(recent, "filingDate")
    report_dates = _safe_list(recent, "reportDate")
    primary_documents = _safe_list(recent, "primaryDocument")

    base = form.strip().upper()
    allowed = {base}
    if include_amendments:
        allowed.add(f"{base}/A")

    rows: list[dict[str, Any]] = []
    for idx, value in enumerate(forms):
        form_value = str(value).upper()
        if form_value not in allowed:
            continue
        rows.append(
            {
                "cik": normalize_cik(cik or submissions.get("cik", "")),
                "company_name": submissions.get("name"),
                "form": value,
                "accession_number": accession_numbers[idx] if idx < len(accession_numbers) else None,
                "filing_date": filing_dates[idx] if idx < len(filing_dates) else None,
                "report_date": report_dates[idx] if idx < len(report_dates) else None,
                "primary_document": primary_documents[idx] if idx < len(primary_documents) else None,
            }
        )
        if len(rows) >= max_filings:
            break
    return pd.DataFrame(rows)


def select_form_filings_for_year(
    filings_df: pd.DataFrame,
    *,
    year: int,
) -> pd.DataFrame:
    if filings_df.empty:
        return filings_df

    by_report = filings_df[filings_df["report_date"].fillna("").astype(str).str.startswith(f"{year}-")]
    if not by_report.empty:
        return by_report.reset_index(drop=True)

    by_filing = filings_df[filings_df["filing_date"].fillna("").astype(str).str.startswith(f"{year}-")]
    return by_filing.reset_index(drop=True)


def ticker_to_cik(company_tickers: dict[str, Any], ticker: str) -> str:
    lookup = ticker.upper().strip()
    for row in company_tickers.values():
        if not isinstance(row, dict):
            continue
        if str(row.get("ticker", "")).upper() == lookup:
            return normalize_cik(row.get("cik_str", ""))
    raise ValueError(f"Ticker not found in SEC company list: {ticker}")


def build_filing_document_url(*, cik: str | int, accession_number: str, primary_document: str) -> str:
    normalized_cik = normalize_cik(cik)
    cik_no_padding = str(int(normalized_cik))
    accession_no_dashes = accession_number.replace("-", "")
    return (
        "https://www.sec.gov/Archives/edgar/data/"
        f"{cik_no_padding}/{accession_no_dashes}/{primary_document}"
    )


def select_10k_for_year(
    tenk_filings: pd.DataFrame,
    *,
    year: int,
) -> dict[str, Any]:
    if tenk_filings.empty:
        raise ValueError("No 10-K filings found for this company.")

    report_matches = tenk_filings[
        tenk_filings["report_date"].fillna("").astype(str).str.startswith(f"{year}-")
    ]
    if not report_matches.empty:
        selected = report_matches.iloc[0].to_dict()
        selected["year_match_basis"] = "report_date"
        return selected

    filing_matches = tenk_filings[
        tenk_filings["filing_date"].fillna("").astype(str).str.startswith(f"{year}-")
    ]
    if not filing_matches.empty:
        selected = filing_matches.iloc[0].to_dict()
        selected["year_match_basis"] = "filing_date"
        return selected

    raise ValueError(f"No 10-K found for year {year} using report_date or filing_date.")


def _pick_latest_fact_entry(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not entries:
        return None
    sorted_entries = sorted(
        entries,
        key=lambda row: (
            row.get("end") or "",
            row.get("filed") or "",
            row.get("fy") or 0,
            row.get("fp") or "",
        ),
        reverse=True,
    )
    return sorted_entries[0]


def latest_company_fact_value(
    company_facts: dict[str, Any],
    *,
    tag: str,
    taxonomy: str = "us-gaap",
    preferred_units: tuple[str, ...] = ("USD", "shares"),
) -> tuple[float | None, dict[str, Any] | None]:
    facts = company_facts.get("facts", {}).get(taxonomy, {})
    concept = facts.get(tag, {})
    units = concept.get("units", {})

    selected_entries: list[dict[str, Any]] = []
    for unit in preferred_units:
        if unit in units and isinstance(units[unit], list):
            selected_entries = units[unit]
            break

    if not selected_entries and units:
        any_unit = next(iter(units.keys()))
        any_entries = units.get(any_unit, [])
        if isinstance(any_entries, list):
            selected_entries = any_entries

    latest = _pick_latest_fact_entry(selected_entries)
    if latest is None:
        return None, None

    value = latest.get("val")
    return (float(value) if value is not None else None), latest


def build_company_feature_row(
    *,
    cik: str | int,
    submissions: dict[str, Any],
    company_facts: dict[str, Any],
    feature_tags: dict[str, str] | None = None,
) -> dict[str, Any]:
    tags = feature_tags or DEFAULT_FEATURE_TAGS
    normalized_cik = normalize_cik(cik)

    feature_row: dict[str, Any] = {
        "cik": normalized_cik,
        "company_name": submissions.get("name"),
        "latest_10k_filing_date": None,
        "latest_10k_accession_number": None,
    }

    tenk_df = extract_recent_10k_filings(submissions, cik=normalized_cik, max_filings=1)
    if not tenk_df.empty:
        feature_row["latest_10k_filing_date"] = tenk_df.iloc[0]["filing_date"]
        feature_row["latest_10k_accession_number"] = tenk_df.iloc[0]["accession_number"]

    for feature_name, tag in tags.items():
        value, metadata = latest_company_fact_value(company_facts, tag=tag)
        feature_row[feature_name] = value
        feature_row[f"{feature_name}_end_date"] = metadata.get("end") if metadata else None
        feature_row[f"{feature_name}_filed_date"] = metadata.get("filed") if metadata else None
        feature_row[f"{feature_name}_fiscal_year"] = metadata.get("fy") if metadata else None
        feature_row[f"{feature_name}_fiscal_period"] = metadata.get("fp") if metadata else None

    return feature_row


def ingest_companies(
    *,
    client: EdgarClient,
    ciks: Iterable[str | int],
    max_10k_filings_per_company: int = 8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    filing_frames: list[pd.DataFrame] = []
    feature_rows: list[dict[str, Any]] = []

    for cik in ciks:
        normalized_cik = normalize_cik(cik)
        submissions = client.get_submissions(normalized_cik)
        company_facts = client.get_company_facts(normalized_cik)

        filing_frames.append(
            extract_recent_10k_filings(
                submissions,
                cik=normalized_cik,
                max_filings=max_10k_filings_per_company,
            )
        )
        feature_rows.append(
            build_company_feature_row(
                cik=normalized_cik,
                submissions=submissions,
                company_facts=company_facts,
            )
        )

    filings_df = pd.concat(filing_frames, ignore_index=True) if filing_frames else pd.DataFrame()
    features_df = pd.DataFrame(feature_rows)
    return filings_df, features_df


def write_ingest_outputs(
    *,
    filings_df: pd.DataFrame,
    features_df: pd.DataFrame,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filings_path = out_dir / "tenk_recent_filings.csv"
    features_path = out_dir / "tenk_features.csv"
    filings_df.to_csv(filings_path, index=False)
    features_df.to_csv(features_path, index=False)
    return filings_path, features_path


def _df_records_with_nulls(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return df.where(pd.notna(df), None).to_dict(orient="records")


def html_to_clean_text(html_content: str) -> str:
    # Remove script/style blocks first.
    no_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_content)
    # Strip all tags, unescape entities, and normalize whitespace.
    no_tags = re.sub(r"(?is)<[^>]+>", " ", no_scripts)
    unescaped = unescape(no_tags).replace("\xa0", " ")
    normalized = re.sub(r"[ \t\r\f\v]+", " ", unescaped)
    normalized = re.sub(r"\n\s+", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _parse_attributes(tag_attributes: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r'([:\w-]+)\s*=\s*([\'"])(.*?)\2', tag_attributes, flags=re.S):
        key = match.group(1)
        value = unescape(match.group(3))
        attrs[key] = value
    return attrs


def _coerce_number(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    text = text.replace(",", "").replace("$", "").replace("\xa0", " ")
    # Convert accounting-style negatives: (123.4) -> -123.4
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_ixbrl_contexts(html_content: str) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    pattern = re.compile(r"<xbrli:context\b([^>]*)>(.*?)</xbrli:context>", flags=re.I | re.S)
    for match in pattern.finditer(html_content):
        attrs = _parse_attributes(match.group(1))
        body = match.group(2)
        context_id = attrs.get("id")
        if not context_id:
            continue

        start_match = re.search(r"<xbrli:startDate>(.*?)</xbrli:startDate>", body, flags=re.I | re.S)
        end_match = re.search(r"<xbrli:endDate>(.*?)</xbrli:endDate>", body, flags=re.I | re.S)
        instant_match = re.search(r"<xbrli:instant>(.*?)</xbrli:instant>", body, flags=re.I | re.S)
        identifier_match = re.search(r"<xbrli:identifier[^>]*>(.*?)</xbrli:identifier>", body, flags=re.I | re.S)

        start_date = start_match.group(1).strip() if start_match else None
        end_date = end_match.group(1).strip() if end_match else None
        instant = instant_match.group(1).strip() if instant_match else None
        period_end = end_date or instant
        period_type = "duration" if end_date else ("instant" if instant else None)

        contexts[context_id] = {
            "context_ref": context_id,
            "period_start": start_date,
            "period_end": period_end,
            "period_type": period_type,
            "entity_identifier": identifier_match.group(1).strip() if identifier_match else None,
        }
    return contexts


def parse_ixbrl_units(html_content: str) -> dict[str, str]:
    units: dict[str, str] = {}
    pattern = re.compile(r"<xbrli:unit\b([^>]*)>(.*?)</xbrli:unit>", flags=re.I | re.S)
    for match in pattern.finditer(html_content):
        attrs = _parse_attributes(match.group(1))
        body = match.group(2)
        unit_id = attrs.get("id")
        if not unit_id:
            continue

        measure_matches = re.findall(r"<xbrli:measure[^>]*>(.*?)</xbrli:measure>", body, flags=re.I | re.S)
        if measure_matches:
            units[unit_id] = "|".join(m.strip() for m in measure_matches)
        else:
            units[unit_id] = ""
    return units


def parse_ixbrl_facts(html_content: str) -> pd.DataFrame:
    contexts = parse_ixbrl_contexts(html_content)
    units = parse_ixbrl_units(html_content)
    rows: list[dict[str, Any]] = []

    pattern = re.compile(r"<ix:(nonFraction|nonNumeric)\b([^>]*)>(.*?)</ix:\1>", flags=re.I | re.S)
    for match in pattern.finditer(html_content):
        fact_type = match.group(1)
        attrs = _parse_attributes(match.group(2))
        raw_value = unescape(re.sub(r"(?is)<[^>]+>", " ", match.group(3))).strip()
        name = attrs.get("name")
        if not name:
            continue

        context_ref = attrs.get("contextRef")
        unit_ref = attrs.get("unitRef")
        context_meta = contexts.get(context_ref or "", {})

        row = {
            "fact_type": fact_type,
            "name": name,
            "context_ref": context_ref,
            "unit_ref": unit_ref,
            "unit": units.get(unit_ref or "", unit_ref),
            "raw_value": raw_value or None,
            "numeric_value": _coerce_number(raw_value),
            "decimals": attrs.get("decimals"),
            "format": attrs.get("format"),
            "scale": attrs.get("scale"),
            "period_start": context_meta.get("period_start"),
            "period_end": context_meta.get("period_end"),
            "period_type": context_meta.get("period_type"),
            "entity_identifier": context_meta.get("entity_identifier"),
        }
        rows.append(row)

    return pd.DataFrame(rows)


def _extract_concept_name(qname: str) -> str:
    return qname.split(":", 1)[1] if ":" in qname else qname


def extract_companyfacts_feature_history(
    *,
    company_facts: dict[str, Any],
    feature_tags: dict[str, str] | None = None,
) -> pd.DataFrame:
    tags = feature_tags or DEFAULT_FEATURE_TAGS
    rows: list[dict[str, Any]] = []
    facts = company_facts.get("facts", {}).get("us-gaap", {})
    for feature_name, concept in tags.items():
        concept_obj = facts.get(concept, {})
        units = concept_obj.get("units", {})
        for unit_name, entries in units.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                value = entry.get("val")
                if value is None:
                    continue
                end_date = entry.get("end")
                rows.append(
                    {
                        "feature_name": feature_name,
                        "concept": concept,
                        "source": "companyfacts",
                        "value": float(value),
                        "unit": unit_name,
                        "period_end": end_date,
                        "period_start": entry.get("start"),
                        "filed": entry.get("filed"),
                        "fy": entry.get("fy"),
                        "fp": entry.get("fp"),
                        "year": int(str(end_date)[:4]) if end_date else None,
                    }
                )
    return pd.DataFrame(rows)


def extract_ixbrl_feature_history(
    *,
    ixbrl_facts: pd.DataFrame,
    feature_tags: dict[str, str] | None = None,
) -> pd.DataFrame:
    if ixbrl_facts.empty:
        return pd.DataFrame()
    tags = feature_tags or DEFAULT_FEATURE_TAGS

    rows: list[dict[str, Any]] = []
    for feature_name, concept in tags.items():
        concept_pattern = re.compile(rf":{re.escape(concept)}$", flags=re.I)
        subset = ixbrl_facts[ixbrl_facts["name"].astype(str).str.contains(concept_pattern, na=False)]
        if subset.empty:
            continue

        for _, row in subset.iterrows():
            period_end = row.get("period_end")
            numeric_value = row.get("numeric_value")
            if numeric_value is None or (isinstance(numeric_value, float) and pd.isna(numeric_value)):
                continue
            rows.append(
                {
                    "feature_name": feature_name,
                    "concept": concept,
                    "source": "ixbrl",
                    "value": float(numeric_value),
                    "unit": row.get("unit"),
                    "period_end": period_end,
                    "period_start": row.get("period_start"),
                    "filed": None,
                    "fy": int(str(period_end)[:4]) if period_end else None,
                    "fp": "FY" if row.get("period_type") == "duration" else None,
                    "year": int(str(period_end)[:4]) if period_end else None,
                }
            )
    return pd.DataFrame(rows)


def combine_feature_histories(
    *,
    companyfacts_history: pd.DataFrame,
    ixbrl_history: pd.DataFrame,
    target_year: int,
) -> pd.DataFrame:
    frames = []
    if not companyfacts_history.empty:
        frames.append(companyfacts_history.copy())
    if not ixbrl_history.empty:
        frames.append(ixbrl_history.copy())
    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["year"].notna()].copy()
    combined["year"] = combined["year"].astype(int)
    combined["source_priority"] = combined["source"].map({"ixbrl": 0, "companyfacts": 1}).fillna(9).astype(int)
    # Prefer iXBRL for the target year, otherwise companyfacts usually has broader history quality.
    combined.loc[combined["year"] != int(target_year), "source_priority"] += 1
    combined = combined.sort_values(
        by=["feature_name", "period_end", "source_priority", "year"],
        ascending=[True, False, True, False],
    )
    deduped = combined.drop_duplicates(subset=["feature_name", "period_end"], keep="first")
    return deduped.sort_values(by=["feature_name", "period_end"]).drop(columns=["source_priority"])


def build_engineered_anomaly_features(
    *,
    feature_history: pd.DataFrame,
    target_year: int,
    target_period_end: str | None = None,
    target_form: str | None = None,
) -> dict[str, Any]:
    if feature_history.empty:
        return {}

    series: dict[str, dict[str, float]] = {}
    for _, row in feature_history.iterrows():
        feature = str(row["feature_name"])
        period_end = row.get("period_end")
        if not period_end:
            continue
        period_key = str(period_end)
        value = float(row["value"])
        series.setdefault(feature, {})[period_key] = value

    def parse_period(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def default_period_for_year(year: int) -> str:
        if str(target_form or "").upper().startswith("10-Q"):
            return f"{year}-09-30"
        return f"{year}-12-31"

    resolved_target_period = target_period_end or default_period_for_year(target_year)

    def get_value(name: str, period_end: str) -> float | None:
        return series.get(name, {}).get(period_end)

    def get_previous_year_same_period(name: str, period_end: str) -> float | None:
        current = parse_period(period_end)
        if current is None:
            return None
        prev_key = f"{current.year - 1:04d}-{current.month:02d}-{current.day:02d}"
        return series.get(name, {}).get(prev_key)

    def get_latest_for_year(name: str, year: int) -> float | None:
        entries = series.get(name, {})
        year_entries = [entries[k] for k in sorted(entries.keys()) if str(k).startswith(f"{year}-")]
        if not year_entries:
            return None
        return year_entries[-1]

    def safe_div(a: float | None, b: float | None) -> float | None:
        if a is None or b in (None, 0):
            return None
        return a / b

    def growth(name: str, period_end: str, year: int) -> float | None:
        cur = get_value(name, period_end)
        prev = get_previous_year_same_period(name, period_end)
        if prev is None:
            cur_year = get_latest_for_year(name, year)
            prev_year = get_latest_for_year(name, year - 1)
            cur = cur_year if cur_year is not None else cur
            prev = prev_year
        if cur is None or prev in (None, 0):
            return None
        return (cur - prev) / abs(prev)

    assets = get_value("assets_usd", resolved_target_period)
    liabilities = get_value("liabilities_usd", resolved_target_period)
    equity = get_value("equity_usd", resolved_target_period)
    revenue = get_value("revenue_usd", resolved_target_period)
    net_income = get_value("net_income_usd", resolved_target_period)
    operating_cash_flow = get_value("operating_cash_flow_usd", resolved_target_period)

    # Fallback for sparse features that may not be present for exact period.
    if assets is None:
        assets = get_latest_for_year("assets_usd", target_year)
    if liabilities is None:
        liabilities = get_latest_for_year("liabilities_usd", target_year)
    if equity is None:
        equity = get_latest_for_year("equity_usd", target_year)
    if revenue is None:
        revenue = get_latest_for_year("revenue_usd", target_year)
    if net_income is None:
        net_income = get_latest_for_year("net_income_usd", target_year)
    if operating_cash_flow is None:
        operating_cash_flow = get_latest_for_year("operating_cash_flow_usd", target_year)

    years_covered = sorted(
        {
            int(str(period_key)[:4])
            for feat in series.values()
            for period_key in feat.keys()
            if str(period_key)[:4].isdigit()
        }
    )
    return {
        "target_year": int(target_year),
        "target_period_end": resolved_target_period,
        "target_form": target_form,
        "years_covered": years_covered,
        "feature_count": len(series),
        "debt_to_assets": safe_div(liabilities, assets),
        "equity_to_assets": safe_div(equity, assets),
        "net_margin": safe_div(net_income, revenue),
        "ocf_to_net_income": safe_div(operating_cash_flow, net_income),
        "accrual_ratio": safe_div((net_income - operating_cash_flow) if (net_income is not None and operating_cash_flow is not None) else None, assets),
        "revenue_growth_yoy": growth("revenue_usd", resolved_target_period, target_year),
        "assets_growth_yoy": growth("assets_usd", resolved_target_period, target_year),
        "net_income_growth_yoy": growth("net_income_usd", resolved_target_period, target_year),
    }


def _safe_filename_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _make_filing_bundle_payload(
    *,
    ticker: str,
    year: int,
    filing_row: dict[str, Any],
    filing_url: str,
    filing_text: str | None,
    company_facts: dict[str, Any],
) -> dict[str, Any]:
    feature_history = extract_companyfacts_feature_history(company_facts=company_facts)
    engineered = build_engineered_anomaly_features(
        feature_history=feature_history,
        target_year=year,
        target_period_end=str(filing_row.get("report_date") or ""),
        target_form=str(filing_row.get("form") or ""),
    )

    payload: dict[str, Any] = {
        "extraction_input": {"ticker": ticker.upper(), "year": int(year)},
        "selected_filing": filing_row,
        "selected_filing_url": filing_url,
        "companyfacts_feature_history": _df_records_with_nulls(feature_history),
        "engineered_anomaly_features": engineered,
    }

    if filing_text is not None:
        clean_text = html_to_clean_text(filing_text)
        ixbrl_facts = parse_ixbrl_facts(filing_text)
        ixbrl_feature_history = extract_ixbrl_feature_history(ixbrl_facts=ixbrl_facts)
        combined_feature_history = combine_feature_histories(
            companyfacts_history=feature_history,
            ixbrl_history=ixbrl_feature_history,
            target_year=year,
        )
        payload.update(
            {
                "ixbrl_facts_stats": {
                    "total_facts": int(len(ixbrl_facts)),
                    "numeric_facts": int(ixbrl_facts["numeric_value"].notna().sum()) if not ixbrl_facts.empty else 0,
                    "contexts": int(ixbrl_facts["context_ref"].nunique()) if not ixbrl_facts.empty else 0,
                },
                "ixbrl_feature_history": _df_records_with_nulls(ixbrl_feature_history),
                "combined_feature_history": _df_records_with_nulls(combined_feature_history),
                "filing_text_clean": clean_text,
                "filing_text_stats": {
                    "character_count": len(clean_text),
                    "word_count": len(clean_text.split()),
                    "line_count": clean_text.count("\n") + 1 if clean_text else 0,
                },
            }
        )
    return payload


def _upload_to_gcs(gcs_client: Any, bucket_name: str, blob_name: str, data: str) -> None:
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(data, content_type="application/json")
    print(f"gcs_upload gs://{bucket_name}/{blob_name}")


def _load_manifest(
    local_path: Path,
    gcs_client: Any | None,
    gcs_bucket: str | None,
    gcs_blob: str,
) -> dict[str, Any]:
    """Load the processing manifest from GCS (preferred) or local fallback."""
    if gcs_client and gcs_bucket:
        try:
            bucket = gcs_client.bucket(gcs_bucket)
            blob = bucket.blob(gcs_blob)
            if blob.exists():
                data = json.loads(blob.download_as_text())
                print(f"manifest_loaded source=gcs gs://{gcs_bucket}/{gcs_blob}")
                return data
        except Exception as exc:
            print(f"manifest_gcs_load_failed reason={exc} falling_back=local")
    if local_path.exists():
        data = json.loads(local_path.read_text(encoding="utf-8"))
        print(f"manifest_loaded source=local path={local_path}")
        return data
    print("manifest_not_found starting_fresh")
    return {"tickers": {}}


def _save_manifest(
    manifest: dict[str, Any],
    local_path: Path,
    gcs_client: Any | None,
    gcs_bucket: str | None,
    gcs_blob: str,
) -> None:
    """Persist manifest to local disk and GCS."""
    from datetime import datetime, timezone
    manifest["last_updated"] = datetime.now(timezone.utc).isoformat()
    manifest_json = json.dumps(manifest, indent=2)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_text(manifest_json, encoding="utf-8")
    if gcs_client and gcs_bucket:
        _upload_to_gcs(gcs_client, gcs_bucket, gcs_blob, manifest_json)


def precompute_universe_filings(
    *,
    client: EdgarClient,
    tickers: list[str],
    start_year: int,
    end_year: int,
    include_quarterly: bool,
    include_html: bool,
    output_dir: str | Path,
    gcs_bucket: str | None = None,
    gcs_prefix: str = "qqq",
) -> dict[str, Any]:
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
                "google-cloud-storage is required for GCS upload. Run: pip install google-cloud-storage"
            ) from exc

    manifest_local = out_dir / "qqq_manifest.json"
    manifest_blob = f"{gcs_prefix}/qqq_manifest.json"
    manifest = _load_manifest(manifest_local, _gcs_client, gcs_bucket, manifest_blob)

    company_tickers = client.get_company_tickers()
    summary_rows: list[dict[str, Any]] = []

    for raw_ticker in tickers:
        ticker = raw_ticker.upper().strip()
        cik = ticker_to_cik(company_tickers, ticker)
        submissions = client.get_submissions(cik)
        company_facts = client.get_company_facts(cik)

        tenk_df = extract_recent_form_filings(
            submissions,
            form="10-K",
            cik=cik,
            max_filings=50,
            include_amendments=False,
        )
        tenq_df = extract_recent_form_filings(
            submissions,
            form="10-Q",
            cik=cik,
            max_filings=80,
            include_amendments=False,
        )

        company_dir = out_dir / ticker
        company_dir.mkdir(parents=True, exist_ok=True)

        seen: set[str] = set(manifest["tickers"].get(ticker, []))
        processed = 0
        skipped = 0

        for year in years:
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
                    filing_text = client.get_text_at_url(filing_url) if include_html else None
                    payload = _make_filing_bundle_payload(
                        ticker=ticker,
                        year=year,
                        filing_row=row,
                        filing_url=filing_url,
                        filing_text=filing_text,
                        company_facts=company_facts,
                    )
                    stem = f"{ticker}_{year}_10K_analysis_ready.json"
                    payload_json = json.dumps(payload, indent=2)
                    (company_dir / stem).write_text(payload_json, encoding="utf-8")
                    if _gcs_client:
                        _upload_to_gcs(_gcs_client, gcs_bucket, f"{gcs_prefix}/{ticker}/{stem}", payload_json)  # type: ignore[arg-type]
                    seen.add(accession)
                    processed += 1

            if include_quarterly:
                quarterly_selected = select_form_filings_for_year(tenq_df, year=year)
                for idx, (_, q_row) in enumerate(quarterly_selected.iterrows(), start=1):
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
                    filing_text = client.get_text_at_url(filing_url) if include_html else None
                    payload = _make_filing_bundle_payload(
                        ticker=ticker,
                        year=year,
                        filing_row=q,
                        filing_url=filing_url,
                        filing_text=filing_text,
                        company_facts=company_facts,
                    )
                    report_date = _safe_filename_segment(str(q.get("report_date") or f"{year}_Q{idx}"))
                    accession_suffix = _safe_filename_segment(str(q.get("accession_number") or "").replace("-", ""))
                    stem = f"{ticker}_{year}_10Q_{report_date}_{accession_suffix}_analysis_ready.json"
                    payload_json = json.dumps(payload, indent=2)
                    (company_dir / stem).write_text(payload_json, encoding="utf-8")
                    if _gcs_client:
                        _upload_to_gcs(_gcs_client, gcs_bucket, f"{gcs_prefix}/{ticker}/{stem}", payload_json)  # type: ignore[arg-type]
                    seen.add(accession)
                    processed += 1

        manifest["tickers"][ticker] = sorted(seen)
        _save_manifest(manifest, manifest_local, _gcs_client, gcs_bucket, manifest_blob)
        print(f"ticker={ticker} new={processed} skipped={skipped}")

        summary_rows.append(
            {
                "ticker": ticker,
                "cik": cik,
                "company_name": submissions.get("name"),
                "files_generated": processed,
                "files_skipped": skipped,
            }
        )

    summary = {
        "start_year": start_year,
        "end_year": end_year,
        "include_quarterly": include_quarterly,
        "include_html": include_html,
        "ticker_count": len(tickers),
        "companies": summary_rows,
    }
    summary_json = json.dumps(summary, indent=2)
    (out_dir / "qqq_precompute_summary.json").write_text(summary_json, encoding="utf-8")
    if _gcs_client:
        _upload_to_gcs(_gcs_client, gcs_bucket, f"{gcs_prefix}/qqq_precompute_summary.json", summary_json)  # type: ignore[arg-type]
    return summary


def extract_10k_filing_by_ticker_year(
    *,
    client: EdgarClient,
    ticker: str,
    year: int,
    output_dir: str | Path,
) -> dict[str, Path]:
    company_tickers = client.get_company_tickers()
    cik = ticker_to_cik(company_tickers, ticker)
    submissions = client.get_submissions(cik)
    company_facts = client.get_company_facts(cik)

    tenk_df = extract_recent_10k_filings(submissions, cik=cik, max_filings=30)
    selected = select_10k_for_year(tenk_df, year=year)

    filing_url = build_filing_document_url(
        cik=cik,
        accession_number=str(selected["accession_number"]),
        primary_document=str(selected["primary_document"]),
    )
    filing_text = client.get_text_at_url(filing_url)
    clean_text = html_to_clean_text(filing_text)
    feature_row = build_company_feature_row(cik=cik, submissions=submissions, company_facts=company_facts)
    ixbrl_facts = parse_ixbrl_facts(filing_text)
    ixbrl_feature_history = extract_ixbrl_feature_history(ixbrl_facts=ixbrl_facts)
    companyfacts_feature_history = extract_companyfacts_feature_history(company_facts=company_facts)
    combined_feature_history = combine_feature_histories(
        companyfacts_history=companyfacts_feature_history,
        ixbrl_history=ixbrl_feature_history,
        target_year=year,
    )
    engineered_features = build_engineered_anomaly_features(
        feature_history=combined_feature_history,
        target_year=year,
    )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{ticker.upper()}_{year}_10k"
    metadata_path = out_dir / f"{stem}_metadata.json"
    filing_path = out_dir / f"{stem}_filing.html"
    table_path = out_dir / f"{stem}_candidate_filings.csv"
    analysis_path = out_dir / f"{stem}_analysis_ready.json"

    pd.DataFrame([selected]).to_json(metadata_path, orient="records", indent=2)
    tenk_df.to_csv(table_path, index=False)
    filing_path.write_text(filing_text, encoding="utf-8")
    analysis_payload = {
        "extraction_input": {"ticker": ticker.upper(), "year": year},
        "resolved_company": {
            "cik": cik,
            "company_name": submissions.get("name"),
        },
        "selected_10k_filing": selected,
        "selected_10k_filing_url": filing_url,
        "candidate_10k_filings": _df_records_with_nulls(tenk_df),
        "financial_features_latest": feature_row,
        "companyfacts_feature_history": _df_records_with_nulls(companyfacts_feature_history),
        "ixbrl_facts_stats": {
            "total_facts": int(len(ixbrl_facts)),
            "numeric_facts": int(ixbrl_facts["numeric_value"].notna().sum()) if not ixbrl_facts.empty else 0,
            "contexts": int(ixbrl_facts["context_ref"].nunique()) if not ixbrl_facts.empty else 0,
        },
        "ixbrl_feature_history": _df_records_with_nulls(ixbrl_feature_history),
        "combined_feature_history": _df_records_with_nulls(combined_feature_history),
        "engineered_anomaly_features": engineered_features,
        "filing_text_clean": clean_text,
        "filing_text_stats": {
            "character_count": len(clean_text),
            "word_count": len(clean_text.split()),
            "line_count": clean_text.count("\n") + 1 if clean_text else 0,
        },
    }
    analysis_path.write_text(json.dumps(analysis_payload, indent=2), encoding="utf-8")

    return {
        "metadata_path": metadata_path,
        "filing_path": filing_path,
        "candidate_filings_path": table_path,
        "analysis_ready_path": analysis_path,
    }
