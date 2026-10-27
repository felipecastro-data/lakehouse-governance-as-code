-- Contract: governance/contracts/customer.customer_360.yml (table created and tagged by gov_engine).
-- Customer profile with order KPIs. PII columns are copied as-is: ABAC masks them on read.
INSERT OVERWRITE {{catalog}}.customer_gold.customer_360
SELECT
  c.customer_id,
  c.full_name,
  c.email,
  c.region,
  count(o.order_id)                                 AS order_count,
  CAST(coalesce(sum(o.amount), 0) AS DECIMAL(18,2)) AS lifetime_value,
  max(o.order_ts)                                   AS last_order_ts
FROM {{catalog}}.customer_silver.customers c
LEFT JOIN {{catalog}}.sales_silver.orders o ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.full_name, c.email, c.region;
