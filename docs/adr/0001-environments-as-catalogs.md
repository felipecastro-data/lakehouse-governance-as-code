# ADR-0001: Environments as catalogs

- **Status**: Accepted
- **Date**: 2026-10-26

## Context

Databricks Free Edition provides a single workspace attached to a single metastore. The usual
enterprise pattern — one workspace per environment with workspace-catalog binding — is not available.

## Decision

Model each environment as its own catalog (`gov_dev`, `gov_prod`) with an identical schema layout
`<domain>_<layer>` plus shared `governance` and `audit` schemas. Bundle targets point at the same
workspace and differ by the `catalog` variable.

## Consequences

- Promotion dev → prod is a change of target, not of code.
- Isolation is logical only: a principal with `USE CATALOG` on `gov_prod` can read prod from any
  compute. Mitigated by granting prod access to groups only and keeping humans read-only.
- Moving to a multi-workspace setup only adds catalog bindings; the layout does not change.

## Alternatives considered

- **Catalog per environment × layer** (`prod_gold`): more catalogs, grants by layer become catalog
  grants. Rejected: domain ownership is harder to express and catalog count grows fast.
- **Schema prefixes in one catalog** (`dev_customer_gold`): no catalog-level boundary at all. Rejected.
