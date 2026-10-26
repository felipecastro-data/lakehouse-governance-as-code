# Day-0 Spike — Free Edition capability check

Run these before Phase 1b. Record the result and any design change next to each item.

| # | Question | How to verify | Result | Design impact if "no" |
|---|---|---|---|---|
| 1 | Can I create groups, and are they **account-level** (usable in UC grants)? | Settings → Identity and access → Groups → create `gov-spike`; then `GRANT USE CATALOG ON CATALOG main TO \`gov-spike\`` | | Grant to users directly in a `principals` override; document as delta |
| 2 | Can I invite a second user? | Settings → Identity and access → Users → Add | | Demo by toggling own group membership |
| 3 | Can I create a service principal + OAuth secret for CI? | Settings → Identity and access → Service principals | | CI uses a PAT stored as a GitHub secret |
| 4 | Can I create catalogs on default storage? | `CREATE CATALOG gov_spike` | | Use `main` catalog with env-prefixed schemas |
| 5 | Which system schemas are enabled? | `SHOW SCHEMAS IN system`; `SELECT * FROM system.access.audit LIMIT 1`; same for `table_lineage`, `column_lineage` | | Scorecard uses `information_schema` only |
| 6 | Are `column_masks`, `row_filters`, `column_tags`, `table_tags` in `information_schema`? | `SHOW TABLES IN system.information_schema` | | Drift check uses `DESCRIBE TABLE EXTENDED` |
| 7 | Do row filters with a mapping-table subquery work on serverless? | Create a test table + filter from `gov_engine plan` output | | Hardcode regions in the filter function |
| 8 | Do mask/filter functions require `EXECUTE` for readers? | Query a masked table as the second user without `EXECUTE` | | Add `EXECUTE` grant on `governance` schema |
| 9 | Is PyPI reachable from serverless (job environment dependencies)? | Job with `dependencies: [faker]` | | Generate data with SQL / Python stdlib |
| 10 | Are ABAC policies / governed tags available? | Catalog Explorer → Policies; `CREATE POLICY` | | Keep engine-based tag enforcement (ADR-0003) |
| 11 | Does the CLI support the bundle `catalogs` resource? | `databricks bundle validate` with a `catalogs:` block | | Keep catalog creation in bootstrap |
| 12 | Daily quota / concurrency limits observed | Workspace usage page | | Size data and schedules accordingly |
