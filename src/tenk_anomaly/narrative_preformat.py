"""Pre-format raw narrative JSON files into analysis-ready format.

Implements the cleaning and structuring rules defined in narrative-preformat-guide.md.
Processes MDA and risk_factors sections only. Outputs *_narrative_ready.json.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Unicode normalisation
# ---------------------------------------------------------------------------

_UNICODE_MAP = str.maketrans({
    "\u2018": "'",    # left single quote
    "\u2019": "'",    # right single quote
    "\u201c": '"',    # left double quote
    "\u201d": '"',    # right double quote
    "\u2013": "-",    # en dash
    "\u2014": "-",    # em dash
    "\u00a0": " ",    # non-breaking space
    "\u2022": "-",    # bullet
    "\u2026": "...",  # ellipsis
    "\u00ae": "",     # registered trademark
    "\u2122": "",     # trademark symbol
    "\u00b7": "-",    # middle dot
})

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Page markers: "Apple Inc. | Q3 2021 Form 10-Q | 30"
_PAGE_MARKER_RE = re.compile(
    r"[A-Za-z][^\|\n]{2,60}\|\s*[^\|\n]{5,80}\|\s*\d{1,3}\s*",
)

# Standalone section headers: "Item 2.", "Item 1A.", "PART II"
_SECTION_HEADER_RE = re.compile(
    r"(?:^|\n)\s*(?:PART\s+[IVX]+\.?|Item\s+\d+[A-Za-z]?\.?)\s*(?:\n|$)",
    re.IGNORECASE,
)

# Item 3 heading within MDA — everything from here onward is quantitative disclosures
_ITEM3_IN_MDA_RE = re.compile(r"\bItem\s+3[\.\s]", re.IGNORECASE)

# Boilerplate triggers — when found, remove from start of its paragraph to next blank line
_MDA_BOILERPLATE_TRIGGERS = [
    "Total Number of Shares Purchased",
    "Exhibit Number",
    "Exhibit Description",
    "Pursuant to the requirements of the Securities Exchange Act",
    "disclosure controls and procedures as defined in Rules",
    "sanctions disclosure",
    "Foreign Assets Control",
]

# Deferral patterns for risk factors — ordered most-specific first
_DEFERRAL_PATTERNS = [
    # "no material changes to/in [the company's] risk factors since ... [YEAR] Form 10-K"
    re.compile(
        r"no\s+material\s+changes?\s+(?:to|in)\s+(?:the\s+)?(?:\w+.s\s+)?risk\s+factors?"
        r"(?:[^.]{0,250}?(\d{4})\s+Form\s+(10-[KQ]))?",
        re.IGNORECASE,
    ),
    # "described/discussed in Part I, Item 1A of the 2020 Form 10-K"
    re.compile(
        r"(?:described|discussed|set\s+forth|included)\s+in\s+(?:Part\s+[IVX]+,?\s+)?Item\s+1A"
        r"[^.]{0,150}?(\d{4})\s+Form\s+(10-[KQ])",
        re.IGNORECASE,
    ),
    # "there have been no material changes"
    re.compile(
        r"there\s+(?:have\s+been|has\s+been|are)\s+no\s+material\s+changes?"
        r"(?:[^.]{0,250}?(\d{4})\s+Form\s+(10-[KQ]))?",
        re.IGNORECASE,
    ),
]

# ---------------------------------------------------------------------------
# Universal cleaning helpers
# ---------------------------------------------------------------------------

def _normalize_unicode(text: str) -> str:
    return text.translate(_UNICODE_MAP)


def _remove_page_markers(text: str) -> str:
    return _PAGE_MARKER_RE.sub(" ", text)


def _remove_section_headers(text: str) -> str:
    return _SECTION_HEADER_RE.sub("\n", text)


def _collapse_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _remove_boilerplate_block(text: str, trigger: str) -> str:
    """Find trigger phrase and remove its surrounding paragraph block."""
    idx = text.lower().find(trigger.lower())
    if idx == -1:
        return text
    para_start = text.rfind("\n\n", 0, idx)
    para_start = para_start + 2 if para_start != -1 else 0
    para_end = text.find("\n\n", idx)
    para_end = para_end if para_end != -1 else len(text)
    return text[:para_start] + text[para_end:]


# ---------------------------------------------------------------------------
# MDA cleaning
# ---------------------------------------------------------------------------

def _clean_mda(raw: str) -> str:
    text = _normalize_unicode(raw)
    text = _remove_page_markers(text)
    text = _remove_section_headers(text)
    for trigger in _MDA_BOILERPLATE_TRIGGERS:
        while trigger.lower() in text.lower():
            new_text = _remove_boilerplate_block(text, trigger)
            if new_text == text:
                break
            text = new_text
    # Truncate at Item 3 (quantitative disclosures bleeds into MDA)
    m = _ITEM3_IN_MDA_RE.search(text)
    if m:
        text = text[:m.start()]
    return _collapse_whitespace(text)


# ---------------------------------------------------------------------------
# Risk factors cleaning + deferral detection
# ---------------------------------------------------------------------------

def _detect_deferral(raw: str) -> tuple[bool, int | None, str | None]:
    """Returns (is_deferred, reference_year, reference_form)."""
    for pattern in _DEFERRAL_PATTERNS:
        m = pattern.search(raw)
        if m:
            groups = [g for g in m.groups() if g is not None]
            year = int(groups[0]) if len(groups) >= 1 else None
            form = groups[1].upper().replace(" ", "") if len(groups) >= 2 else None
            # Normalise form: "10K" → "10-K"
            if form and "-" not in form:
                form = form[:2] + "-" + form[2:]
            return True, year, form
    return False, None, None


def _clean_risk_factors(raw: str) -> tuple[str, bool, int | None, str | None]:
    """Returns (cleaned_text, is_deferred, deferral_year, deferral_form)."""
    is_deferred, year, form = _detect_deferral(raw)
    text = _normalize_unicode(raw)
    text = _remove_page_markers(text)
    text = _remove_section_headers(text)
    text = _collapse_whitespace(text)
    return text, is_deferred, year, form


# ---------------------------------------------------------------------------
# Main pre-formatting function
# ---------------------------------------------------------------------------

def preformat_narrative(payload: dict[str, Any]) -> dict[str, Any]:
    """Transform a raw *_narrative.json payload into *_narrative_ready.json format.

    Only MDA and risk_factors sections are processed. All other sections are excluded.
    """
    sections_raw = payload.get("sections", {})

    # --- MDA ---
    mda_raw = sections_raw.get("mda", "")
    mda_cleaned = _clean_mda(mda_raw) if mda_raw else ""
    mda_section: dict[str, Any] = {
        "raw_char_count": len(mda_raw),
        "cleaned_char_count": len(mda_cleaned),
        "cleaned_text": mda_cleaned,
        "is_empty": len(mda_cleaned) == 0,
        "is_boilerplate_only": len(mda_raw) > 0 and len(mda_cleaned) == 0,
    }

    # --- Risk factors ---
    rf_raw = sections_raw.get("risk_factors", "")
    rf_cleaned, is_deferred, defer_year, defer_form = (
        _clean_risk_factors(rf_raw) if rf_raw else ("", False, None, None)
    )
    rf_section: dict[str, Any] = {
        "raw_char_count": len(rf_raw),
        "cleaned_char_count": len(rf_cleaned),
        "cleaned_text": rf_cleaned if not is_deferred else "",
        "is_empty": len(rf_raw) == 0,
        "is_deferred_to_annual": is_deferred,
    }
    if is_deferred:
        rf_section["deferral_reference_year"] = defer_year
        rf_section["deferral_reference_form"] = defer_form

    # --- Quality flags ---
    sections_missing = []
    for key in ("mda", "risk_factors"):
        if key not in sections_raw or not sections_raw[key]:
            sections_missing.append(key)

    flags: dict[str, Any] = {
        "risk_factors_deferred": is_deferred,
        "mda_very_short": mda_section["cleaned_char_count"] < 500,
        "mda_boilerplate_heavy": (
            mda_section["raw_char_count"] > 0
            and mda_section["cleaned_char_count"] < 0.6 * mda_section["raw_char_count"]
        ),
        "sections_missing": sections_missing,
    }

    return {
        "ticker": payload.get("ticker"),
        "year": payload.get("year"),
        "form": payload.get("form"),
        "accession_number": payload.get("accession_number"),
        "filing_date": payload.get("filing_date"),
        "period_end_date": payload.get("report_date"),
        "pre_formatted_at": datetime.now(timezone.utc).isoformat(),
        "sections": {
            "mda": mda_section,
            "risk_factors": rf_section,
        },
        "pre_formatting_flags": flags,
    }
