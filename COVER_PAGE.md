# Code Sample — Cover Page

**Submitted by:** MD Rajibul Islam
**For:** Data Scientist, Research and Analytics Department, Office of the New York State Attorney General
**Reference No.:** RAD_NYC_DAS_6463
**Repository:** https://github.com/<your-handle>/nys-code-sample

---

## What this is

A complete, runnable ETL and analysis pipeline over two public NYC Open Data
datasets: **DCWP Consumer Complaints** (79,287 rows) and **DCWP Charges**
(143,146 rows). It extracts from the Socrata API, validates the data against a
declarative rule set, builds a small SQLite warehouse, and produces a ranked
screening report with uncertainty bounds.

It was written specifically for this application. Everything in it is my own
work on public data — nothing is drawn from my employer's systems.

## Why this problem

The posting describes using data to develop and test legal hypotheses:
acquiring data, testing it for reliability, choosing a methodology,
quantifying uncertainty, and communicating findings with their limitations. I
picked a question that exercises each of those steps rather than one that
showcases volume:

> Do consumer complaints to DCWP end without a decision on the merits at
> materially different rates across business categories, and is a category's
> enforcement footprint proportional to the complaints it generates?

## What it found

- **40.0%** of complaints across 63 analysable categories close for
  administrative reasons — missing information, no response, withdrawal —
  rather than on the merits.
- **Tow truck companies** are the standout: the 3rd-highest complaint volume in
  the city (5,864), a **74.5%** administrative-closure rate (1.87× the
  baseline, 95% CI 73.4–75.6%), and only **2.1** enforcement cases per 100
  complaints. That combination of high volume, high attrition and low
  enforcement is the largest gap in the dataset.
- Of **63,674** businesses with at least one consumer complaint, **5.3%**
  (95% CI 5.2–5.5%) were ever charged by DCWP.

These are screening results, not conclusions. The report says so in its own
header, and the limitations are stated alongside the numbers rather than in a
footnote.

## What I would point a reviewer at

| | |
|---|---|
| `src/dcwp_pipeline/quality.py` | The declarative data-quality framework. Checks are configuration, not scattered assertions. |
| `src/dcwp_pipeline/transform.py` | The outcome taxonomy — the one genuinely substantive modelling judgement, written to be argued with. |
| `src/dcwp_pipeline/analysis.py` | Wilson intervals and why ranking uses the lower bound. |
| `README.md` → *What the quality gate caught* | Three real data defects the pipeline caught on its first run, and what each turned out to be. |
| `sql/02_analysis.sql` | The same questions in SQL, for independent interrogation of the warehouse. |

## Running it

The project is managed with [uv](https://docs.astral.sh/uv/), so a clean clone
needs no Python setup — `make` handles the virtualenv and dependencies.

```bash
git clone https://github.com/<your-handle>/nys-code-sample.git
cd nys-code-sample

make run ROWS=5000   # ~30s, truncated end to end
make run             # ~60s, full extract from the live API
make test            # 20 unit tests
make report          # the findings, then the same questions in SQL
```

No API key required. `uv.lock` is committed, so the dependency graph is
identical to the one these results were produced on.

## Scope and honesty

This is a few days' work, not a production system. It has no orchestration, no
incremental loading, and no CI. The statistical content is deliberately modest:
proportions with interval estimates, and an explicit refusal to make causal
claims the data cannot support. I would rather show a narrow question answered
carefully than a broad one answered loosely.
