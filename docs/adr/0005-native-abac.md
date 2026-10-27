# ADR-0005: Native ABAC policies on governed tags

- **Status**: Accepted — supersedes [ADR-0003](0003-classification-driven-masking.md)
- **Date**: 2026-10-27

## Context

ADR-0003 planned to emulate attribute-based access control: the engine would attach a mask to every
PII column with `ALTER COLUMN ... SET MASK`. The Day-0 spike ([spike-checklist.md](../spike-checklist.md),
item 10) showed that Free Edition supports **native ABAC**: governed tags (tag policies) and
`CREATE POLICY` with `COLUMN MASK` and `ROW FILTER`, verified at catalog level with `EXCEPT` clauses
and `has_tag` / `has_tag_value` conditions.

## Decision

1. **Governed tags** are declared in the spec and synced through `/api/2.1/tag-policies`:
   - `classification`: the levels in `classification.yml`
   - `pii_type`: the PII types in `classification.yml`
   - `filter_key`: the row filters in `access_policy.yml`
2. **One catalog-level policy per PII type** and one per row filter:
   ```sql
   CREATE OR REPLACE POLICY mask_email ON CATALOG gov_prod
   COLUMN MASK gov_prod.governance.mask_email
   TO `account users` EXCEPT `gov-pii-readers`, `gov-pii-restricted-readers`
   FOR TABLES
   MATCH COLUMNS has_tag_value('pii_type', 'email') OR has_tag('class.email_address') AS col
   ON COLUMN col
   ```
3. **Exemptions live in the policy** (`EXCEPT`, from `unmasked_for` / `bypass`); mask functions are
   pure transformations with no group logic.
4. **Contracts only tag.** The engine's only per-table statements are `SET TAGS`; masks and filters
   follow the tags.
5. **Defense in depth**: each PII type can also match Databricks system classification tags
   (`class.email_address`, `class.credit_card`, …), so a column found by automatic data
   classification is masked even before a contract declares it.

## Consequences

- A new table is protected the moment its columns are tagged. No per-table policy SQL to forget.
- `information_schema.abac_policy_definitions` lists ~8 policies instead of one mask per column,
  which makes review and drift detection simpler.
- Governed tags restrict values: a typo like `pii_type = 'emial'` is rejected by the platform.
- Every principal in `EXCEPT` must exist before apply, so the apply job creates groups first.
- New tag policies take ~1 minute to become usable; the apply job waits after creating one.
- A column matching two mask policies (for example contract `pii_type=email` and system
  `class.name`) must resolve to one mask; keep `system_tags` specific. `date_of_birth` has no system
  tag because auto-classified birth dates may be `STRING` while its mask takes `DATE`.

## Alternatives considered

- **Per-column `SET MASK`** (ADR-0003): works everywhere, but scales with column count and lets a
  forgotten column slip through. Kept as the fallback if ABAC is unavailable.
