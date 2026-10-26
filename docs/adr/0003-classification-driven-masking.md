# ADR-0003: Classification-driven masking (ABAC semantics)

- **Status**: Accepted (revisit after spike item 10)
- **Date**: 2026-10-26

## Context

Masking rules written per column do not scale and drift from classification. Unity Catalog ABAC
policies solve this natively (policy on a tag → mask), but may not be available on Free Edition.

## Decision

- `classification.yml` defines ordered levels, who may unmask each level, mask strategies, and
  `pii_types` (each with a level and strategy).
- Contracts tag columns with a `piiType`. The engine derives the column's classification tag and
  attaches `governance.mask_<pii_type>`.
- Every mask function calls one generated helper, `governance.can_see(level)`, so "who sees what"
  is decided in one place.
- Contracts may raise a column's classification but never lower it below its `pii_type` level
  (validation error).

## Consequences

- Adding a PII column = one line in a contract. Changing who unmasks = one line in YAML.
- Same outcome as ABAC; if ABAC is available, the engine can emit `CREATE POLICY` statements
  instead of per-column `SET MASK`, keeping the same spec.

## Alternatives considered

- **Dynamic views** with `CASE WHEN is_account_group_member(...)`: legacy pattern, duplicates
  tables and can be bypassed if base-table access leaks. Rejected.
