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
  First dev run (2026-10-27), all tasks green: bronze 5,169 customer / 50,260 order rows → silver 4,984 / 48,857
  (duplicates, unknown countries, test and orphan orders removed) → gold 4,984 profiles; 6/6 quality rules pass.
  Read as `gov-platform-admins`: every PII column masked by its policy (`u***@example.com`, `********1679`,
  DOB `1948-01-01`, SHA-256 national ID, card `************6688`); all regions visible (row filter bypass).
  Gold holds orders from all three regions, which shows the pipeline identity bypasses the row filter.
- [x] **Phase 3 — Protection & verification**: drift detection and PII propagation check ([ADR-0008](adr/0008-drift-and-pii-propagation.md)).
  - [x] `gov_engine.drift`: schemas, direct grants, contract columns and types, engine-owned tags, ABAC policies and per-column masks vs `information_schema`; critical drift fails the `drift` task.
  - [x] `gov_engine.lineage`: walks `system.access.column_lineage` from tagged PII (and bronze PII inferred from lineage) and flags untagged silver and gold columns.
  - [x] Checked locally against `gov_dev` (2026-10-28): 26 lineage edges, 9 bronze columns inferred as PII, 0 untagged PII columns; schema, table and tag drift clean.
  - [x] `system.access` can't be granted on (owned by "System user", account admins have no `MANAGE`), so lineage is read through `gov_dev.audit.column_lineage`, a view an account admin owns, with `SELECT` granted to `gov-deployer`.
  - [x] Dev pipeline run 2026-10-28 as `gov-deployer`, all tasks green: `drift` 0 critical / 0 warning (full visibility as catalog owner), `pii_propagation` 26 lineage edges, 9 bronze PII columns inferred, 0 untagged PII columns.
  - [x] FR8 acceptance (2026-10-28): a manual `GRANT SELECT ON VIEW gov_dev.audit.column_lineage TO gov-analysts-amer` failed the next run's `drift` task with `[critical] grant TABLE gov_dev.audit.column_lineage: undeclared SELECT to gov-analysts-amer`; every other task passed. The grant was then revoked.
- [x] **Phase 4 — Observability**: audit + lineage views, governance scorecard dashboard ([ADR-0009](adr/0009-audit-views-and-scorecard.md)).
  - [x] Audit views in `audit` (`column_lineage`, `table_access`, `grant_changes`, `policy_changes`, `access_denied`): SQL in `src/audit/views.sql`, created and owned by an account admin (`make audit-views`); bodies checked against `gov_dev` system tables (2026-10-29).
  - [x] `gov_engine.scorecard` + pipeline task `scorecard` (`run_if: ALL_DONE`) writing `audit.scorecard`, `audit.findings`, `audit.table_inventory`.
  - [x] AI/BI dashboard `governance_scorecard` in the bundle; `gov-auditors` `CAN_READ` ("Can view"), no embedded credentials.
  - [x] Dev pipeline run 2026-10-29 with the `scorecard` task, all tasks green: 100% owned (3/3), 100% classified (24/24), 100% PII masked (9/9), 4 restricted tables (2 bronze, classified from lineage), 0 drift, 0 untagged PII.
  - [x] Views created in `gov_dev` by the account admin (`make audit-views`), owned by the admin; scorecard tables owned by `gov-deployer`. All 10 dashboard datasets return rows: 3 manual grant changes (the FR8 test grant, its revoke, the deployer's lineage grant), 6 restricted reads by people, 4 denied requests.
  - [x] Dashboard checked in the UI by the admin (2026-10-29); daily dev schedule unpaused so the trends build history.
  - [x] FR10 with a second test user (only in `gov-auditors`, 2026-10-29): `SELECT` on `gov_dev.audit.grant_changes` returns rows; `system.access.audit` → `INSUFFICIENT_PERMISSIONS` (no `USE SCHEMA` on `system.access`); `gov_dev.customer_silver.customers` → `INSUFFICIENT_PERMISSIONS` (no `USE SCHEMA`); dashboard opens with the viewer's credentials and every counter and chart renders.
  - [x] Table widgets re-rendered after the spec fix (tables need widget spec version 2; version 1 showed "Invalid widget definition").
- [x] **Phase 5 — Privacy & polish**: right-to-erasure ([ADR-0010](adr/0010-right-to-erasure.md)), `make demo`, README visuals, deploy workflow.
  - [x] `governance/privacy.yml` (subject key, register); CI rejects a contract with PII but no `customer_id`.
  - [x] `gov_engine.erasure`: scope from `information_schema`, lineage gap check, hashed register (`MERGE`, idempotent), `DELETE` + `REORG ... APPLY (PURGE)`, `audit.erasure_log`.
  - [x] `right_to_erasure` job (erase → verify) as the deployer, `CAN_MANAGE_RUN` for `gov-data-engineers`; pipeline tasks `erasure` (after bronze) and `erasure_check`; scorecard metrics `erasure_requests`, `erasure_residual`.
  - [x] FR12 acceptance in dev (2026-10-30): `DSR-0001` for `C000042` deleted 31 rows from 5 tables (1 + 14 bronze, 1 + 14 silver, 1 gold); verify `0 residual rows, 0 gaps`. The next pipeline run re-ingested 15 bronze rows for the subject, the `erasure` task removed them before silver, `erasure_check` passed, scorecard `erasure_requests` 1 / `erasure_residual` 0.
  - [x] `make demo`: declare → apply → enforce (as the caller) → verify and measure (from the pipeline's recorded scorecard, measured as the catalog owner).
  - [x] Deploy workflow: validates policy first, optional pipeline run, step summary; `databricks/setup-cli` pinned to v1.22.1.
  - [x] README charts generated from the spec and the recorded scorecard (`scripts/readme_visuals.py` → `docs/images/*.svg`).
- [ ] **Prod deploy**: `deploy` workflow with `target=prod` (environment approval), `make audit-views ENV=prod` as the admin, first pipeline run.

## 10. Decisions

| Decision | Choice |
|---|---|
| Data domain | Retail: `customer` and `sales` domains |
| Table creation | From contracts, before data lands ([ADR-0007](adr/0007-contract-first-tables-and-pipeline-identity.md)) |
| Pipeline identity | `gov-deployer` in exempt group `gov-pipeline-runners` (ADR-0007) |
| Bronze PII | Protected by layer, inferred from lineage; no bronze contracts ([ADR-0008](adr/0008-drift-and-pii-propagation.md)) |
| Drift response | Report and fail on critical; never auto-revoke (ADR-0008) |
| Audit views | SQL in repo, created and owned by an account admin; auditors read them through the `audit` schema ([ADR-0009](adr/0009-audit-views-and-scorecard.md)) |
| Scorecard | Pipeline task as the deployer writes `audit` tables; dashboard queries with viewer credentials (ADR-0009) |
| Environments | Two: `dev`, `prod` |
| Contract format | ODCS v3 (subset + `customProperties`) |
| Policy engine language | Python, `pyyaml` only (runs locally and on serverless) |
| Group naming | `gov-<role>` (e.g. `gov-analysts-amer`) |
| Masking mechanism | Native ABAC on governed tags ([ADR-0005](adr/0005-native-abac.md)) |
| CI identity | `gov-deployer` service principal, OAuth M2M ([ADR-0006](adr/0006-deploy-service-principal.md)) |
