# Narrative Pre-Formatting Guide
## From `*_narrative.json` → `*_narrative_ready.json`
**Purpose:** Clean and structure raw SEC narrative text before LLM analysis.
**Scope:** MDA + Risk Factors sections only (V1). Quantitative disclosures excluded.

---

## Why Pre-Formatting Is Necessary

Raw narrative JSON files contain:
- Unicode escape sequences (`\u2019` instead of `'`)
- Boilerplate legal language mixed into substantive content
- Share repurchase tables, exhibit listings, signatures, page numbers
- Risk factor deferrals to annual filings ("no material changes since 10-K")
- Section header artifacts (`Item 2.`, `Item 3.`, page markers like `Apple Inc. | Q3 2021 Form 10-Q | 30`)

Sending raw text to the LLM wastes tokens, increases cost, and reduces signal
quality. Pre-formatting strips noise and flags structural patterns before
analysis — so the LLM focuses on substance, not boilerplate.

---

## Critical Pattern: Risk Factor Deferral

10-Q filings frequently defer risk factors to the most recent 10-K:

> "There have been no material changes to the Company's risk factors
> since the 2020 Form 10-K."

This is NOT silence — it is a deliberate legal statement. It must be detected
and flagged as `risk_factors_deferred: true` rather than treated as empty.
When deferred, the prior 10-K risk factors remain in effect.

This pattern is meaningful for forward-looking analysis:
- First quarter where deferral ends = management felt changes were material enough to re-disclose
- Compare deferral status quarter-over-quarter to detect when management broke the pattern

---

## Input Format

```json
{
  "ticker": "AAPL",
  "year": 2021,
  "form": "10-Q",
  "accession_number": "0000320193-21-000065",
  "filing_date": "2021-07-28",
  "sections": {
    "mda": "raw text...",
    "quantitative_disclosures": "raw text — SKIP",
    "risk_factors": "raw text..."
  }
}
```

---

## Output Format: `*_narrative_ready.json`

```json
{
  "ticker": "AAPL",
  "year": 2021,
  "form": "10-Q",
  "accession_number": "0000320193-21-000065",
  "filing_date": "2021-07-28",
  "period_end_date": "2021-06-26",
  "pre_formatted_at": "ISO timestamp",
  "sections": {
    "mda": {
      "raw_char_count": 4821,
      "cleaned_char_count": 3102,
      "cleaned_text": "cleaned substantive text only",
      "is_empty": false,
      "is_boilerplate_only": false
    },
    "risk_factors": {
      "raw_char_count": 890,
      "cleaned_char_count": 142,
      "cleaned_text": "cleaned text or empty string if fully deferred",
      "is_empty": false,
      "is_deferred_to_annual": true,
      "deferral_reference_year": 2020,
      "deferral_reference_form": "10-K"
    }
  },
  "pre_formatting_flags": {
    "risk_factors_deferred": true,
    "mda_very_short": false,
    "mda_boilerplate_heavy": false,
    "sections_missing": []
  }
}
```

---

## Cleaning Rules

### Universal (apply to all sections)

| Pattern | Action |
|---------|--------|
| Unicode escapes (`\u2019`, `\u201c`, etc.) | Replace with standard characters (`'`, `"`) |
| Page markers (`Apple Inc. \| Q3 2021 Form 10-Q \| 30`) | Remove entirely |
| Section headers (`Item 2.`, `Item 3.`, `PART II`) | Remove |
| Multiple consecutive spaces/newlines | Collapse to single space |
| Trailing/leading whitespace | Strip |

### MDA-Specific

| Pattern | Action |
|---------|--------|
| Share repurchase tables (detected by "Total Number of Shares Purchased") | Remove block |
| Exhibit reference lists ("Exhibit Number Exhibit Description") | Remove block |
| Signature blocks ("Pursuant to the requirements of the Securities Exchange Act") | Remove block |
| Legal certification boilerplate ("disclosure controls and procedures as defined in Rules") | Remove block |
| FSB/sanctions disclosure boilerplate | Remove block |
| Content after "Item 3." heading within MDA | Remove (that's quantitative disclosures) |

### Risk Factors-Specific

| Pattern | Action |
|---------|--------|
| `"There have been no material changes to the Company's risk factors since the [YEAR] Form [FORM]"` | Set `is_deferred_to_annual: true`, extract year and form |
| `"no material changes"` variants | Flag as deferred |
| Content after risk factors section (share repurchase data, Item 2 onwards) | Remove |

---

## Quality Checks

After cleaning, flag these conditions in `pre_formatting_flags`:

| Flag | Condition | Implication |
|------|-----------|-------------|
| `mda_very_short` | cleaned_char_count < 500 | MDA may be missing or failed extraction |
| `mda_boilerplate_heavy` | cleaned < 60% of raw | Lots of noise was stripped — verify manually |
| `risk_factors_deferred` | deferral pattern detected | Use prior 10-K risk factors for comparison |
| `sections_missing` | key missing from JSON | Extraction may have failed for this filing |

---

## What to Skip

- `quantitative_disclosures` — exclude entirely from narrative_ready output
- `business` section — 10-K only, not present in 10-Q
- `financial_statements` section — numbers already captured in analysis_ready.json
- Exhibit listings, signatures, certifications — pure legal noise

---

## File Naming Convention

```
Input:  {TICKER}_{YEAR}_{FORM}_{PERIOD_END_DATE}_narrative.json
Output: {TICKER}_{YEAR}_{FORM}_{PERIOD_END_DATE}_narrative_ready.json
```

Example:
```
Input:  AAPL_2021_10Q_2021-06-26_narrative.json
Output: AAPL_2021_10Q_2021-06-26_narrative_ready.json
```

---

## Storage Location

```
data/processed/qqq_narrative/          ← existing raw narrative files
data/processed/qqq_narrative_ready/    ← new pre-formatted files
    AAPL/
        AAPL_2021_10Q_2021-03-27_narrative_ready.json
        AAPL_2021_10Q_2021-06-26_narrative_ready.json
        ...
    TSLA/
    WBD/
    ...
```

---

## Script Reference

Script to build: `scripts/preformat_narratives.py`
- Input: `data/processed/qqq_narrative/{TICKER}/`
- Output: `data/processed/qqq_narrative_ready/{TICKER}/`
- Runs once offline — not at scoring time
- Idempotent — safe to re-run, overwrites existing ready files
- Logs: print count of files processed, flags raised, deferrals detected
