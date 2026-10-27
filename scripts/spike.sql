-- Day-0 spike (docs/spike-checklist.md). Run in Databricks SQL Editor with "Run all".
-- Prerequisite: group `gov-spike` exists and you are a member.
-- Everything lives in catalog gov_spike; drop it at the end (last statement).

-- #4 Can we create a catalog on default storage?
CREATE CATALOG IF NOT EXISTS gov_spike;
CREATE SCHEMA IF NOT EXISTS gov_spike.governance;

-- #1 Is the workspace group usable in Unity Catalog grants?
GRANT USE CATALOG ON CATALOG gov_spike TO `gov-spike`;

-- #5 Which system schemas are enabled?
SHOW SCHEMAS IN system;
SELECT 'audit' AS source, count(*) AS rows FROM system.access.audit WHERE event_date >= current_date() - 7
UNION ALL SELECT 'table_lineage', count(*) FROM system.access.table_lineage
UNION ALL SELECT 'column_lineage', count(*) FROM system.access.column_lineage;

-- #6 Are masks, filters and tags exposed in information_schema?
SHOW TABLES IN system.information_schema LIKE '*mask*|*filter*|*tag*|*privilege*';

-- #7 Row filter backed by a mapping-table subquery
CREATE OR REPLACE TABLE gov_spike.governance.region_access (group_name STRING, value STRING);
INSERT OVERWRITE gov_spike.governance.region_access VALUES ('gov-spike', 'AMER');

CREATE OR REPLACE FUNCTION gov_spike.governance.filter_region(row_value STRING)
RETURNS BOOLEAN
RETURN EXISTS (SELECT 1 FROM gov_spike.governance.region_access a
               WHERE a.value = row_value AND is_account_group_member(a.group_name));

-- Column mask that calls another function (the can_see pattern)
CREATE OR REPLACE FUNCTION gov_spike.governance.can_see(level STRING)
RETURNS BOOLEAN
RETURN CASE level WHEN 'confidential' THEN is_account_group_member('gov-spike-pii') ELSE FALSE END;

CREATE OR REPLACE FUNCTION gov_spike.governance.mask_email(v STRING)
RETURNS STRING
RETURN CASE WHEN gov_spike.governance.can_see('confidential') THEN v
  ELSE regexp_replace(v, '^(.)[^@]*', '$1***') END;

CREATE OR REPLACE TABLE gov_spike.governance.customers (id INT, email STRING, region STRING);
INSERT INTO gov_spike.governance.customers VALUES
  (1, 'ana@example.com', 'AMER'),
  (2, 'bob@example.com', 'EMEA');

ALTER TABLE gov_spike.governance.customers SET ROW FILTER gov_spike.governance.filter_region ON (region);
ALTER TABLE gov_spike.governance.customers ALTER COLUMN email SET MASK gov_spike.governance.mask_email;
ALTER TABLE gov_spike.governance.customers ALTER COLUMN email SET TAGS ('pii_type' = 'email');

-- EXPECTED: exactly 1 row (AMER), email shown as a***@example.com
SELECT * FROM gov_spike.governance.customers;

-- #6 again: do the policies show up in information_schema?
SELECT 'column_masks' AS view, count(*) AS rows FROM system.information_schema.column_masks WHERE table_catalog = 'gov_spike'
UNION ALL SELECT 'row_filters', count(*) FROM system.information_schema.row_filters WHERE table_catalog = 'gov_spike'
UNION ALL SELECT 'column_tags', count(*) FROM system.information_schema.column_tags WHERE catalog_name = 'gov_spike';

-- Cleanup: run separately AFTER sharing results
-- DROP CATALOG gov_spike CASCADE;
