# ADR-0007: Contract-first tables and an exempt pipeline identity

- **Status**: Accepted
- **Date**: 2026-10-27

## Context

Phase 2 adds data: synthetic bronze, silver and gold built by a job. Two problems appear.

1. **Unprotected first write.** If the pipeline creates tables, they exist untagged until the next
   governance run, so the first rows land with no masks or row filters.
2. **Policies apply to the pipeline too.** ABAC policies target `account users`, which includes the
   `gov-deployer` service principal that runs the job. Gold would be built from *masked*,
   *region-filtered* silver: empty or wrong.

## Decision

- **The contract is the DDL.** `gov_engine` renders `CREATE TABLE IF NOT EXISTS` from each contract
  (types, `NOT NULL`, primary key, comment) in a `tables` phase, before tags and policies. The
  pipeline job runs `governance_apply` as its first task, so every governed table exists and is
  tagged before data lands. Transforms only `INSERT OVERWRITE`.
- **A dedicated exemption group, `gov-pipeline-runners`.** It is listed in every policy's `EXCEPT`
  clause (via `unmasked_for` and the row filter `bypass`) and has **no grants**. Its only member is
  `gov-deployer`, added by a person, so the engine never grants itself an exemption.
- **Contract quality rules run as a job task** (`uniqueness`, `notNull`, `referentialIntegrity`)
  and fail the run on any violation.

## Consequences

- Protection is in place before the first row; there is no window of exposure.
- A changed contract does not alter an existing table (`IF NOT EXISTS`); the mismatch is drift for
  Phase 3 to report, never a silent rewrite.
- The exemption is visible and reviewable: one group in the policy files, one human-approved
  membership. Tests fail if a policy stops exempting it or if it gains grants.
- Enterprise variant: a separate pipeline service principal per environment, distinct from the
  deployer ([production deltas](../production-deltas.md)).

## Alternatives considered

- **Build gold from bronze** to avoid reading masked silver. Rejected: it duplicates cleaning logic
  and breaks the medallion contract.
- **Exempt the service principal by application id.** Rejected: the id would be hard-coded per
  environment in the policy files, and the engine could not tell a principal from a group.
