# ADR-0002: Governance-as-code engine, separate from the bundle

- **Status**: Accepted
- **Date**: 2026-10-26

## Context

Databricks Asset Bundles manage schemas, volumes, jobs and dashboards, and support schema grants.
They do not manage column masks, row filters, tags or groups. Writing those as hand-maintained SQL
scatters policy across files and makes review and drift detection hard.

## Decision

- Policy is declared in `governance/*.yml` (layout, classification, access policy, data contracts).
- A Python engine (`src/gov_engine`) validates the spec and renders idempotent Unity Catalog SQL
  (functions, mapping tables, grants, tags, masks, row filters).
- The engine runs locally (`plan`, `matrix`) and in Databricks as the `governance_apply` bundle job.
- **The bundle owns infrastructure; the engine owns access policy.** The bundle declares no grants.

## Consequences

- One reviewable source of truth for "who can see what"; PR diffs show policy changes.
- Rendering is pure Python → unit-testable without a workspace.
- Drift detection can compare the same spec against `information_schema`.
- Two deployment steps (bundle deploy, then apply job) — wired together in CI.

## Alternatives considered

- **Bundle grants + SQL files**: splits policy across two mechanisms. Rejected.
- **Terraform Databricks provider**: covers grants and some tags, but masks/filters still need SQL,
  and it adds a second IaC tool next to bundles. Kept as a production option.
