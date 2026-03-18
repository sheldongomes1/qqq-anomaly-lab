.PHONY: install test lint run extract-10k precompute-qqq

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -U pip && pip install -e ".[dev]"

test:
	. .venv/bin/activate && pytest

lint:
	. .venv/bin/activate && ruff check src tests scripts

run:
	. .venv/bin/activate && python scripts/train_baseline.py

extract-10k:
	. .venv/bin/activate && python scripts/extract_10k_by_ticker_year.py --ticker GOOG --year 2025

precompute-qqq:
	. .venv/bin/activate && python scripts/precompute_qqq_universe.py --start-year 2021 --end-year 2025 --include-quarterly
