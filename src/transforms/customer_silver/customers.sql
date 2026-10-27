-- Contract: governance/contracts/customer.customers.yml (table created and tagged by gov_engine).
-- One row per customer: keep the latest ingested record, normalize, derive region, drop unknown countries.
INSERT OVERWRITE {{catalog}}.customer_silver.customers
SELECT
  customer_id,
  concat_ws(' ', trim(first_name), trim(last_name))      AS full_name,
  lower(trim(email))                                     AS email,
  phone,
  to_date(date_of_birth)                                 AS date_of_birth,
  national_id,
  concat_ws(', ', street, city)                          AS street_address,
  country_code                                           AS country,
  CASE
    WHEN country_code IN ('US', 'CA', 'BR', 'MX')             THEN 'AMER'
    WHEN country_code IN ('GB', 'DE', 'FR', 'ES', 'NL')       THEN 'EMEA'
    WHEN country_code IN ('JP', 'AU', 'IN', 'SG')             THEN 'APAC'
  END                                                    AS region,
  to_timestamp(signup_ts)                                AS created_at
FROM {{catalog}}.customer_bronze.customers_raw
WHERE country_code IN ('US', 'CA', 'BR', 'MX', 'GB', 'DE', 'FR', 'ES', 'NL', 'JP', 'AU', 'IN', 'SG')
QUALIFY row_number() OVER (PARTITION BY customer_id ORDER BY _ingested_at DESC) = 1;
