# Day-0 Spike — Free Edition capability check

Run on 2026-10-27 against a Databricks Free Edition workspace (CLI v1.22.1, Serverless Starter
Warehouse 2X-Small). Test SQL: [`scripts/spike.sql`](../scripts/spike.sql).

| # | Question | Result | Design impact |
|---|---|---|---|
| 1 | Can I create groups usable in UC grants? | ✅ UI creates groups "to account and workspace"; `GRANT USE CATALOG ... TO \`gov-spike\`` works | Group-only access as designed |
| 2 | Can I invite a second user? | ⏳ Only 1 user today; UI check pending | Needed for the two-sided masking demo |
| 3 | Service principal + OAuth secret for CI? | ✅ SP created via CLI; OAuth secret create/delete works | CI uses a **deploy service principal (OAuth M2M)**, not a PAT |
| 4 | Create catalogs on default storage? | ✅ `CREATE CATALOG` works | Catalog per environment as designed |
| 5 | System schemas enabled? | ✅ `access.audit` (6k events / 7 days), `table_lineage`, `column_lineage`, plus `billing`, `query`, `compute`, `lakeflow`, `tags`, … Audit lag ≈ 13 min | Audit + lineage views and scorecard are feasible |
| 6 | Policy views in `information_schema`? | ✅ `column_masks`, `row_filters`, `column_tags`, `table_tags`, `*_privileges`, `abac_policy_definitions` | Drift detection can be pure SQL |
| 7 | Mapping-table row filter on serverless? | ✅ 1 of 2 rows returned; mask calling `can_see()` returns `a***@example.com` | ADR-0004 confirmed |
| 8 | Do readers need `EXECUTE` on mask/filter functions? | ⏳ Needs a second user (item 2) | Grant `EXECUTE` on `governance` if required |
| 9 | PyPI reachable from serverless jobs? | ⏳ Phase 2 (data generator) | Fallback: stdlib / SQL generation |
| 10 | ABAC policies / governed tags? | ✅ **Available.** 100+ system `class.*` governed tags; custom governed tag created via `/api/2.1/tag-policies`; `CREATE POLICY ... COLUMN MASK ... MATCH COLUMNS has_tag_value(...)` masked the column. New tag policies take ~1 min to propagate | Revisit ADR-0003: native ABAC instead of per-column `SET MASK` |
| 11 | Bundle `catalogs` resource supported? | ❌ `bundle validate` accepts it, but **deploy fails**: the catalogs REST API returns "Metastore storage root URL does not exist" on Default Storage. SQL `CREATE CATALOG` works | Catalog created by `gov_engine ensure-catalog` (SQL) before `bundle deploy` |
| 12 | Quota / concurrency limits | ⏳ Observe during Phase 2 | Size data and schedules accordingly |

## Follow-up findings (2026-10-27, during the ABAC redesign)

- **Catalog-level ABAC verified end to end**: `CREATE POLICY ... ON CATALOG` with `COMMENT`, `COLUMN MASK`
  and `ROW FILTER ... USING COLUMNS`, `EXCEPT` with several groups, and `has_tag_value(...) OR has_tag('class.*')`.
- **Policies require every `EXCEPT` principal to exist** (`PRINCIPAL_DOES_NOT_EXIST`).
- **`databricks groups create` makes workspace-local groups** that Unity Catalog cannot see. Account groups are
  created through the workspace proxy `/api/2.0/account/scim/v2/Groups` → `gov_engine sync-groups`.
- **Service principals created in the workspace are account-level** (visible in the account SCIM proxy).
- **Workspace admins get no data access to a catalog owned by the deploy SP**: after the first deploy
  the admin user gets `USE CATALOG` denied on `gov_dev`. Access comes only through `gov-*` groups
  (break-glass: `gov-platform-admins`).
- **Tag policies can be updated in place** with `PATCH /api/2.1/tag-policies/{key}?update_mask=description,values`.

## Spike artifacts to clean up after item 8

- Catalog `gov_spike` (`DROP CATALOG gov_spike CASCADE`)
- Policy `spike_mask_email` (dropped with the catalog)
- Governed tag `spike_pii_type` (`databricks api delete /api/2.1/tag-policies/spike_pii_type`)
- Service principal `gov-spike-sp`
- Governed tag `spike_filter_key`
- Groups `gov-spike`, `gov-spike-acct` (account groups)
