# Production deltas

What this design would change in an enterprise Databricks account. Free Edition constraints are
deliberate trade-offs, not gaps in understanding.

| Area | This project (Free Edition) | Enterprise setup |
|---|---|---|
| Environment isolation | Catalog per env in one workspace | Workspace per env + **workspace-catalog binding** so prod data is unreachable from dev |
| Identity | Engine creates account groups via the workspace SCIM proxy | SCIM from the IdP (Entra ID / Okta), SSO, no local users; engine only checks groups exist |
| Pipeline identity | `gov-deployer` runs the pipeline, exempted from policies via `gov-pipeline-runners` | Separate pipeline service principal per environment, distinct from the deployer |
| Deployment identity | One `gov-deployer` service principal (OAuth M2M), workspace admin | One service principal per environment with least privilege: `CREATE CATALOG`, `MANAGE` on its tag policies, no workspace admin |
| Storage | Default managed storage | Managed locations per catalog on dedicated storage accounts; external locations with storage credentials |
| Encryption | Platform-managed keys | Customer-managed keys for managed services and storage |
| Networking | Public endpoints | Private Link, IP access lists, serverless egress control |
| Tag-driven policy | Native ABAC policies on governed tags (same as enterprise) | Policies at metastore/catalog level shared across workspaces |
| Classification | Declared in contracts; policies also match system `class.*` tags | Automated data classification scans on every catalog, with steward review of new findings |
| Drift response | Report and fail the pipeline; no auto-revoke | Same report as a scheduled job with alerts; reviewed `remediate` command per domain |
| System table access | Lineage through an admin-owned view in `audit`; `system.access` can't be granted on Free Edition | Metastore admin grants `system.access` to a dedicated monitoring principal; views still used for auditors |
| Audit | Admin-owned views over system tables; scorecard dashboard refreshed by the daily pipeline | Audit logs also delivered to SIEM; alerts on manual grant changes, policy changes and denied access to restricted data |
| Observability ownership | Account admin owns the audit views (one-time human step per environment) | Views owned by a dedicated monitoring principal with `system.access` access, deployed from CI |
| Right to erasure | Register holds SHA-256 of the subject key; erasure is physical after the 7-day VACUUM window | Keyed hash (HMAC, secret in a secret scope); request intake from a DSR tool (OneTrust, ServiceNow) via API; shorter `deletedFileRetentionDuration` on PII tables; erasure propagated to downstream shares and backups |
| Data sharing | Out of scope | Delta Sharing with recipient-level row filters |
| Change control | PR review + CI | PR review, CODEOWNERS per domain, prod deploy behind environment approval |
| Compliance | Demo scenarios | Compliance security profile (HIPAA/PCI) where required; retention policies enforced |
