
-- ===== reference_data =====
CREATE TABLE IF NOT EXISTS gov_prod.governance.region_access (group_name STRING NOT NULL, value STRING NOT NULL) COMMENT 'Group to region mapping for row filter region. Managed by gov_engine - do not edit by hand';
INSERT OVERWRITE gov_prod.governance.region_access VALUES
  ('gov-analysts-amer', 'AMER'),
  ('gov-analysts-emea', 'EMEA'),
  ('gov-pii-readers', 'AMER'),
  ('gov-pii-readers', 'APAC'),
  ('gov-pii-readers', 'EMEA');

-- ===== functions =====
CREATE OR REPLACE FUNCTION gov_prod.governance.can_see(level STRING)
RETURNS BOOLEAN
COMMENT 'True if the current user may see unmasked values at this level. Managed by gov_engine - do not edit by hand'
RETURN CASE level
    WHEN 'public' THEN TRUE
    WHEN 'internal' THEN TRUE
    WHEN 'confidential' THEN is_account_group_member('gov-pii-readers') OR is_account_group_member('gov-pii-restricted-readers')
    WHEN 'restricted' THEN is_account_group_member('gov-pii-restricted-readers')
    ELSE FALSE
  END;
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_person_name(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=person_name (confidential, initial_only). Managed by gov_engine - do not edit by hand'
RETURN CASE WHEN gov_prod.governance.can_see('confidential') THEN v
  ELSE concat(left(v, 1), '.') END;
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_email(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=email (confidential, partial_email). Managed by gov_engine - do not edit by hand'
RETURN CASE WHEN gov_prod.governance.can_see('confidential') THEN v
  ELSE regexp_replace(v, '^(.)[^@]*', '$1***') END;
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_phone(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=phone (confidential, last4). Managed by gov_engine - do not edit by hand'
RETURN CASE WHEN gov_prod.governance.can_see('confidential') THEN v
  ELSE concat(repeat('*', greatest(length(v) - 4, 0)), right(v, 4)) END;
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_street_address(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=street_address (confidential, redact). Managed by gov_engine - do not edit by hand'
RETURN CASE WHEN gov_prod.governance.can_see('confidential') THEN v
  ELSE '***REDACTED***' END;
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_date_of_birth(v DATE)
RETURNS DATE
COMMENT 'Mask for pii_type=date_of_birth (confidential, year_only). Managed by gov_engine - do not edit by hand'
RETURN CASE WHEN gov_prod.governance.can_see('confidential') THEN v
  ELSE make_date(year(v), 1, 1) END;
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_national_id(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=national_id (restricted, sha256). Managed by gov_engine - do not edit by hand'
RETURN CASE WHEN gov_prod.governance.can_see('restricted') THEN v
  ELSE sha2(v, 256) END;
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_card_number(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=card_number (restricted, last4). Managed by gov_engine - do not edit by hand'
RETURN CASE WHEN gov_prod.governance.can_see('restricted') THEN v
  ELSE concat(repeat('*', greatest(length(v) - 4, 0)), right(v, 4)) END;
CREATE OR REPLACE FUNCTION gov_prod.governance.filter_region(row_value STRING)
RETURNS BOOLEAN
COMMENT 'Row filter on region, backed by region_access. Managed by gov_engine - do not edit by hand'
RETURN is_account_group_member('gov-platform-admins')
  OR is_account_group_member('gov-data-engineers')
  OR is_account_group_member('gov-pii-restricted-readers')
  OR is_account_group_member('gov-customer-stewards')
  OR is_account_group_member('gov-sales-stewards')
  OR EXISTS (SELECT 1 FROM gov_prod.governance.region_access a WHERE a.value = row_value AND is_account_group_member(a.group_name));

-- ===== grants =====
GRANT USE CATALOG ON CATALOG gov_prod TO `gov-analysts-amer`;
GRANT USE CATALOG ON CATALOG gov_prod TO `gov-analysts-emea`;
GRANT USE CATALOG ON CATALOG gov_prod TO `gov-auditors`;
GRANT USE CATALOG ON CATALOG gov_prod TO `gov-customer-stewards`;
GRANT USE CATALOG ON CATALOG gov_prod TO `gov-data-engineers`;
GRANT USE CATALOG ON CATALOG gov_prod TO `gov-pii-readers`;
GRANT USE CATALOG ON CATALOG gov_prod TO `gov-pii-restricted-readers`;
GRANT USE CATALOG, USE SCHEMA, SELECT, MODIFY, CREATE TABLE, CREATE FUNCTION, APPLY TAG ON CATALOG gov_prod TO `gov-platform-admins`;
GRANT USE CATALOG ON CATALOG gov_prod TO `gov-sales-stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.audit TO `gov-auditors`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_bronze TO `gov-data-engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_gold TO `gov-analysts-amer`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_gold TO `gov-analysts-emea`;
GRANT USE SCHEMA, SELECT, APPLY TAG ON SCHEMA gov_prod.customer_gold TO `gov-customer-stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_gold TO `gov-data-engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_gold TO `gov-pii-readers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_gold TO `gov-pii-restricted-readers`;
GRANT USE SCHEMA, SELECT, APPLY TAG ON SCHEMA gov_prod.customer_silver TO `gov-customer-stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_silver TO `gov-data-engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_silver TO `gov-pii-readers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_silver TO `gov-pii-restricted-readers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_bronze TO `gov-data-engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_gold TO `gov-analysts-amer`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_gold TO `gov-analysts-emea`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_gold TO `gov-data-engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_gold TO `gov-pii-readers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_gold TO `gov-pii-restricted-readers`;
GRANT USE SCHEMA, SELECT, APPLY TAG ON SCHEMA gov_prod.sales_gold TO `gov-sales-stewards`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_silver TO `gov-data-engineers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_silver TO `gov-pii-readers`;
GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.sales_silver TO `gov-pii-restricted-readers`;
GRANT USE SCHEMA, SELECT, APPLY TAG ON SCHEMA gov_prod.sales_silver TO `gov-sales-stewards`;

-- ===== tags =====
ALTER TABLE gov_prod.customer_gold.customer_360 SET TAGS ('classification' = 'confidential', 'domain' = 'customer', 'layer' = 'gold', 'owner' = 'gov-customer-stewards', 'data_contract' = 'customer.customer_360');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `customer_id` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `full_name` SET TAGS ('classification' = 'confidential', 'pii_type' = 'person_name');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `email` SET TAGS ('classification' = 'confidential', 'pii_type' = 'email');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `region` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `order_count` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `lifetime_value` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `last_order_ts` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_silver.customers SET TAGS ('classification' = 'restricted', 'domain' = 'customer', 'layer' = 'silver', 'owner' = 'gov-customer-stewards', 'data_contract' = 'customer.customers');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `customer_id` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `full_name` SET TAGS ('classification' = 'confidential', 'pii_type' = 'person_name');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `email` SET TAGS ('classification' = 'confidential', 'pii_type' = 'email');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `phone` SET TAGS ('classification' = 'confidential', 'pii_type' = 'phone');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `date_of_birth` SET TAGS ('classification' = 'confidential', 'pii_type' = 'date_of_birth');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `national_id` SET TAGS ('classification' = 'restricted', 'pii_type' = 'national_id');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `street_address` SET TAGS ('classification' = 'confidential', 'pii_type' = 'street_address');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `country` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `region` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `created_at` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders SET TAGS ('classification' = 'restricted', 'domain' = 'sales', 'layer' = 'silver', 'owner' = 'gov-sales-stewards', 'data_contract' = 'sales.orders');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `order_id` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `customer_id` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `order_ts` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `amount` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `currency` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `card_number` SET TAGS ('classification' = 'restricted', 'pii_type' = 'card_number');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `region` SET TAGS ('classification' = 'internal');

-- ===== masks =====
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `full_name` SET MASK gov_prod.governance.mask_person_name;
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `email` SET MASK gov_prod.governance.mask_email;
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `full_name` SET MASK gov_prod.governance.mask_person_name;
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `email` SET MASK gov_prod.governance.mask_email;
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `phone` SET MASK gov_prod.governance.mask_phone;
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `date_of_birth` SET MASK gov_prod.governance.mask_date_of_birth;
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `national_id` SET MASK gov_prod.governance.mask_national_id;
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `street_address` SET MASK gov_prod.governance.mask_street_address;
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `card_number` SET MASK gov_prod.governance.mask_card_number;

-- ===== row_filters =====
ALTER TABLE gov_prod.customer_gold.customer_360 SET ROW FILTER gov_prod.governance.filter_region ON (`region`);
ALTER TABLE gov_prod.customer_silver.customers SET ROW FILTER gov_prod.governance.filter_region ON (`region`);
ALTER TABLE gov_prod.sales_silver.orders SET ROW FILTER gov_prod.governance.filter_region ON (`region`);
