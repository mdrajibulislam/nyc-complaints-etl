# Every target runs through `uv`, which creates the virtualenv and installs
# the locked dependencies on first use. There is no separate install step.
UV ?= uv

.PHONY: help install smoke run cached validate test sql clean distclean

help:
	@echo "make install  - create .venv and install locked dependencies"
	@echo "make smoke    - 5,000 rows per source, end to end  (~30s)"
	@echo "make run      - full extract from the live API      (~60s)"
	@echo "make cached   - re-run transforms/analysis on the cached extract"
	@echo "make validate - extract and run the quality gate only"
	@echo "make test     - unit tests"
	@echo "make sql      - run sql/02_analysis.sql against the warehouse"
	@echo "make clean    - remove cached data, warehouse and reports"

install:
	$(UV) sync

smoke: install
	$(UV) run dcwp-pipeline run --max-rows 5000

run: install
	$(UV) run dcwp-pipeline run

cached: install
	$(UV) run dcwp-pipeline run --cached

validate: install
	$(UV) run dcwp-pipeline validate

test: install
	$(UV) run pytest

sql:
	@test -f data/warehouse/dcwp.db || { echo "No warehouse yet - run 'make run' first."; exit 1; }
	sqlite3 data/warehouse/dcwp.db < sql/02_analysis.sql

clean:
	rm -f data/raw/*.csv data/warehouse/*.db reports/*

distclean: clean
	rm -rf .venv .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
