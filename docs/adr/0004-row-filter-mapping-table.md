# ADR-0004: Row filters backed by a mapping table

- **Status**: Accepted (revisit after spike item 7)
- **Date**: 2026-10-26

## Context

Row filters that hardcode `CASE WHEN is_account_group_member('x') THEN region = 'AMER'` require a
function change for every new group or region.

## Decision

Each row filter in `access_policy.yml` declares a column, bypass principals and a
principal → values mapping. The engine renders:

- `governance.<filter>_access (group_name, value)` — overwritten from the spec on every apply.
- `governance.<function>(row_value)` — `TRUE` for bypass groups, otherwise `EXISTS` a mapping row
  for a group the current user belongs to.

## Consequences

- Access changes are data changes, reviewed via the YAML diff.
- The mapping table itself is sensitive; only platform admins can modify it.
- A subquery per row filter has a cost; acceptable at this data size.

## Alternatives considered

- **Hardcoded CASE in the function**: simplest, fallback if mapping-table subqueries are not supported.
