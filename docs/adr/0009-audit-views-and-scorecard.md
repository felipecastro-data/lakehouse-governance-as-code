# ADR-0009: Audit views and the governance scorecard

- **Status**: Accepted
- **Date**: 2026-10-29

## Context

Phase 4 adds observability. Auditors must be able to answer "who changed access" and "who read
sensitive data" without direct access to `system.access.audit` (FR10). A scorecard dashboard must show
% owned, % classified, % PII masked, restricted access, grant changes and drift (FR11).

Constraints found in Phases 3 and 4:

1. **Only account admins can read `system.access`, and nobody can grant it further** (ADR-0008). The
   deployer can't read system tables, so it can't create a view over them that works.
2. **information_schema is filtered by caller.** Only the catalog owner (`gov-deployer`) sees every tag
   and policy, so coverage must be measured as the deployer.
3. **The audit log is noisy.** `gov_engine` re-applies every declared grant and runs
   `CREATE OR REPLACE POLICY` on every apply, so most `updatePermissions` and `updatePolicy` events are
   the engine restating the spec.
4. **Table reads are in `system.access.table_lineage`**, with the principal and the statement. A row with
   no target is a read.

## Decision

**Audit views: SQL in the repo, created and owned by an account admin.** `src/audit/views.sql` defines
these views in `<catalog>.audit`:

| View | Source | Rows |
|---|---|---|
| `column_lineage` | `system.access.column_lineage` | Column lineage into the catalog (ADR-0008) |
| `table_access` | `system.access.table_lineage` | One read or write per table, principal and statement. `by_pipeline` marks the deployer |
| `grant_changes` | `system.access.audit` (`updatePermissions`) | One GRANT/REVOKE per principal. `by_engine` marks gov_engine applies |
| `policy_changes` | `system.access.audit` (`create/update/deletePolicy`) | ABAC policy changes and their `EXCEPT` lists |
| `access_denied` | `system.access.audit` (401/403) | Requests on the catalog that Unity Catalog refused |

An account admin runs `make audit-views ENV=<env>` once per environment, and again after the file
changes. The command looks up the catalog owner, fills it in as the deployer, and runs the statements
under the admin's CLI login. The views read `system.*` with the owner's access, so readers only need
`SELECT` on the view. `gov-auditors` get it from their existing `audit` schema grant. The only explicit
grant is `SELECT` on `column_lineage` to the deployer, for the PII propagation check.

**Scorecard: a pipeline task measures it as the deployer and writes tables to `audit`.** The
`scorecard` task runs after `drift` and `pii_propagation` with `run_if: ALL_DONE`, so a failed check is
recorded too. `gov_engine.scorecard` reuses both checks and writes the following:

| Table | Content |
|---|---|
| `audit.scorecard` | One row per metric per run (history) |
| `audit.findings` | Drift and PII propagation findings per run (history) |
| `audit.table_inventory` | Each domain table's layer, owner and classification (replaced each run) |

Metrics:

- `pct_owned`: silver/gold tables with an `owner` tag that names a declared group.
- `pct_classified`: silver/gold columns with a `classification` tag.
- `pct_pii_masked`: silver/gold PII columns, tagged or caught by the propagation check, covered by a
  live mask policy for their PII type.
- `restricted_tables`: domain tables classified restricted.
- `drift_critical`, `drift_warning`, `untagged_pii`: counts from the Phase 3 checks.

Coverage is measured on silver and gold only. Bronze is protected by layer and has no tags (ADR-0008).
In the inventory, bronze tables are classified from lineage, using the PII types inferred for their
columns, so reads of raw restricted data still count as restricted access.

**Dashboard: an AI/BI dashboard in the bundle.** `resources/governance_scorecard.dashboard.yml` deploys
`src/dashboards/governance_scorecard.lvdash.json`, with `dataset_catalog` set to the environment's
catalog and `dataset_schema: audit`. It has two pages:

- **Scorecard**: KPIs, coverage and drift trends, and the latest findings.
- **Access and changes**: grant changes per day (engine vs manual), reads of restricted tables, manual
  grant changes, denied requests and the table inventory.

The dashboard uses `embed_credentials: false`, so every viewer queries with their own grants. The
bundle gives `gov-auditors` `CAN_VIEW`. Restricted access and grant changes are computed when a viewer
queries, by joining the admin-owned views with `table_inventory`. They are not stored in `scorecard`,
because the deployer can't read the views.

## Consequences

- An auditor sees the dashboard and the audit views and nothing else. Their grants are `USE CATALOG`
  and `USE SCHEMA`/`SELECT` on `audit`. They have no path to `system.*` and none to domain data. A
  consistency test checks the dashboard reads only `audit` objects.
- Each environment needs an account admin to run `make audit-views` before the "Access and changes"
  page has data. Prod needs it before its first pipeline run anyway (ADR-0008).
- View ownership must stay with the admin. If ownership moves to the deployer, the views stop
  working.
- The views follow the system tables' lag (about 15 minutes) and retention.
- `make scorecard` from a laptop is only correct as the catalog owner, like `make drift`.
- The drift check ignores the new `audit` objects. `audit` is a shared schema with no contracts, and
  the only grant on it goes to the catalog owner.

## Alternatives considered

- **The deployer creates the views.** Rejected: the deployer can't read `system.*`, so its views would
  fail at query time.
- **Persist grant changes and restricted reads in `scorecard`.** Rejected: that needs the deployer to
  read the audit views, which means another explicit grant. Computing them in the dashboard needs
  nothing new, and the numbers are always current.
- **A view over `information_schema` instead of `table_inventory`.** Rejected: information_schema
  filters rows by caller, so an auditor would see no tags on tables they can't use.
- **Embedded credentials on the dashboard.** Rejected: every viewer would see what the deployer sees.
  That breaks least privilege, and the dashboard would no longer show FR10 working.
