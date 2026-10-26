# Project Plan — Lakehouse Governance as Code

> Governed lakehouse on **Databricks Free Edition** with **Unity Catalog**, where every access rule,
> classification, mask and row filter is declared in Git, applied by an engine, checked for drift
> and measured on a scorecard.

## 1. Vision

Most Unity Catalog demos show *features*. This project shows a *governance program*:

1. **Declare** — policy lives in YAML (`governance/`): layout, classification levels, access policy, data contracts.
2. **Apply** — a small engine (`src/gov_engine`) renders the spec into Unity Catalog SQL and applies it through a Databricks Asset Bundle job.
3. **Verify** — drift detection compares declared vs actual state; lineage checks catch PII flowing into untagged columns.
4. **Measure** — a governance scorecard built on system tables tracks coverage and access to sensitive data.

## 2. What this project demonstrates

| Skill area | Evidence in the repo |
|---|---|
| Data architecture | Environment × domain × layer layout, ownership split (bundle vs engine), ADRs |
| Access control | Group-only grants, least privilege, separation of duties, break-glass group |
| Data protection | Classification-driven column masks, mapping-table row filters, pseudonymization |
| Classification | 4-level scheme, tag taxonomy, tag-driven enforcement (ABAC-equivalent) |
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
| Catalogs, groups | One-time bootstrap (`gov_engine bootstrap`, scripts) |
| Schemas, volumes, jobs, dashboards | Databricks Asset Bundle |
| Grants, tags, masks, row filters | `gov_engine` (driven by `governance/*.yml`) |

Details: [architecture.md](architecture.md).

## 5. Functional requirements

| ID | Requirement | Acceptance check |
|---|---|---|
| FR1 | Layout: catalog per env, schema per domain × layer, plus `governance` and `audit` | Bundle deploy creates identical layout per target; consistency test passes |
| FR2 | Group-only access, declared in `access_policy.yml` | `SHOW GRANTS` contains no individual users |
| FR3 | Least privilege: no human `MODIFY` in prod; analysts read gold only; bronze engineers only | Generated access matrix matches the policy |
| FR4 | Classification: 4 levels (public, internal, confidential, restricted) mapped to controls | `classification.yml` is the single source; engine validates contracts against it |
| FR5 | Tag-driven masking: a column's `pii_type` determines its mask function | Analyst sees masked email; `pii_readers` member sees clear value |
| FR6 | Row filter via group→region mapping table | Changing the mapping changes visible rows without code change |
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
| Account console likely unavailable | Group/SP creation may be restricted | Spike item; principals are config in `access_policy.yml`, so fallback is a YAML change |
| Cannot impersonate users | Hard to show both sides of a mask | Second test user; policy logic in one `can_see()` function |
| Restricted outbound internet | No arbitrary downloads | Generate data in-workspace |
| Managed storage only | No external locations | Managed tables/volumes only |
| System tables lag / limited retention | Audit not real-time | Daily scorecard; demo after delay |
| Bundles don't manage masks/tags/groups | Policy needs another mechanism | `gov_engine` applied by a bundle job ([ADR-0002](adr/0002-governance-as-code-engine.md)) |
| ABAC / governed tags may be unavailable | No native tag-driven policies | Engine emulates ABAC ([ADR-0003](adr/0003-classification-driven-masking.md)) |
| Bundle dev mode prefixes names | Schema names diverge from policy | No `mode`; explicit `presets` per target |

## 8. Day-0 spike

See [spike-checklist.md](spike-checklist.md). Design adjusts based on the results.

## 9. Phases

- [ ] **Phase 0 — Spike**: verify Free Edition capabilities.
- [x] **Phase 1a — Scaffold**: repo, spec files, engine (validate/plan/matrix), bundle skeleton, CI, docs, ADRs.
- [ ] **Phase 1b — Foundation**: bootstrap catalogs + groups, deploy schemas, apply grants.
- [ ] **Phase 2 — Data**: synthetic generator, bronze → silver → gold jobs.
- [ ] **Phase 3 — Protection & verification**: apply masks/filters/tags, drift detection, PII propagation check.
- [ ] **Phase 4 — Observability**: audit + lineage views, governance scorecard dashboard.
- [ ] **Phase 5 — Privacy & polish**: right-to-erasure, `make demo`, README screenshots, deploy workflow.

## 10. Decisions

| Decision | Choice |
|---|---|
| Data domain | Retail: `customer` and `sales` domains |
| Environments | Two: `dev`, `prod` |
| Contract format | ODCS v3 (subset + `customProperties`) |
| Policy engine language | Python, `pyyaml` only (runs locally and on serverless) |
| Group naming | `gov-<role>` (e.g. `gov-analysts-amer`) |
