-- Indexes go here, not in the table DDL: to_sql replaces the table on every
-- load, so the loader re-applies them afterwards.
DROP INDEX IF EXISTS idx_complaints_business;
DROP INDEX IF EXISTS idx_charges_business;
DROP INDEX IF EXISTS idx_bridge_business;
