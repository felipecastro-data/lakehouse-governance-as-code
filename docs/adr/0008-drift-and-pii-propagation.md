# ADR-0008: Drift detection and PII propagation checks

- **Status**: Accepted
- **Date**: 2026-10-28

## Context

Phase 3 verifies that what runs in Unity Catalog is what Git declares (FR8), and that personal data
never flows into a column no policy masks (FR9). Things we found while checking `gov_dev`:

1. **information_schema is filtered by caller.** An admin who reads through `gov-platform-admins`
   sees only that group's grants. `abac_policy_definitions` shows nothing to that admin, and
   `SHOW POLICIES` fails with "no READ METADATA". The catalog owner (`gov-deployer`) sees everything.
2. **ABAC masks do not show up in `column_masks` / `row_filters`.** Those views list only per-column
   `SET MASK` / `SET ROW FILTER`.
3. **`system.access` is readable only by account admins** by default. `gov-deployer` cannot read
   `column_lineage` until someone grants it access.
4. **Bronze has untagged raw PII and no contract.** Lineage already links bronze to silver at the column
   level (`customers_raw.first_name` and `last_name` → `customers.full_name`).

## Decision

**Drift is pure SQL over `<catalog>.information_schema`, run as the catalog owner.** `gov_engine.drift`
compares the following with the spec:

- schemas (`layout.yml`)
- direct grants on the catalog, schemas and tables (`expand_grants`)
- columns and types (contracts)
- engine-owned tags (`declared_tags`)
- ABAC policies: type, target and `EXCEPT` list (`declared_policies`)

Any per-column mask or row filter is drift, because the engine protects data only through ABAC.

- **Critical** (fails the `drift` task): an undeclared grant, a missing or wrong `pii_type` or
  `filter_key` tag, a missing or altered policy, or an undeclared GRANT/DENY policy. These widen access
  or weaken protection.
- **Warning**: everything else, such as a missing grant, a contract/column mismatch, a table without a
  contract, or an undeclared tag. Apply re-adds missing state. It never revokes or deletes, so
  undeclared state stays drift until a person removes it.

**Bronze is a raw zone that is known to hold PII. We protect it by layer, not by contract.** Bronze
stays untagged and is reachable only by `gov-data-engineers`, admins and the pipeline. Its PII is
*inferred from lineage*: a bronze column that feeds a `pii_type` column is raw PII of that type.

**The PII propagation check walks column lineage downstream.** It starts from every protected column
(a `pii_type` tag, or a system `class.*` tag that a mask policy matches) and from every inferred bronze
column. It flags each silver or gold column that is fed by PII but is not protected. It keeps walking
through flagged columns, so a leak two layers deep shows up in one run. It uses only the latest run that
wrote each target table, within 30 days, so a column a transform stopped reading drops out.

**Both checks are pipeline tasks** (`drift`, `pii_propagation`) after `quality`. They are also CLI
commands (`gov_engine drift|pii-propagation --env`) that use the SQL Statement Execution API.

**An account admin grants `gov-deployer` `USE CATALOG` on `system` and `USE SCHEMA, SELECT` on
`system.access`.** This is a one-time human step like the exemption membership in
[ADR-0007](0007-contract-first-tables-and-pipeline-identity.md). It goes to the service principal, not
to a `gov-*` group, because the pipeline group must have no grants and auditors only read curated views
(FR10). Phase 4's audit views need the same access.

## Consequences

- A manual `GRANT` fails the next pipeline run. It keeps failing until someone reverts it or adds it
  to `access_policy.yml`.
- On a laptop, drift is only complete when run as the owner. As anyone else it reports grants and
  policies as missing that are actually there. The CLI help says so.
- Bronze is never tagged, so analysts never depend on it, and bronze contracts would only duplicate the
  silver ones. Inference only covers bronze columns that feed a tagged column. A raw PII column that
  feeds only untagged columns is caught by the system `class.*` tags (auto-classification), not by this
  check.
- System tables lag (about 15 minutes), so lineage from a run's own writes usually shows up in the next
  run's check.
- Policy drift compares type, target and exemptions, not the `MATCH` expression (`abac_policy_definitions`
  returns only matched column aliases). Every apply runs `CREATE OR REPLACE`, which resets the expression.

## Alternatives considered

- **Bronze contracts with `pii_type` tags.** Rejected: masks would then apply to engineers in bronze,
  which defeats the raw layer. The contracts would only describe the source system, and bronze is
  rewritten with `overwriteSchema`, which can drop tags.
- **Treat every bronze column as PII.** Rejected: every silver column (`customer_id`, `amount`) would be
  "fed by PII", so the check would only produce noise.
- **Auto-remediate drift (revoke undeclared grants).** Deferred: one wrong revoke in prod is worse than a
  failed job. Reporting comes first; remediation can be an explicit, reviewed command later.
