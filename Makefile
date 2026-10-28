# Every target runs through `uv`, which creates the virtualenv and installs the
# locked dependencies on first use.
UV ?= uv
ROWS ?=

.PHONY: setup run test report

setup:
	$(UV) sync

# make run           full extract from the live API, ~60s
# make run ROWS=5000 truncated run, ~30s, for a quick end-to-end check
run: setup
	$(UV) run nyc-complaints-etl run $(if $(ROWS),--max-rows $(ROWS))

test: setup
	$(UV) run pytest

# The generated findings, then the same questions asked in SQL.
report:
	@test -f reports/findings.md || { echo "Nothing to report yet - run 'make run' first."; exit 1; }
	@cat reports/findings.md
	@echo
	@sqlite3 data/warehouse/dcwp.db < sql/02_analysis.sql
