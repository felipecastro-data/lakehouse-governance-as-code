# Project Plan — Lakehouse Governance as Code

> Governed lakehouse on **Databricks Free Edition** with **Unity Catalog**, where every access rule,
> classification, mask and row filter is declared in Git, applied by an engine, checked for drift
> and measured on a scorecard.

## 1. Vision

Most Unity Catalog demos show *features*. This project shows a *governance program*:

1. **Declare** — policy lives in YAML (`governance/`): layout, classification levels, access policy, data contracts.
2. **Apply** — a small engine (`src/gov_engine`) creates account groups and governed tags, then renders the spec into Unity Catalog SQL (grants, tags, native ABAC policies) and applies it through a Databricks Asset Bundle job.
3. **Verify** — drift detection compares declared vs actual state; lineage checks catch PII flowing into untagged columns.
4. **Measure** — a governance scorecard built on system tables tracks coverage and access to sensitive data.

## 2. What this project demonstrates

| Skill area | Evidence in the repo |
|---|---|
| Data architecture | Environment × domain × layer layout, ownership split (bundle vs engine), ADRs |
| Access control | Group-only grants, least privilege, separation of duties, break-glass group |
| Data protection | Classification-driven column masks, mapping-table row filters, pseudonymization |
| Classification | 4-level scheme as governed tags, native ABAC policies, auto-classification tags as a safety net |
| Data contracts | ODCS v3 contracts per table: owner, classification, quality rules |
| Observability | Audit + lineage views, drift detection, governance scorecard |
| Privacy engineering | Right-to-erasure scenario across layers, proven with lineage and audit |
| Platform engineering | DABs, CI/CD, tests, reproducible from scratch |

## 3. Scope

### In scope
- Synthetic retail dataset with realistic PII in two domains: **customer** (customers, addresses) and **sales** (orders, payments).
- Catalog per environment (`gov_dev`, `gov_prod`), schemas `<domain>_<layer>` plus shared `governance` and `audit`.
- Group-only access, column masks, row filter by region, tags, data contracts.
- Drift detection, lineage-based PII propagation check, governance scorecard dashboard.
- Right-to-erasure scenario.
- Deployment with Databricks Asset Bundles; CI with GitHub Actions.

### Out of scope
Real data, SSO/SCIM, private networking, customer-managed keys, Delta Sharing, external locations,
multiple workspaces, streaming. These are documented as [production deltas](production-deltas.md).

## 4. Architecture summary

```
gov_dev / gov_prod                     (catalog per environment)
├── customer_bronze | customer_silver | customer_gold
├── sales_bronze    | sales_silver    | sales_gold
├── governance      (mask/filter functions, mapping tables)
└── audit           (views over system tables, scorecard)
```

**Ownership split** (see [ADR-0002](adr/0002-governance-as-code-engine.md)):

| Concern | Owner |
|---|---|
| Catalog | `gov_engine ensure-catalog` (SQL, before deploy) |
| Schemas, volumes, jobs, dashboards | Databricks Asset Bundle |
| Account groups, governed tags | `gov_engine` (REST API) |
| Grants, tags, ABAC policies | `gov_engine` (SQL, driven by `governance/*.yml`) |
| Group membership | People |

Details: [architecture.md](architecture.md).

## 5. Functional requirements

| ID | Requirement | Acceptance check |
|---|---|---|
| FR1 | Layout: catalog per env, schema per domain × layer, plus `governance` and `audit` | Bundle deploy creates identical layout per target; consistency test passes |
| FR2 | Group-only access, declared in `access_policy.yml` | `SHOW GRANTS` contains no individual users |
| FR3 | Least privilege: no human `MODIFY` in prod; analysts read gold only; bronze engineers only | Generated access matrix matches the policy |
| FR4 | Classification: 4 levels (public, internal, confidential, restricted) mapped to controls | `classification.yml` is the single source; engine validates contracts against it |
| FR5 | Native ABAC: one catalog policy per PII type matches the governed `pii_type` tag (and system `class.*` tags) | Analyst sees masked email; `pii_readers` member sees clear value; no per-column `SET MASK` |
| FR6 | Row filter policy on governed `filter_key` tag, backed by a group→region mapping table | Changing the mapping changes visible rows without code change |
| FR7 | Data contracts (ODCS v3) for every governed table | Contracts validated in CI |
| FR8 | Drift detection: declared vs actual grants, tags, masks | Manual `GRANT` shows up as drift |
| FR9 | PII propagation check using column lineage | Downstream column fed by PII but untagged is flagged |
| FR10 | Audit views granted to `auditors` only (no direct `system` access) | Auditor can query views, not `system.access.audit` |
| FR11 | Governance scorecard dashboard | Shows % owned, % classified, % PII masked, restricted access, grant changes, drift |
| FR12 | Right-to-erasure scenario | Customer removed from all layers; evidence via lineage + audit |
| FR13 | Everything deployed by bundle + engine; idempotent | Second deploy/apply produces no changes |

## 6. Non-functional requirements

- **Reproducible**: tear down and rebuild from the repo alone.
- **Idempotent**: re-running apply is safe.
- **No secrets in Git**: CI uses GitHub secrets.
- **Fits Free Edition quota**: ~100k rows, scheduled/manual jobs, no continuous compute.
- **Tested**: unit tests for spec validation and SQL rendering; consistency tests between spec and bundle.
- **Documented**: README, architecture, ADRs, RACI, production deltas, scripted demo.

## 7. Free Edition limitations → design response

| Limitation | Impact | Design response |
|---|---|---|
| Single workspace & metastore | No workspace isolation or catalog binding | Environments = catalogs ([ADR-0001](adr/0001-environments-as-catalogs.md)) |
| Serverless only, daily quota, small SQL warehouse | Small data, no always-on compute | Synthetic small data; manual/daily triggers |
| No account console | Account groups/SPs only via workspace | Engine creates account groups through the workspace SCIM proxy; SP created in workspace |
| Cannot impersonate users | Hard to show both sides of a mask | Second test user; exemptions are one `EXCEPT` clause per policy |
| Restricted outbound internet | No arbitrary downloads | Generate data in-workspace |
| Managed storage only | No external locations | Managed tables/volumes only |
| System tables lag / limited retention | Audit not real-time | Daily scorecard; demo after delay |
| Bundles don't manage policies, tags or groups | Policy needs another mechanism | `gov_engine` applied by a bundle job ([ADR-0002](adr/0002-governance-as-code-engine.md)) |
| ABAC available but needs governed tags + existing principals | Ordering matters | Apply job: groups → tag policies (wait ~1 min if new) → SQL ([ADR-0005](adr/0005-native-abac.md)) |
| Single admin user | Deploy identity tied to a person | `gov-deployer` service principal with OAuth M2M ([ADR-0006](adr/0006-deploy-service-principal.md)) |
| Default Storage: catalogs REST API fails | Bundle can't create the catalog | `gov_engine ensure-catalog` runs `CREATE CATALOG` via SQL before deploy |
| Bundle dev mode prefixes names | Schema names diverge from policy | No `mode`; explicit `presets` per target |

## 8. Day-0 spike

See [spike-checklist.md](spike-checklist.md). Design adjusts based on the results.

## 9. Phases

- [x] **Phase 0 — Spike**: verify Free Edition capabilities (items 2, 8, 9, 12 carried into later phases).
- [x] **Phase 1a — Scaffold**: repo, spec files, engine (validate/plan/matrix), bundle skeleton, CI, docs, ADRs.
- [x] **Phase 1a+ — ABAC redesign**: governed tags, catalog ABAC policies, account-group sync, OAuth deploy SP.
- [x] **Phase 1b — Foundation**: deploy as `gov-deployer`, sync groups + governed tags, apply grants and policies (dev: 50 applied, 27 table tags waiting for Phase 2 tables, 0 failed).
- [x] **Phase 2 — Data**: synthetic generator, contract-first tables, bronze → silver → gold job, contract quality checks ([ADR-0007](adr/0007-contract-first-tables-and-pipeline-identity.md)).
- [ ] **Phase 3 — Protection & verification**: apply masks/filters/tags, drift detection, PII propagation check.
- [ ] **Phase 4 — Observability**: audit + lineage views, governance scorecard dashboard.
- [ ] **Phase 5 — Privacy & polish**: right-to-erasure, `make demo`, README screenshots, deploy workflow.

## 10. Decisions

| Decision | Choice |
|---|---|
| Data domain | Retail: `customer` and `sales` domains |
| Table creation | From contracts, before data lands ([ADR-0007](adr/0007-contract-first-tables-and-pipeline-identity.md)) |
| Pipeline identity | `gov-deployer` in exempt group `gov-pipeline-runners` (ADR-0007) |
| Environments | Two: `dev`, `prod` |
| Contract format | ODCS v3 (subset + `customProperties`) |
| Policy engine language | Python, `pyyaml` only (runs locally and on serverless) |
| Group naming | `gov-<role>` (e.g. `gov-analysts-amer`) |
| Masking mechanism | Native ABAC on governed tags ([ADR-0005](adr/0005-native-abac.md)) |
| CI identity | `gov-deployer` service principal, OAuth M2M ([ADR-0006](adr/0006-deploy-service-principal.md)) |
