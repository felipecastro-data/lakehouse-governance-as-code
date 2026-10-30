
-- ===== reference_data =====
CREATE TABLE IF NOT EXISTS gov_prod.governance.region_access (group_name STRING NOT NULL, value STRING NOT NULL) COMMENT 'Group to region mapping for row filter region. Managed by gov_engine - do not edit by hand';
INSERT OVERWRITE gov_prod.governance.region_access VALUES
  ('gov-analysts-amer', 'AMER'),
  ('gov-analysts-emea', 'EMEA'),
  ('gov-pii-readers', 'AMER'),
  ('gov-pii-readers', 'APAC'),
  ('gov-pii-readers', 'EMEA');
CREATE TABLE IF NOT EXISTS gov_prod.governance.erasure_requests (request_id STRING NOT NULL, subject_hash STRING NOT NULL, requested_at TIMESTAMP, requested_by STRING) COMMENT 'Right-to-erasure register: SHA-256 of customer_id, never the key. Managed by gov_engine - do not edit by hand';

-- ===== functions =====
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_person_name(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=person_name (initial_only). Managed by gov_engine - do not edit by hand'
RETURN concat(left(v, 1), '.');
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_email(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=email (partial_email). Managed by gov_engine - do not edit by hand'
RETURN regexp_replace(v, '^(.)[^@]*', '$1***');
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_phone(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=phone (last4). Managed by gov_engine - do not edit by hand'
RETURN concat(repeat('*', greatest(length(v) - 4, 0)), right(v, 4));
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_street_address(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=street_address (redact). Managed by gov_engine - do not edit by hand'
RETURN '***REDACTED***';
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_date_of_birth(v DATE)
RETURNS DATE
COMMENT 'Mask for pii_type=date_of_birth (year_only). Managed by gov_engine - do not edit by hand'
RETURN make_date(year(v), 1, 1);
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_national_id(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=national_id (sha256). Managed by gov_engine - do not edit by hand'
RETURN sha2(v, 256);
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_card_number(v STRING)
RETURNS STRING
COMMENT 'Mask for pii_type=card_number (last4). Managed by gov_engine - do not edit by hand'
RETURN concat(repeat('*', greatest(length(v) - 4, 0)), right(v, 4));
CREATE OR REPLACE FUNCTION gov_prod.governance.filter_region(row_value STRING)
RETURNS BOOLEAN
COMMENT 'Row filter on region, backed by region_access. Managed by gov_engine - do not edit by hand'
RETURN EXISTS (SELECT 1 FROM gov_prod.governance.region_access a
  WHERE a.value = row_value AND is_account_group_member(a.group_name));

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

-- ===== tables =====
CREATE TABLE IF NOT EXISTS gov_prod.customer_gold.customer_360 (
  `customer_id` STRING NOT NULL,
  `full_name` STRING,
  `email` STRING,
  `region` STRING NOT NULL,
  `order_count` BIGINT,
  `lifetime_value` DECIMAL(18,2),
  `last_order_ts` TIMESTAMP,
  CONSTRAINT customer_360_pk PRIMARY KEY (`customer_id`)
) COMMENT 'Gold data product — customer profile with order KPIs, for analysts. Contract customer.customer_360.';
CREATE TABLE IF NOT EXISTS gov_prod.customer_silver.customers (
  `customer_id` STRING NOT NULL,
  `full_name` STRING,
  `email` STRING,
  `phone` STRING,
  `date_of_birth` DATE,
  `national_id` STRING,
  `street_address` STRING,
  `country` STRING,
  `region` STRING NOT NULL,
  `created_at` TIMESTAMP,
  CONSTRAINT customers_pk PRIMARY KEY (`customer_id`)
) COMMENT 'Conformed customer master, one row per customer. Contract customer.customers.';
CREATE TABLE IF NOT EXISTS gov_prod.sales_silver.orders (
  `order_id` STRING NOT NULL,
  `customer_id` STRING NOT NULL,
  `order_ts` TIMESTAMP,
  `amount` DECIMAL(18,2),
  `currency` STRING,
  `card_number` STRING,
  `region` STRING NOT NULL,
  CONSTRAINT orders_pk PRIMARY KEY (`order_id`)
) COMMENT 'One row per order with its payment method. Contract sales.orders.';

-- ===== tags =====
ALTER TABLE gov_prod.customer_gold.customer_360 SET TAGS ('classification' = 'confidential', 'domain' = 'customer', 'layer' = 'gold', 'owner' = 'gov-customer-stewards', 'data_contract' = 'customer.customer_360');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `customer_id` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `full_name` SET TAGS ('classification' = 'confidential', 'pii_type' = 'person_name');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `email` SET TAGS ('classification' = 'confidential', 'pii_type' = 'email');
ALTER TABLE gov_prod.customer_gold.customer_360 ALTER COLUMN `region` SET TAGS ('classification' = 'internal', 'filter_key' = 'region');
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
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `region` SET TAGS ('classification' = 'internal', 'filter_key' = 'region');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `created_at` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders SET TAGS ('classification' = 'restricted', 'domain' = 'sales', 'layer' = 'silver', 'owner' = 'gov-sales-stewards', 'data_contract' = 'sales.orders');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `order_id` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `customer_id` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `order_ts` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `amount` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `currency` SET TAGS ('classification' = 'internal');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `card_number` SET TAGS ('classification' = 'restricted', 'pii_type' = 'card_number');
ALTER TABLE gov_prod.sales_silver.orders ALTER COLUMN `region` SET TAGS ('classification' = 'internal', 'filter_key' = 'region');

-- ===== policies =====
CREATE OR REPLACE POLICY mask_person_name ON CATALOG gov_prod
COMMENT 'Mask person_name (confidential). Managed by gov_engine - do not edit by hand'
COLUMN MASK gov_prod.governance.mask_person_name
TO `account users` EXCEPT `gov-pii-readers`, `gov-pii-restricted-readers`, `gov-pipeline-runners`
FOR TABLES
MATCH COLUMNS has_tag_value('pii_type', 'person_name') OR has_tag('class.name') AS col
ON COLUMN col;
CREATE OR REPLACE POLICY mask_email ON CATALOG gov_prod
COMMENT 'Mask email (confidential). Managed by gov_engine - do not edit by hand'
COLUMN MASK gov_prod.governance.mask_email
TO `account users` EXCEPT `gov-pii-readers`, `gov-pii-restricted-readers`, `gov-pipeline-runners`
FOR TABLES
MATCH COLUMNS has_tag_value('pii_type', 'email') OR has_tag('class.email_address') AS col
ON COLUMN col;
CREATE OR REPLACE POLICY mask_phone ON CATALOG gov_prod
COMMENT 'Mask phone (confidential). Managed by gov_engine - do not edit by hand'
COLUMN MASK gov_prod.governance.mask_phone
TO `account users` EXCEPT `gov-pii-readers`, `gov-pii-restricted-readers`, `gov-pipeline-runners`
FOR TABLES
MATCH COLUMNS has_tag_value('pii_type', 'phone') OR has_tag('class.phone_number') AS col
ON COLUMN col;
CREATE OR REPLACE POLICY mask_street_address ON CATALOG gov_prod
COMMENT 'Mask street_address (confidential). Managed by gov_engine - do not edit by hand'
COLUMN MASK gov_prod.governance.mask_street_address
TO `account users` EXCEPT `gov-pii-readers`, `gov-pii-restricted-readers`, `gov-pipeline-runners`
FOR TABLES
MATCH COLUMNS has_tag_value('pii_type', 'street_address') OR has_tag('class.street_address') OR has_tag('class.location') AS col
ON COLUMN col;
CREATE OR REPLACE POLICY mask_date_of_birth ON CATALOG gov_prod
COMMENT 'Mask date_of_birth (confidential). Managed by gov_engine - do not edit by hand'
COLUMN MASK gov_prod.governance.mask_date_of_birth
TO `account users` EXCEPT `gov-pii-readers`, `gov-pii-restricted-readers`, `gov-pipeline-runners`
FOR TABLES
MATCH COLUMNS has_tag_value('pii_type', 'date_of_birth') AS col
ON COLUMN col;
CREATE OR REPLACE POLICY mask_national_id ON CATALOG gov_prod
COMMENT 'Mask national_id (restricted). Managed by gov_engine - do not edit by hand'
COLUMN MASK gov_prod.governance.mask_national_id
TO `account users` EXCEPT `gov-pii-restricted-readers`, `gov-pipeline-runners`
FOR TABLES
MATCH COLUMNS has_tag_value('pii_type', 'national_id') OR has_tag('class.us_ssn') OR has_tag('class.passport') OR has_tag('class.driver_license') AS col
ON COLUMN col;
CREATE OR REPLACE POLICY mask_card_number ON CATALOG gov_prod
COMMENT 'Mask card_number (restricted). Managed by gov_engine - do not edit by hand'
COLUMN MASK gov_prod.governance.mask_card_number
TO `account users` EXCEPT `gov-pii-restricted-readers`, `gov-pipeline-runners`
FOR TABLES
MATCH COLUMNS has_tag_value('pii_type', 'card_number') OR has_tag('class.credit_card') AS col
ON COLUMN col;
CREATE OR REPLACE POLICY filter_region ON CATALOG gov_prod
COMMENT 'Row filter on filter_key=region. Managed by gov_engine - do not edit by hand'
ROW FILTER gov_prod.governance.filter_region
TO `account users` EXCEPT `gov-platform-admins`, `gov-data-engineers`, `gov-pii-restricted-readers`, `gov-customer-stewards`, `gov-sales-stewards`, `gov-pipeline-runners`
FOR TABLES
MATCH COLUMNS has_tag_value('filter_key', 'region') AS col
USING COLUMNS (col);
