PY ?= python3
export PYTHONPATH := src

.PHONY: help smoke run cached test clean

help:
	@echo "make smoke   - 5k rows per source, end to end (~30s)"
	@echo "make run     - full pipeline against the live API (~2-3 min)"
	@echo "make cached  - rerun transforms/analysis on the cached extract"
	@echo "make test    - unit tests"
	@echo "make clean   - remove cached data, warehouse and reports"

smoke:
	$(PY) -m dcwp_pipeline run --max-rows 5000

run:
	$(PY) -m dcwp_pipeline run

cached:
	$(PY) -m dcwp_pipeline run --cached

test:
	$(PY) -m pytest -q

clean:
	rm -f data/raw/*.csv data/warehouse/*.db reports/*
