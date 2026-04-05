# CLAUDE.md — QQQ Anomaly Lab

## What this product is

Financial anomaly detection for Nasdaq-100 (QQQ) SEC filings. Users pick a company and period, get an anomaly score, the key financial drivers behind it, and citations back to the source filing.

Core principle: precompute everything offline so the app is fast at request time — no live EDGAR fetch when a user asks a question.

## Memory management rules

**These rules are mandatory — follow them automatically, do not wait to be asked.**

- After any process step is completed (pipeline run, new feature, config change, architecture decision), update the relevant memory file in `~/.claude/projects/-home-sheldongomes-AIProjects-qqq-anomaly-lab-repo/memory/`.
- If a process changes (e.g. how the pipeline runs, where data lives, new GCP resources), update the affected memory file immediately — do not let stale memories accumulate.
- If a new area of work begins that isn't covered by an existing memory file, create one and add it to `MEMORY.md`.
- Memory files live at: `~/.claude/projects/-home-sheldongomes-AIProjects-qqq-anomaly-lab-repo/memory/`

## Backlog tracking rules

**Also mandatory.**

- A running backlog is maintained at `~/.claude/projects/-home-sheldongomes-AIProjects-qqq-anomaly-lab-repo/memory/backlog.md`.
- When a new task or improvement is identified, add it to the backlog immediately.
- When a backlog item is completed, mark it `[x]` and note the date.
- Periodically clean up completed items to keep the backlog readable.
- The backlog is the source of truth for what needs to be done next.

## Key context

- **GCP project:** `qqq-anomaly-lab`
- **GCS bucket:** `gs://qqq-anomaly-raw-sg/qqq/`
- **SEC API email:** `sheldon.gomes@gmail.com` (in `~/.bashrc`)
- **Dataset:** 1,906 JSON files, 101 QQQ tickers, 2021–2026, annual + quarterly
- **Manifest:** `gs://qqq-anomaly-raw-sg/qqq/qqq_manifest.json` — tracks processed accession numbers for incremental re-runs

## How to run the pipeline

```bash
# Full universe refresh (incremental — skips already-processed filings)
SEC_API_EMAIL=sheldon.gomes@gmail.com python3 scripts/precompute_qqq_universe.py \
  --start-year 2021 --end-year 2026 \
  --include-quarterly \
  --gcs-bucket qqq-anomaly-raw-sg \
  --gcs-prefix qqq

# Test run with specific tickers
SEC_API_EMAIL=sheldon.gomes@gmail.com python3 scripts/precompute_qqq_universe.py \
  --start-year 2021 --end-year 2026 \
  --include-quarterly \
  --tickers AAPL,MSFT \
  --gcs-bucket qqq-anomaly-raw-sg \
  --gcs-prefix qqq
```

## Tech stack

- Python 3.11, pandas, scikit-learn, requests, google-cloud-storage
- Data source: SEC EDGAR APIs (submissions, company facts, filing HTML)
- Storage: GCS (raw JSON bundles) → BigQuery (planned, for app queries)
- Anomaly detection: Isolation Forest (baseline)

## What's built vs. what's not

**Built:**
- SEC EDGAR ingestion pipeline with engineered features
- GCS upload integrated into pipeline
- Incremental manifest to skip already-processed filings

**Not built yet (see backlog):**
- Manifest backfill for the initial 101-ticker run
- BigQuery ingestion
- Web app / API layer
- RAG/LLM explanation layer
- Evaluation framework
- Scheduled pipeline refresh
