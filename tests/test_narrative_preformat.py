from __future__ import annotations

from tenk_anomaly.narrative_preformat import preformat_narrative

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(mda: str = "", risk_factors: str = "", form: str = "10-Q") -> dict:
    return {
        "ticker": "AAPL",
        "year": 2021,
        "form": form,
        "accession_number": "0000320193-21-000065",
        "filing_date": "2021-07-28",
        "report_date": "2021-06-26",
        "sections": {"mda": mda, "risk_factors": risk_factors},
    }


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

def test_output_has_required_top_level_keys():
    out = preformat_narrative(_make_payload("some mda text", "some risk text"))
    for key in ("ticker", "year", "form", "accession_number", "filing_date",
                "period_end_date", "pre_formatted_at", "sections", "pre_formatting_flags"):
        assert key in out


def test_period_end_date_comes_from_report_date():
    out = preformat_narrative(_make_payload("mda", "risks"))
    assert out["period_end_date"] == "2021-06-26"


def test_sections_contains_only_mda_and_risk_factors():
    out = preformat_narrative(_make_payload("mda", "risks"))
    assert set(out["sections"].keys()) == {"mda", "risk_factors"}


def test_quantitative_disclosures_excluded():
    payload = _make_payload("mda", "risks")
    payload["sections"]["quantitative_disclosures"] = "some quant text"
    out = preformat_narrative(payload)
    assert "quantitative_disclosures" not in out["sections"]


# ---------------------------------------------------------------------------
# Unicode normalisation
# ---------------------------------------------------------------------------

def test_unicode_curly_quotes_normalised():
    out = preformat_narrative(_make_payload(mda="\u2018hello\u2019 and \u201cworld\u201d"))
    assert "\u2018" not in out["sections"]["mda"]["cleaned_text"]
    assert "\u2019" not in out["sections"]["mda"]["cleaned_text"]
    assert "hello" in out["sections"]["mda"]["cleaned_text"]


def test_non_breaking_space_replaced():
    out = preformat_narrative(_make_payload(mda="revenue\u00a0growth"))
    assert "\u00a0" not in out["sections"]["mda"]["cleaned_text"]


# ---------------------------------------------------------------------------
# MDA cleaning
# ---------------------------------------------------------------------------

def test_mda_share_repurchase_block_removed():
    mda = "Revenue grew 10 percent.\n\nTotal Number of Shares Purchased\n100,000 shares at $150\n\nMore content."
    out = preformat_narrative(_make_payload(mda=mda))
    assert "Total Number of Shares Purchased" not in out["sections"]["mda"]["cleaned_text"]
    assert "Revenue grew" in out["sections"]["mda"]["cleaned_text"]


def test_mda_signature_block_removed():
    mda = "Good results.\n\nPursuant to the requirements of the Securities Exchange Act\nSigned: CEO\n"
    out = preformat_narrative(_make_payload(mda=mda))
    assert "Pursuant to the requirements" not in out["sections"]["mda"]["cleaned_text"]


def test_mda_truncated_at_item3():
    mda = "Revenue discussion here.\n\nItem 3. Quantitative Disclosures\nInterest rate risk..."
    out = preformat_narrative(_make_payload(mda=mda))
    assert "Quantitative Disclosures" not in out["sections"]["mda"]["cleaned_text"]
    assert "Revenue discussion" in out["sections"]["mda"]["cleaned_text"]


def test_mda_char_counts_recorded():
    mda = "A" * 1000
    out = preformat_narrative(_make_payload(mda=mda))
    assert out["sections"]["mda"]["raw_char_count"] == 1000
    assert out["sections"]["mda"]["cleaned_char_count"] > 0


# ---------------------------------------------------------------------------
# Risk factor deferral detection
# ---------------------------------------------------------------------------

def test_deferral_detected_no_material_changes():
    rf = ("The Company's risk factors can be affected by many issues, "
          "including but not limited to those described in Part I, Item 1A "
          "of the 2020 Form 10-K under the heading Risk Factors.")
    out = preformat_narrative(_make_payload(risk_factors=rf))
    assert out["sections"]["risk_factors"]["is_deferred_to_annual"] is True
    assert out["sections"]["risk_factors"]["deferral_reference_year"] == 2020
    assert out["sections"]["risk_factors"]["deferral_reference_form"] == "10-K"
    assert out["pre_formatting_flags"]["risk_factors_deferred"] is True


def test_deferral_detected_explicit_no_changes():
    rf = "There have been no material changes to the Company's risk factors since the 2022 Form 10-K."
    out = preformat_narrative(_make_payload(risk_factors=rf))
    assert out["sections"]["risk_factors"]["is_deferred_to_annual"] is True
    assert out["sections"]["risk_factors"]["deferral_reference_year"] == 2022


def test_deferred_cleaned_text_is_empty():
    rf = "There have been no material changes since the 2021 Form 10-K."
    out = preformat_narrative(_make_payload(risk_factors=rf))
    assert out["sections"]["risk_factors"]["cleaned_text"] == ""


def test_non_deferred_risk_factors_not_flagged():
    rf = ("The Company faces risks from competition, regulatory changes, "
          "and macroeconomic conditions that could materially affect results.")
    out = preformat_narrative(_make_payload(risk_factors=rf))
    assert out["sections"]["risk_factors"]["is_deferred_to_annual"] is False
    assert out["pre_formatting_flags"]["risk_factors_deferred"] is False


# ---------------------------------------------------------------------------
# Quality flags
# ---------------------------------------------------------------------------

def test_mda_very_short_flag():
    out = preformat_narrative(_make_payload(mda="Short."))
    assert out["pre_formatting_flags"]["mda_very_short"] is True


def test_mda_not_short_flag():
    out = preformat_narrative(_make_payload(mda="x" * 600))
    assert out["pre_formatting_flags"]["mda_very_short"] is False


def test_sections_missing_flag_when_mda_absent():
    payload = _make_payload()
    payload["sections"] = {}  # no sections at all
    out = preformat_narrative(payload)
    assert "mda" in out["pre_formatting_flags"]["sections_missing"]
    assert "risk_factors" in out["pre_formatting_flags"]["sections_missing"]


def test_mda_boilerplate_heavy_flag():
    # Most of the MDA is boilerplate that gets stripped
    boilerplate = "\n\nPursuant to the requirements of the Securities Exchange Act\n" * 10
    real = "Revenue grew 12 percent year over year."
    out = preformat_narrative(_make_payload(mda=real + boilerplate))
    assert out["pre_formatting_flags"]["mda_boilerplate_heavy"] is True
