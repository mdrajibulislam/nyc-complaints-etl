-- Analysis queries against data/warehouse/dcwp.db
--   sqlite3 data/warehouse/dcwp.db < sql/02_analysis.sql
--
-- The Python layer writes the ranked report. These are the queries for
-- checking it independently.

.headers on
.mode column

-- 1. Where do complaints die? Outcome mix for the ten busiest categories.
--    `administrative` = closed on process, not on the merits.
SELECT
    business_category,
    COUNT(*)                                                      AS complaints,
    ROUND(100.0 * SUM(outcome_class = 'administrative') / COUNT(*), 1) AS pct_administrative,
    ROUND(100.0 * SUM(outcome_class = 'relief')         / COUNT(*), 1) AS pct_relief,
    ROUND(100.0 * SUM(outcome_class = 'out_of_scope')   / COUNT(*), 1) AS pct_referred_out
FROM complaints
GROUP BY business_category
HAVING complaints >= 500
ORDER BY complaints DESC
LIMIT 10;


-- 2. The enforcement gap: complaint volume against charges actually brought.
--    High on the left, low on the right is the interesting case.
WITH c AS (
    SELECT business_category, COUNT(*) AS complaints
    FROM complaints GROUP BY business_category
),
g AS (
    SELECT business_category,
           COUNT(DISTINCT record_id) AS cases,
           SUM(guilty)               AS counts_guilty
    FROM charges GROUP BY business_category
)
SELECT
    c.business_category,
    c.complaints,
    COALESCE(g.cases, 0)                                           AS enforcement_cases,
    ROUND(100.0 * COALESCE(g.cases, 0) / c.complaints, 1)          AS cases_per_100_complaints,
    COALESCE(g.counts_guilty, 0)                                   AS counts_guilty
FROM c LEFT JOIN g USING (business_category)
WHERE c.complaints >= 300
ORDER BY cases_per_100_complaints ASC
LIMIT 15;


-- 3. Businesses with repeat complaints that were never charged. The
--    administrative share is how many never reached a decision either way.
SELECT
    business_name,
    business_category,
    complaints,
    administrative,
    ROUND(100.0 * administrative / complaints, 1) AS pct_administrative
FROM business_bridge
WHERE ever_charged = 0
  AND complaints >= 10
ORDER BY complaints DESC
LIMIT 20;


-- 4. Do charged businesses see different complaint outcomes than uncharged
--    ones? Descriptive only - being charged isn't random, so these are two
--    self-selected groups and no causal claim follows.
SELECT
    CASE ever_charged WHEN 1 THEN 'charged' ELSE 'never charged' END AS cohort,
    COUNT(*)                                            AS businesses,
    SUM(complaints)                                     AS complaints,
    ROUND(1.0 * SUM(complaints) / COUNT(*), 2)          AS complaints_per_business,
    ROUND(100.0 * SUM(relief) / SUM(complaints), 1)     AS pct_relief,
    ROUND(100.0 * SUM(administrative) / SUM(complaints), 1) AS pct_administrative
FROM business_bridge
GROUP BY ever_charged;


-- 5. Adjudication outcomes by severity of the case (counts charged).
SELECT
    CASE
        WHEN charge_count = 1              THEN '1 count'
        WHEN charge_count BETWEEN 2 AND 5  THEN '2-5 counts'
        WHEN charge_count BETWEEN 6 AND 50 THEN '6-50 counts'
        ELSE '50+ counts'
    END                                        AS case_size,
    COUNT(*)                                   AS charge_lines,
    ROUND(100.0 * SUM(is_adverse) / COUNT(*), 1) AS pct_adverse_to_business,
    SUM(guilty)                                AS counts_guilty
FROM charges
GROUP BY case_size
ORDER BY charge_lines DESC;
