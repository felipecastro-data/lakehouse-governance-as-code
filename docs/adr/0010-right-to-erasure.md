# ADR-0010: Right to erasure

- **Status**: Accepted
- **Date**: 2026-10-30

## Context

GDPR Art. 17 (and CCPA's right to delete) require removing a person's data on request, from every
copy, and proving it was done (FR12). In this lakehouse a customer lives in five tables across three
layers (`customers_raw`, `orders_raw`, `customers`, `orders`, `customer_360`), and new tables appear
as the program grows.

Constraints:

1. **Sources re-deliver.** Bronze is rebuilt on every run (here by the generator; in real life by
   a CDC feed or a nightly extract), so a one-off DELETE is undone by the next ingestion.
2. **Delta deletes are logical.** DELETE writes deletion vectors or new files; the old files, and the
   subject's rows in them, stay reachable through time travel until VACUUM removes them.
3. **The register itself is personal data.** A list of erased customer ids is a list of people who
   asked to be forgotten.
4. **Only the deployer writes in prod** (FR3). Nobody, not even the steward who approves a request,
   may run a DELETE by hand.
5. **Scope can't be a hard-coded table list.** It goes stale as soon as someone adds a table.

## Decision

**Declare the subject key once** in `governance/privacy.yml` (`subject_key: customer_id`). CI rejects
any data contract with a PII column that lacks the key, so every governed table stays erasable.

**Register requests as hashes.** The `right_to_erasure` job MERGEs `(request_id, sha2(subject_id), requested_at,
requested_by)` into `<catalog>.governance.erasure_requests`, which `gov_engine` creates on apply and never
overwrites. The raw id never lands in a table. Re-running a request id changes nothing.

**Find the scope at run time.** Every table in a domain schema with the subject key column, from
`information_schema.columns`, downstream layers first (gold, silver, bronze). A table added tomorrow is in
scope without a code change.

**Check scope against lineage.** A domain table that column lineage shows is fed by a scope table, but
has no subject key, is a *gap*: the subject's data may be there and can't be found. Gaps fail the check.

**Erase, purge, prove.** The job deletes `WHERE sha2(customer_id) IN (register)` from every table in
scope, runs `REORG TABLE ... APPLY (PURGE)` on the tables it changed so the current files no longer hold
the rows, and appends rows-deleted per table to `audit.erasure_log`, which auditors can read. A `verify`
task then requires zero matching rows everywhere and no gaps.

**Re-apply on every ingestion.** The pipeline's `erasure` task runs the same delete right after
`bronze`, before silver is built, and `erasure_check` verifies after the quality checks. The scorecard
records `erasure_requests` and `erasure_residual`.

**Separation of duties.** The job runs as its owner, the deployer. `gov-data-engineers` have
`CAN_MANAGE_RUN` on it: they can start a run for a request their domain steward approved
([RACI](../raci.md)), but they can't modify prod tables themselves.

## Consequences

- One command erases a person from every layer: `make erase ENV=dev REQUEST=DSR-0001 SUBJECT=C000042`.
- The evidence trail is complete without system-table access: request in the register (hashed), rows
  per table in `audit.erasure_log`, the job's writes in `audit.table_access`, the result on the scorecard.
- `requested_by` in the register is the job's identity (the deployer). The person who started the run
  is in the job's run history; a DSR tool would pass its ticket id as the request id.
- **Time travel still holds the rows until VACUUM.** Old file versions are retained for the table's
  `delta.deletedFileRetentionDuration` (7 days by default); predictive optimization VACUUMs managed tables
  automatically. Erasure is complete when that window passes, which fits the one-month response period
  in GDPR Art. 12(3). Shorter retention is a per-table property if a regulator requires it.
- **SHA-256 of a sequential id can be brute-forced.** It keeps the raw id out of tables and logs, but
  is pseudonymization, not anonymization. Production would use a keyed hash (HMAC with a secret in a
  secret scope). See [production deltas](../production-deltas.md).
- Aggregates that don't carry the key (a future `segments` table) must either carry it or be rebuilt
  from erased sources; the gap check makes that decision explicit instead of silent.
- Erasure applies to the whole register on every run, so its cost grows with the number of requests.
  At this scale it is a semi-join per table; at enterprise scale the register would be partitioned and
  applied incrementally.
