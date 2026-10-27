-- Contract: governance/contracts/sales.orders.yml (table created and tagged by gov_engine).
-- Deduplicate, drop test orders and orders for unknown customers, normalize card numbers,
-- and take the region from the customer so the region row filter applies to orders too.
INSERT OVERWRITE {{catalog}}.sales_silver.orders
SELECT
  o.order_id,
  o.customer_id,
  to_timestamp(o.order_ts)                         AS order_ts,
  CAST(o.amount AS DECIMAL(18,2))                  AS amount,
  upper(o.currency)                                AS currency,
  regexp_replace(o.card_number, '[^0-9]', '')      AS card_number,
  c.region
FROM {{catalog}}.sales_bronze.orders_raw o
JOIN {{catalog}}.customer_silver.customers c ON c.customer_id = o.customer_id
WHERE o.status <> 'test'
QUALIFY row_number() OVER (PARTITION BY o.order_id ORDER BY o._ingested_at DESC) = 1;
