# 10k-anomaly Project Goal

## Core goal

Build a practical, cost-efficient financial anomaly detection product that helps users identify unusual patterns in public company filings, starting with the Nasdaq-100 universe.

## Product vision

Create a web app where a user selects a company and period, and instantly receives:

- an anomaly score
- the key financial drivers behind that score
- transparent filing references for trust and auditability

The user experience should be fast and reliable because core data is precomputed in advance.

## v1 scope (what we are building now)

- Universe: Nasdaq-100 / QQQ constituents (bounded, high-value set)
- History: last 5 years (annual and quarterly filings)
- Source data:
  - SEC filing metadata (10-K, 10-Q)
  - SEC companyfacts historical series
  - filing-linked structured outputs
- Output format: precomputed per-company JSON bundles in `data/processed/qqq_full`
- Detection basis:
  - engineered accounting and growth features
  - unsupervised anomaly scoring

## Why this approach

- Keeps cost low by avoiding live heavy ingestion per user request
- Improves app speed with preloaded data
- Preserves robustness with SEC source-of-truth data
- Gives a clear product scope that can be communicated simply

## What success looks like (v1)

- Data pipeline reliably refreshes QQQ dataset on schedule
- App can return anomaly insights for supported companies quickly
- Results are explainable (feature-level reasons, not black-box only)
- RAG-assisted explanations are grounded in SEC filings and accounting references, with clear source-backed rationale for flagged anomalies
- Every RAG explanation includes citations to the underlying SEC filing sections and reference material used
- Anomaly scores remain model/data-driven, with RAG used for interpretation and context only
- At least 80% of reviewed RAG explanations are rated accurate and useful in internal quality checks
- Product development follows an evals-first approach: new features, prompts, and model changes must pass predefined evaluation thresholds before release
- The system supports periodic expansion without redesign

## Evals Framework (v1)

- Evals are required both pre-release and at inference time for displayed anomaly results
- User-facing anomaly views include eval outputs (confidence, data coverage, citation quality, and recent model quality status)
- Minimum release gates:
  - explanation quality: >= 80% rated accurate/useful in internal review
  - citation quality: 100% of displayed explanations include source references
  - anomaly stability: top-ranked anomaly set remains meaningfully consistent across adjacent refresh runs
- Any model/prompt/data change that fails eval thresholds is blocked from production release


## Non-goals for v1

- Full-market coverage beyond QQQ
- expensive image/chart OCR workflows
- heavy real-time external news fusion at request time

## Guiding principle

Prioritize robust, explainable, and cost-aware anomaly detection over broad but noisy feature scope.
