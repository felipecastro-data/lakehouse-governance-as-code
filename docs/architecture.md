# Architecture

## Control flow: governance as code

```mermaid
flowchart LR
    subgraph Git["Git repository"]
        L[layout.yml]
        C[classification.yml]
        A[access_policy.yml]
        K[contracts/*.yml]
    end

    subgraph CI["GitHub Actions"]
        V[validate + test]
        P[plan: render SQL]
        D[bundle deploy]
    end

    subgraph DBX["Databricks Free Edition"]
        S[Schemas, jobs, dashboards<br/>owned by bundle]
        J[governance_apply job<br/>runs gov_engine as gov-deployer]
        UC[(Unity Catalog<br/>account groups · governed tags · grants<br/>tags · ABAC policies)]
        ST[(System tables<br/>audit · lineage · information_schema)]
        AV[audit views + scorecard]
        DR[drift + PII propagation checks]
    end

    Git --> V --> P --> D
    D --> S
    D --> J --> UC
    UC --> ST --> AV
    ST --> DR
    Git -. declared state .-> DR
```

## Namespace layout

```mermaid
flowchart TB
    M[(metastore)] --> DEV[gov_dev]
    M --> PROD[gov_prod]
    PROD --> CB[customer_bronze] & CS[customer_silver] & CG[customer_gold]
    PROD --> SB[sales_bronze] & SS[sales_silver] & SG[sales_gold]
    PROD --> GOV[governance<br/>mask/filter functions · mapping tables]
    PROD --> AUD[audit<br/>views over system tables]
```

`gov_dev` has the same structure. Schema names are `<domain>_<layer>`, so a grant can target
"all gold schemas" or "all customer schemas" with a selector in `access_policy.yml`.

## Ownership split

| Concern | Managed by | Why |
|---|---|---|
| Catalog | `gov_engine ensure-catalog` (SQL, before deploy) | Default Storage rejects the catalogs API the bundle uses |
| Schemas, volumes, jobs, dashboards | Databricks Asset Bundle | Declarative infra with targets |
| Account groups, governed tags | `gov_engine` (REST API) | Account-level; must exist before policies reference them |
| Grants, tags, ABAC policies, mask/filter functions, mapping tables | `gov_engine` (SQL) | Not expressible in bundles; policy must be one source of truth |
| Group membership | People (admins) | Who is in a group is an access request, not code |

Each object has exactly one owner so the two systems never overwrite each other ([ADR-0002](adr/0002-governance-as-code-engine.md)).

## Identity model

| Logical principal | Group | Purpose |
|---|---|---|
| `platform_admins` | `gov-platform-admins` | Break-glass, sees all regions |
| `data_engineers` | `gov-data-engineers` | Builds pipelines; write in dev, read-only in prod |
| `analysts_amer` / `analysts_emea` | `gov-analysts-*` | Gold read, rows filtered by region, PII masked |
| `pii_readers` | `gov-pii-readers` | Unmasks **confidential** columns |
| `pii_restricted_readers` | `gov-pii-restricted-readers` | Unmasks **restricted** columns |
| `customer_stewards` / `sales_stewards` | `gov-*-stewards` | Domain owners; can apply tags |
| `auditors` | `gov-auditors` | Read `audit` schema only |

Group names live in `access_policy.yml → principals`; everything else refers to logical names.
Groups are created as **account** groups through `/api/2.0/account/scim/v2/Groups`: the plain
workspace SCIM API creates workspace-local groups that Unity Catalog cannot resolve.

Deployments run as the **`gov-deployer`** service principal (OAuth M2M), which owns prod objects
([ADR-0006](adr/0006-deploy-service-principal.md)).

## Policy evaluation at query time (ABAC)

```mermaid
sequenceDiagram
    participant U as Analyst (gov-analysts-amer)
    participant UC as Unity Catalog
    participant P as ABAC policies on gov_prod
    participant RF as governance.filter_region
    participant MK as governance.mask_email
    U->>UC: SELECT * FROM customer_gold.customer_360
    UC->>P: which policies match this table's tags for this user?
    P-->>UC: filter_region (region tagged filter_key=region)<br/>mask_email (email tagged pii_type=email)
    UC->>RF: row_value = region
    RF-->>UC: TRUE only if a group of the user maps to the region
    UC->>MK: v = email
    MK-->>UC: j***@example.com
    UC-->>U: AMER rows, masked email
```

Policies are attached to the catalog and find columns through **governed tags**; the user's groups
decide whether they are in `TO` or `EXCEPT`. Contracts only tag columns, so a new table is protected
as soon as it is tagged ([ADR-0005](adr/0005-native-abac.md)).

## Data flow

`bronze` (raw, engineers only) → `silver` (cleaned, conformed, masked + filtered) → `gold`
(data products with contracts, masked + filtered). Bronze is protected by access, not masks.
