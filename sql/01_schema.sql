-- Indexes are created after pandas writes each table (to_sql replaces the
-- table itself, so indexes are declared here and applied by the loader).
DROP INDEX IF EXISTS idx_complaints_business;
DROP INDEX IF EXISTS idx_charges_business;
DROP INDEX IF EXISTS idx_bridge_business;
