# Lakehouse Governance as Code

[![ci](https://github.com/felipecastro-data/lakehouse-governance-as-code/actions/workflows/ci.yml/badge.svg)](https://github.com/felipecastro-data/lakehouse-governance-as-code/actions/workflows/ci.yml)
![Databricks Free Edition](https://img.shields.io/badge/Databricks-Free%20Edition-FF3621)
![Unity Catalog](https://img.shields.io/badge/Unity%20Catalog-governed-1B3139)
![License: MIT](https://img.shields.io/badge/license-MIT-blue)

**Unity Catalog governance on Databricks Free Edition, declared in Git, applied by an engine, checked for drift, and measured.**

Every grant, classification tag, column mask and row filter in this lakehouse comes from four YAML
files. A small Python engine validates them, renders idempotent Unity Catalog SQL, and applies it
through a Databricks Asset Bundle job. Change who can see personal data with a one-line pull request.

```mermaid
flowchart LR
    Y["governance/*.yml<br/>layout · classification<br/>access policy · contracts"] --> E["gov_engine<br/>validate · plan · apply"]
    E --> UC[("Unity Catalog<br/>grants · tags · masks · row filters")]
    UC --> ST[("System tables<br/>audit · lineage")]
    ST --> SC["Drift checks +<br/>governance scorecard"]
    Y -. declared state .-> SC
```

## What this demonstrates

| Area | How |
|---|---|
| **Data architecture** | Catalog per environment, `<domain>_<layer>` schemas, clear ownership split between bundle and engine ([ADRs](docs/adr)) |
| **Access control** | Group-only grants, least privilege, no human writes in prod, break-glass group ([access matrix](docs/generated/access-matrix-prod.md)) |
| **Classification** | 4 levels → controls; contracts tag PII columns, engine derives masks (ABAC semantics) |
| **Data protection** | Column masks via one `can_see(level)` policy function; row filters backed by a mapping table; pseudonymization |
| **Data contracts** | [ODCS v3](https://bitol-io.github.io/open-data-contract-standard/) contract per governed table |
| **Verification** | Spec validation in CI, drift detection, PII propagation check via column lineage *(Phase 3)* |
| **Observability** | Audit + lineage views and a governance scorecard *(Phase 4)* |
| **Platform engineering** | Databricks Asset Bundles, GitHub Actions, unit + consistency tests |

## How a policy becomes enforcement

A contract marks a column as PII:

```yaml
# governance/contracts/customer.customers.yml
- name: email
  logicalType: string
  customProperties:
    - property: piiType
      value: email
```

`classification.yml` says `email` is **confidential**, masked with `partial_email`, and only
`pii_readers` may unmask confidential data. The engine renders:

```sql
CREATE OR REPLACE FUNCTION gov_prod.governance.mask_email(v STRING) RETURNS STRING
RETURN CASE WHEN gov_prod.governance.can_see('confidential') THEN v
  ELSE regexp_replace(v, '^(.)[^@]*', '$1***') END;

ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `email`
  SET TAGS ('classification' = 'confidential', 'pii_type' = 'email');
ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `email`
  SET MASK gov_prod.governance.mask_email;
```

An analyst sees `j***@example.com`; a member of `gov-pii-readers` sees the real address.
Full rendered plan: [docs/generated/plan-prod.sql](docs/generated/plan-prod.sql).

## Repository layout

```
governance/            the policy — single source of truth
  layout.yml           environments, domains, layers
  classification.yml   levels, mask strategies, PII types
  access_policy.yml    principals, grants, row filters
  contracts/           ODCS data contracts per table
src/gov_engine/        validate · render · apply · (drift, lineage)
src/jobs/              Databricks job entrypoints
resources/             bundle resources: schemas, jobs
databricks.yml         bundle targets (dev, prod)
docs/                  plan, architecture, ADRs, RACI, production deltas
tests/                 spec, render, apply and bundle-consistency tests
```

## Quickstart

```bash
make setup                 # .venv + dev dependencies
make test                  # unit + consistency tests
make validate              # validate governance/*.yml
make plan ENV=prod         # preview the SQL
make matrix ENV=prod       # access matrix as Markdown
```

Deploy to Databricks Free Edition (after the [Day-0 spike](docs/spike-checklist.md)):

```bash
databricks auth login --host https://<your-workspace>.cloud.databricks.com
make bootstrap ENV=dev     # print catalog SQL; run once in the SQL editor
scripts/bootstrap_groups.sh
make apply ENV=dev         # bundle deploy + governance_apply job
```

## Status

| Phase | Scope | Status |
|---|---|---|
| 0 | Free Edition capability spike | ⏳ |
| 1a | Scaffold: spec, engine, bundle, CI, docs | ✅ |
| 1b | Bootstrap catalogs + groups, deploy, apply grants | ⏳ |
| 2 | Synthetic data, bronze → silver → gold | ⏳ |
| 3 | Masks/filters live, drift detection, PII propagation | ⏳ |
| 4 | Audit + lineage views, scorecard dashboard | ⏳ |
| 5 | Right-to-erasure, scripted demo | ⏳ |

Full plan: [docs/PLAN.md](docs/PLAN.md).

## Free Edition trade-offs

Built on a single serverless workspace, so environments are catalogs and some enterprise controls
are out of reach. Each trade-off is documented with its enterprise equivalent in
[docs/production-deltas.md](docs/production-deltas.md).

## License

MIT
