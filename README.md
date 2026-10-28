# NYC consumer complaints: where cases stop short of a decision

An ETL and analysis pipeline over two public NYC Open Data datasets, built to
answer one narrow question carefully.

> Do consumer complaints to the NYC Department of Consumer and Worker
> Protection (DCWP) end without a decision on the merits at materially
> different rates across business categories, and is a category's enforcement
> footprint proportional to the complaints it generates?

**This repository produces a screening output, not a finding.** Everything it
reports is descriptive. The limitations are stated next to the numbers.

---

## Download

```bash
git clone https://github.com/<your-handle>/nys-code-sample.git
cd nys-code-sample
```

## Requirements

- **[uv](https://docs.astral.sh/uv/)** — handles Python, the virtualenv and
  every dependency. Nothing else needs installing, not even Python itself.
- **sqlite3** — only for `make report`. Ships with macOS and most Linux distros.

```bash
# install uv, if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh     # macOS / Linux
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
```

No API key is required. Set `SOCRATA_APP_TOKEN` to avoid anonymous throttling
on the NYC Open Data API.

## Run it

Four targets. `run` and `test` call `setup` themselves, so on a clean clone
`make run` is enough to see the whole thing work.

```bash
make run ROWS=5000   # truncated end-to-end run   ~30s  ← start here
make run             # full extract, 222k rows    ~60s
make test            # 20 unit tests
make report          # the findings, then the same questions in SQL
```

| Target | What it does |
|---|---|
| `make setup` | `uv sync` — create `.venv`, install locked dependencies |
| `make run` | Full pipeline: extract → validate → transform → warehouse → report. `ROWS=n` caps rows per source, which drops the volume checks to `warn` and leaves every other rule enforced |
| `make test` | `uv run pytest` |
| `make report` | Print `reports/findings.md`, then run `sql/02_analysis.sql` against the warehouse |

Without `make`:

```bash
uv sync
uv run dcwp-pipeline run --max-rows 5000
uv run dcwp-pipeline run
uv run pytest
```

The CLI is a console script, so `uv run dcwp-pipeline --help` lists every
flag, including the ones with no Make target: `--cached` to re-run analysis on
the cached extract without touching the API, `validate` to run the quality gate
on its own, and `--ignore-quality-failures`.

### Outputs

Written to `reports/`:

| File | Contents |
|---|---|
| `findings.md` | The ranked screening report |
| `data_quality.md` | Every check, its threshold and its result |
| `category_profile.csv` | Full per-category table |
| `summary.json` | Headline figures |

The warehouse is written to `data/warehouse/dcwp.db`. To interrogate it
directly: `sqlite3 data/warehouse/dcwp.db < sql/02_analysis.sql`.

---

## Data

| Dataset | ID | Rows | Window |
|---|---|---|---|
| DCWP Consumer Complaints | `nre2-6m2s` | 79,287 | Sep 2022 – Aug 2026 |
| DCWP Charges | `5fn4-dr26` | 143,146 | Jul 2023 – Jul 2026 |

Both are public, require no authentication, and contain business entities
rather than private individuals. They join on `business_unique_id`.

---

## What the quality gate caught

The pipeline refuses to publish analysis on data that fails an
error-severity check. On the first run against live data it stopped, with four
failures. All four were real, and none were fixed by loosening a threshold:

**1. `charges.record_id` had 86,856 duplicates in 143,146 rows.**
`record_id` is the adjudication *case* id (`0001-2026-ADJC`), not a row key —
one case carries a line per charge brought. The grain is `(record_id, charge)`:
143,139 distinct pairs. Deduplicating on `record_id` alone, which is what a
reasonable first guess does, would have silently discarded 60% of the charges
in the dataset and understated enforcement everywhere.
→ Fixed in `clean_charges`; a `unique_composite` check now asserts the real grain.

**2. `charge_count` ran up to 54,681, far outside my assumed `[0, 500]`.**
These are genuine: per-unit and per-day violations against construction
companies and towing operators. The assumption was wrong, not the data.
→ The error bound moved to `[0, 100000]` to catch actual corruption, and a
separate `warn`-level check at 500 still flags unusual magnitude.

**3. `complaints.record_id` had 137 duplicates.**
134 complaint ids appear twice, almost always because one complaint was
recorded against two spellings of the same business — `Paypal Inc` and
`PayPal, Inc.`. It is one complaint.
→ Deduplicated on `record_id`; the check is now `warn` with a headroom
threshold so growth in the rate still raises an alert.

**4. A fourth check tripped on the same `charge_count` assumption** and
resolved with it.

This section exists because it is the honest version of the work. The first
run of a pipeline over unfamiliar public data should fail, and what matters is
whether the failure is investigated or silenced.

---

## Method

### Outcome taxonomy

DCWP records 34 distinct `result` values and they do not mean comparable
things. `Cash Amount - AMT` is a consumer getting money back; `Requested
Information Not Provided` is a case dying because the consumer stopped
replying. Collapsing all 34 into one "resolved" rate produces a number that
looks precise and means nothing.

The four buckets are defined in `transform.py` as readable constants so a
reviewer can disagree with a specific assignment and re-run:

| Bucket | Meaning |
|---|---|
| `relief` | Consumer demonstrably got something — money, refund, cancelled contract, repaired goods |
| `no_relief` | Worked to a substantive conclusion, consumer got nothing, including "advised to sue" |
| `administrative` | Ended on process — missing information, no response, duplicate, withdrawn |
| `out_of_scope` | Referred elsewhere, no jurisdiction, or information only. Excluded from all rate denominators |

A unit test asserts the buckets never overlap, because a result counted in two
buckets would be double-counted silently.

### Uncertainty

Every rate carries a **Wilson score interval**. Ranking uses the interval's
**lower bound**, not the point estimate, so a category reaches the top only
when even a pessimistic reading of its data is high. This is the difference
between surfacing *Tow Truck Company* (5,864 complaints) and surfacing a
category with 11 complaints and a 55% rate.

Wilson rather than the normal approximation: it stays inside `[0, 1]` and
behaves correctly when successes are 0 or equal to trials, both common in the
long tail.

### What is not controlled for

Complaint quality on arrival. How reachable complainants in a category are.
Whether some categories attract more speculative complaints. DCWP casework
priorities and staffing. Being charged is not random, so the charged and
never-charged cohorts in query 4 are self-selected and cannot support a causal
claim. **A high rank is a reason to look closer, nothing more.**

---

## Findings

Full report in `reports/findings.md`.

- **40.0%** of complaints across 63 analysable categories close administratively.
- **Tow Truck Company** is the standout: 3rd-highest complaint volume (5,864),
  **74.5%** administrative closure (1.87× baseline, 95% CI 73.4–75.6%), and
  **2.1** enforcement cases per 100 complaints — the largest gap between
  complaint volume and enforcement in the dataset.
- Lowest administrative closure: **General Vendor** at 3.8%.
- Of **63,674** businesses with a complaint, **5.3%** (95% CI 5.2–5.5%) were
  ever charged.
- Categories with meaningful complaint volume and **zero** enforcement cases:
  Appliances (434), Laundries (414), Temporary Street Fair Vendor Permit (446).

The towing result is the one worth a second look. Towing is already a
recognised consumer-protection problem, the complaint volume is high, and
three-quarters of those complaints never reach a decision either way.

---

## Layout

```
pyproject.toml                project metadata, dependencies, console script
uv.lock                       pinned dependency graph, committed for reproducibility
Makefile                      setup, run, test, report - all through `uv`
config/pipeline.json          datasets + quality rules, as data
src/dcwp_pipeline/
  socrata.py                  paged API reader with retry and backoff
  quality.py                  declarative data-quality framework
  transform.py                cleaning, outcome taxonomy, the business bridge
  analysis.py                 Wilson intervals, category ranking
  pipeline.py                 orchestration
  cli.py                      command-line entry point
sql/01_schema.sql             warehouse indexes
sql/02_analysis.sql           the same questions in SQL
tests/                        20 unit tests
```

### Design notes

- **Checks are configuration, not code.** Every rule the pipeline enforces is
  visible in one JSON file. Adding a rule needs no Python.
- **Severity is a first-class concept.** A 3.2% null rate in an optional join
  key is a warning; a broken primary key is an error that stops the run. Treating
  both the same gets the gate ignored within a month.
- **The pipeline refuses to publish on failed data.** `--ignore-quality-failures`
  exists but has to be typed deliberately.
- **Extracts cache as CSV, not Parquet.** A reviewer can open them in anything.
- **Thresholds are parameters.** `min_complaints_per_category` is a judgement
  call, so it lives in config where it can be changed and re-run.
- **`uv.lock` is committed.** A reviewer running this next month gets the same
  dependency graph I did, which is the difference between a reproducible
  result and a story about one.

---

## Scope

A few days' work, not a production system: no orchestration, no incremental
loading, no CI. The statistical content is deliberately modest — proportions
with interval estimates and an explicit refusal to make causal claims the data
cannot support.

Written for an application to the NYS Office of the Attorney General,
Research and Analytics Department (Ref. RAD_NYC_DAS_6463). Public data only.
