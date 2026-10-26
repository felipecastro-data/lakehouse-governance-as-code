# Production deltas

What this design would change in an enterprise Databricks account. Free Edition constraints are
deliberate trade-offs, not gaps in understanding.

| Area | This project (Free Edition) | Enterprise setup |
|---|---|---|
| Environment isolation | Catalog per env in one workspace | Workspace per env + **workspace-catalog binding** so prod data is unreachable from dev |
| Identity | Groups created in workspace UI | SCIM from the IdP (Entra ID / Okta), account-level groups, SSO, no local users |
| Deployment identity | PAT or user OAuth | Service principal per env with OAuth M2M; `run_as` on jobs; humans never own prod objects |
| Storage | Default managed storage | Managed locations per catalog on dedicated storage accounts; external locations with storage credentials |
| Encryption | Platform-managed keys | Customer-managed keys for managed services and storage |
| Networking | Public endpoints | Private Link, IP access lists, serverless egress control |
| Tag-driven policy | `gov_engine` emulates ABAC | Native **ABAC policies** + governed tags; engine shrinks to tag assignment and drift checks |
| Classification | Declared in contracts | Automated data classification scans feeding steward review |
| Audit | System tables queried in-workspace | Audit logs also delivered to SIEM; alerts on privileged actions |
| Data sharing | Out of scope | Delta Sharing with recipient-level row filters |
| Change control | PR review + CI | PR review, CODEOWNERS per domain, prod deploy behind environment approval |
| Compliance | Demo scenarios | Compliance security profile (HIPAA/PCI) where required; retention policies enforced |
