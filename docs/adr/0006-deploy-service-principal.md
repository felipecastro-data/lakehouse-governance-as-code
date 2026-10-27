# ADR-0006: Deploy as a service principal with OAuth M2M

- **Status**: Accepted
- **Date**: 2026-10-27

## Context

CI needs an identity to deploy the bundle and run the apply job. A personal access token ties prod
to one person, never expires on its own schedule, and makes every prod object owned by a human.
The spike (item 3) showed Free Edition supports service principals with OAuth secrets.

## Decision

- A dedicated service principal, **`gov-deployer`**, deploys every environment from GitHub Actions
  with OAuth M2M (`DATABRICKS_CLIENT_ID` / `DATABRICKS_CLIENT_SECRET`).
- Because it deploys, it **owns** the catalogs, schemas and jobs, and the apply job runs as it.
- Humans deploy only to `dev` from their laptop; prod changes go through a PR and the `prod`
  GitHub environment, which requires approval.
- The prod bundle root is the deployer's home folder, not `/Workspace/Shared`.

## Consequences

- Prod ownership and audit events show `gov-deployer`, not a person.
- Free Edition simplification: `gov-deployer` is a **workspace admin** (it creates account groups,
  governed tags and catalogs). In an enterprise account it would get only `CREATE CATALOG` on the
  metastore, `MANAGE` on its tag policies, and group management through SCIM from the IdP
  ([production deltas](../production-deltas.md)).
- The OAuth secret must be rotated; it lives only in GitHub secrets.
