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
        J[governance_apply job<br/>runs gov_engine]
        UC[(Unity Catalog<br/>grants · tags · masks · row filters)]
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
    PROD --> GOV[governance<br/>functions · mapping tables]
    PROD --> AUD[audit<br/>views over system tables]
```

`gov_dev` has the same structure. Schema names are `<domain>_<layer>`, so a grant can target
"all gold schemas" or "all customer schemas" with a selector in `access_policy.yml`.

## Ownership split

| Concern | Managed by | Why |
|---|---|---|
| Catalogs, groups | Bootstrap (one-time) | Requires admin rights; rarely changes |
| Schemas, volumes, jobs, dashboards | Databricks Asset Bundle | Declarative infra with targets |
| Grants, tags, masks, row filters, mapping tables | `gov_engine` | Not expressible in bundles; policy must be one source of truth |

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

## Policy evaluation at query time

```mermaid
sequenceDiagram
    participant U as Analyst (gov-analysts-amer)
    participant UC as Unity Catalog
    participant RF as governance.filter_region
    participant MK as governance.mask_email
    participant CS as governance.can_see
    U->>UC: SELECT * FROM customer_gold.customer_360
    UC->>RF: row_value = region
    RF-->>UC: TRUE only if group mapped to region
    UC->>MK: v = email
    MK->>CS: can_see('confidential')
    CS-->>MK: FALSE (not in gov-pii-readers)
    MK-->>UC: j***@example.com
    UC-->>U: AMER rows, masked email
```

All mask functions delegate the "who may see this level" decision to `can_see()`, which is generated
from `classification.yml`. Changing who can unmask a level is a one-line YAML change.

## Data flow

`bronze` (raw, engineers only) → `silver` (cleaned, conformed, masked + filtered) → `gold`
(data products with contracts, masked + filtered). Bronze is protected by access, not masks.
