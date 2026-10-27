| principal | (catalog) | audit | customer_bronze | customer_gold | customer_silver | sales_bronze | sales_gold | sales_silver |
|---|---|---|---|---|---|---|---|---|
| `platform_admins` | USE CATALOG, USE SCHEMA, SELECT, MODIFY, CREATE TABLE, CREATE FUNCTION, APPLY TAG | – | – | – | – | – | – | – |
| `data_engineers` | USE CATALOG | – | USE SCHEMA, SELECT | USE SCHEMA, SELECT | USE SCHEMA, SELECT | USE SCHEMA, SELECT | USE SCHEMA, SELECT | USE SCHEMA, SELECT |
| `analysts_amer` | USE CATALOG | – | – | USE SCHEMA, SELECT | – | – | USE SCHEMA, SELECT | – |
| `analysts_emea` | USE CATALOG | – | – | USE SCHEMA, SELECT | – | – | USE SCHEMA, SELECT | – |
| `pii_readers` | USE CATALOG | – | – | USE SCHEMA, SELECT | USE SCHEMA, SELECT | – | USE SCHEMA, SELECT | USE SCHEMA, SELECT |
| `pii_restricted_readers` | USE CATALOG | – | – | USE SCHEMA, SELECT | USE SCHEMA, SELECT | – | USE SCHEMA, SELECT | USE SCHEMA, SELECT |
| `customer_stewards` | USE CATALOG | – | – | USE SCHEMA, SELECT, APPLY TAG | USE SCHEMA, SELECT, APPLY TAG | – | – | – |
| `sales_stewards` | USE CATALOG | – | – | – | – | – | USE SCHEMA, SELECT, APPLY TAG | USE SCHEMA, SELECT, APPLY TAG |
| `auditors` | USE CATALOG | USE SCHEMA, SELECT | – | – | – | – | – | – |
| `pipelines` | – | – | – | – | – | – | – | – |
