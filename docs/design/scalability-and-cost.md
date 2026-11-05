# Scalability and cost

How the governance program behaves as data, metadata and requests grow, and what it costs to run.
Every number here is measured in this workspace (Free Edition, AWS us-east-2) from the Jobs run
history and `system.billing.usage`, unless it is marked as an estimate. Prices are the list prices in
`system.billing.list_prices`. Free Edition doesn't charge them, but it caps daily compute, so they are
the right unit for comparing choices.

## 1. Two cost centres

The program has two kinds of work, and they scale with different things:

| Work | Tasks | Scales with |
|---|---|---|
| **Data** | `bronze`, `erasure`, `silver_*`, `gold_*`, `quality` | Rows |
| **Governance** | `governance` (apply), `drift`, `pii_propagation`, `erasure_check`, `scorecard` | Metadata (tables, columns, grants, lineage edges), not rows |

The design keeps governance cost tied to metadata. Masks and filters are catalog-wide ABAC policies
matched by tags, grants sit on schemas, and the checks read `information_schema` and lineage
instead of the data. `erasure` and `erasure_check` are the exception: they scan the rows of the tables
in scope (§3.4).

## 2. Measured runtime and cost

### Pipeline at the default size (5k customers / 50k orders)

Medians of the five scheduled dev runs, 2026-10-31 → 2026-11-04 (whole runs: 348–603 s, median 352 s):

| Task | Median | Kind |
|---|---:|---|
| governance (apply: 81 statements + groups and tags over REST) | 109 s | Governance |
| bronze | 39 s | Data |
| erasure (register re-applied to 5 tables) | 38 s | Data |
| silver_customers / silver_orders / gold_customer_360 | 21 / 21 / 19 s | Data |
| quality | 21 s | Data |
| drift / pii_propagation / erasure_check (run in parallel) | 31 / 31 / 31 s | Governance |
| scorecard | 41 s | Governance |

At this size every data task is close to the ~20 s floor of a serverless task: start-up, Python
environment and writing to Unity Catalog. Data volume barely shows. The critical path is roughly
half governance.

### Billed compute

| Unit of work | DBU | List price | Source |
|---|---:|---:|---|
| One pipeline run (`lakehouse-pipeline` 0.84–0.98 + `governance-apply` child 0.20) | **~1.1** | **~$0.39** | 5 runs, `usage_metadata.job_run_id` |
| Daily dev schedule, per month | ~33 | ~$11.70 | 5.57 DBU over 5 days, all jobs SKU |
| Governance overhead per run (apply + 3 checks + scorecard, by task time) | ~0.6 | ~$0.21 | Task-time share of the run's DBUs (estimate) |
| One right-to-erasure request (erase 64 s + verify 27 s) | 0.32 | $0.11 | Run 998550237707306 |
| Prod promotion (dev + test pipelines, prod deploy) | ~2.4 | ~$0.85 | 2 × run + apply (estimate, [ADR-0011](../adr/0011-three-stage-promotion.md)) |
| Scorecard dashboard viewing session (2X-Small warehouse, 10 min auto-stop) | ~0.7 | ~$0.47 | Days with a single dashboard session billed 0.68–0.71 SQL DBU |
| Predictive optimization (auto OPTIMIZE / VACUUM) | ~0.1 / day | ~$0.04 | 0.54 DBU over 5 days |
| Storage | negligible | < $0.01 / day | `DEFAULT_STORAGE` at $0.023 / DSU |

Jobs serverless is $0.35/DBU and serverless SQL is $0.70/DBU (list prices, us-east-2, premium tier).

Choices that keep this low:

- **Only dev runs on a schedule.** test runs as a promotion step and prod on demand. Running all three
  daily would triple the ~$11.70/month.
- **The scorecard is computed by the pipeline** (41 s of jobs compute at $0.35/DBU), not by
  dashboard queries. The dashboard only reads one small `audit` table, so a viewing session costs the
  warehouse's minimum billed window and nothing more.
- **Checks read metadata.** Drift is 12 queries against `information_schema`, the same whether a
  table holds 50k rows or 50M.

## 3. How each control scales

### 3.1 ABAC policies: grow with PII types, not tables

| Grows with | Today | At 500 tables / 5,000 columns |
|---|---|---|
| Policies = PII types + row filters | 8 (7 masks + 1 filter) | Still 8, unless a new PII type is added |
| Per-column `SET MASK` alternative | 9 bindings | One per PII column, each a drift risk ([ADR-0005](../adr/0005-native-abac.md)) |

A new table gets masking from its contract's tags alone; no policy changes. Query-time cost is the
mask UDF applied to masked columns of the rows actually read, plus a semi-join to the small
`governance.region_access` table for the row filter. Both are proportional to the query, not to the number of
policies. The pipeline identity is exempt, so building silver and gold pays none of it.

### 3.2 Apply: grows with columns

Apply renders 81 statements today: 32 grants, 27 tags, 8 policies, 8 functions, 3 tables and 3 reference
rows. Grants are per schema selector, so new tables add **zero** grants. Tags are one `ALTER` per
classified column and run on every apply (idempotent), so apply time grows linearly with contract
columns. At ~1 s per statement on a serverless SQL session, 5,000 columns would add over an hour.
Next steps when that matters:

1. Apply only the diff: drift already computes declared minus actual, so apply can run just the
   missing statements.
2. Run apply per domain in parallel, since domains share no objects.

### 3.3 Drift and PII propagation: grow with metadata

- **Drift** runs 12 `information_schema` queries per catalog and compares in memory, so it is linear
  in grants + columns + tags. That is comfortable to ~10⁵ columns; beyond that, filter by domain
  schema and run per domain.
- **PII propagation** walks `system.access.column_lineage` downstream from tagged columns: 26 edges
  today, linear in edges. Lineage keeps a year of history, so at scale the view is filtered to a
  recent window (the latest write is what matters).
- **Scorecard** reuses the outputs of those checks plus one `information_schema.tables` query.

### 3.4 Right to erasure: grows with rows × requests

Each pipeline run re-applies the whole register to every table in scope:
`DELETE … WHERE sha2(customer_id) IN (SELECT subject_hash FROM erasure_requests)`. That is a full
scan with a hash per row, plus a broadcast semi-join whose size is the number of requests.
`erasure_check` repeats the scan to count residual rows. This is the one governance control that grows
with data, and [ADR-0010](../adr/0010-right-to-erasure.md) accepts it at this scale. The measured
numbers at 200× rows are in §4.

When it stops being acceptable:

1. Apply the register to **newly ingested rows only** (the bronze batch), plus a full pass when a
   request is registered.
2. Persist the hashed key as a column (or use liquid clustering on `customer_id`), so deletes prune
   files instead of hashing every row.
3. Deletion vectors already make `DELETE` cheap to write. `REORG … APPLY (PURGE)` rewrites files, so
   batch requests into one daily purge rather than one job run per request ($0.11 each, §2).

## 4. Scale run: 1M customers / 10M orders

Run 573093414186903 in `gov_dev` on 2026-11-05, started with `make pipeline-scale ENV=dev`, which sets
the job parameters (`customers=1000000`, `orders=10000000`). It is the same pipeline, contracts and
checks as the daily run, with 200× the rows. **All 11 tasks green in 690 s** (11.5 min).

| Rows | Default run | Scale run |
|---|---:|---:|
| Bronze customers / orders | 5,169 / 50,260 | 1,030,343 / 10,050,077 |
| Silver customers / orders (deduplicated, cleaned) | 4,984 / 48,857 | 995,090 / 9,753,515 |
| Gold `customer_360` | 4,984 | 995,090 |
| Erased subject's rows removed after re-ingestion | 1 customer + orders | 1 customer + 12 orders |

| Task | Default (median) | Scale | Change |
|---|---:|---:|---|
| governance | 109 s | 66 s | Metadata only; varies with REST latency, not rows |
| bronze | 39 s | 421 s | Synthetic generation in single-threaded driver Python (customers 41 s, orders 350 s) |
| erasure (full register over 5 tables) | 38 s | 40 s | Flat |
| silver_customers / silver_orders / gold | 21 / 21 / 19 s | 20 / 24 / 20 s | Flat |
| quality (uniqueness, referential integrity) | 21 s | 22 s | Flat |
| drift / pii_propagation / erasure_check | 31 / 31 / 31 s | 32 / 31 / 30 s | Flat |
| scorecard | 41 s | 42 s | Flat |

Scorecard for the scale run: owned 100% (3/3), classified 100% (24/24), PII masked 100% (9/9),
0 critical drift, 0 untagged PII, 0 erasure residual rows.

What it shows:

- **Every control holds at volume.** Quality rules, drift, lineage-based PII propagation and erasure
  verification all pass on 10M orders with the same results as on 50k.
- **Governance cost doesn't move with rows.** Drift, PII propagation, erasure check and scorecard stayed within ±3 s, and apply ran faster than its median (66 s vs 109 s), which tracks REST latency. They read
  metadata, as §1 claims.
- **Even the row-scanning controls are cheap at 10M.** Erasure's hash-and-semi-join over five tables
  took 40 s. The incremental design in §3.4 is for ~10⁹ rows or a large register, not for this size.
- **The only bottleneck is the test-data generator.** It runs single-threaded on the driver so the
  data stays seeded and reproducible. A real source would land files in parallel, and Spark-native
  generation (`spark.range`) would remove it if bigger scale tests were needed.
- **Compute cost:** about 2 DBU (~$0.70 at list price), estimated from task time against the 1.1 DBU
  of a default run. The extra ~330 s is all in bronze. Billing records arrive in
  `system.billing.usage` a few hours after the run.

The next scheduled dev run (06:00 UTC) goes back to the default sizes: bronze overwrites, and silver
and gold use `INSERT OVERWRITE`.

## 5. Enterprise cost delta

What changes in cost, not just in design, when moving to the setup in
[production-deltas.md](../production-deltas.md):

| Area | Free Edition (this project) | Enterprise | Cost effect |
|---|---|---|---|
| Environments | 3 catalogs, 1 workspace; only dev scheduled | Workspace per environment | No platform fee per workspace; compute is the same per run. Networking (Private Link endpoints) is billed per endpoint-hour and per GB |
| Compute | Serverless jobs, list $0.35/DBU, no charge | Serverless or job clusters on committed-use discounts | Same DBUs per run; committed use lowers the rate |
| Schedule | dev daily only | All environments daily; prod at data SLA cadence | ~1.1 DBU per run per environment at this size; data tasks then dominate as volume grows |
| Classification | Declared in contracts | Automated data classification scans | Extra serverless DBUs per scanned table; incremental scans keep it proportional to new tables |
| Audit | Views + dashboard on a shared 2X-Small warehouse | SIEM delivery of audit logs; dedicated monitoring warehouse | Log storage and SIEM ingest pricing; warehouse sized for auditors' concurrency |
| Encryption | Platform keys | Customer-managed keys | KMS key and request charges (small) |
| Erasure | Register re-applied in full on every run | Incremental application, daily batched purge | Cost moves from per-run full scans to proportional to new data plus requests |

The governance layer itself (apply, drift, PII propagation, scorecard) stays a small fixed overhead per
run, about 0.6 DBU measured here. It grows with metadata, which a governed estate keeps in check by
design, and not with data volume.
