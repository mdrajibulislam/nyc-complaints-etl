# Data quality report

Generated: 2026-10-28T02:37:49+00:00

- Checks run: **18**
- Errors: **0**
- Warnings: **0**
- Verdict: **PASS**

| Table | Check | Column | Severity | Result | Observed | Threshold |
|---|---|---|---|---|---|---|
| complaints | row_count_min | - | error | pass | 79287 | 50000 |
| complaints | unique | record_id | warn | pass | 137 | 300 |
| complaints | not_null | record_id | error | pass | 0.0 | 0.0 |
| complaints | not_null | intake_date | error | pass | 0.0 | 0.01 |
| complaints | not_null | business_unique_id | warn | pass | 0.032 | 0.05 |
| complaints | not_null | business_category | warn | pass | 0.0176 | 0.02 |
| complaints | date_not_future | intake_date | error | pass | 0.0 | 0.0 |
| complaints | date_not_future | result_date | warn | pass | 0.0 | 0.0 |
| charges | row_count_min | - | error | pass | 143146 | 100000 |
| charges | unique_composite | record_id + charge | error | pass | 7 | 20 |
| charges | not_null | record_id | error | pass | 0.0 | 0.0 |
| charges | not_null | business_unique_id | error | pass | 0.0 | 0.0 |
| charges | numeric_range | charge_count | error | pass | 0.0 | 0.0 |
| charges | numeric_range | charge_count | warn | pass | 0.0004 | 0.01 |
| charges | numeric_range | guilty | error | pass | 0.0 | 0.0 |
| charges | referential_integrity | business_unique_id | warn | pass | 0.8208 | 1.0 |
| charges | accepted_values | outcome | warn | pass | 0.0 | 0.0 |
| charges | date_not_future | violation_date | warn | pass | 0.0 | 0.0 |
