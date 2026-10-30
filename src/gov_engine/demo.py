"""Scripted demo (`make demo ENV=dev`): declare -> apply -> enforce -> verify -> measure, against a deployed
environment, as the person running it. Read-only: it changes nothing.

The enforcement step shows what *you* see, so run it again as an analyst or a PII reader to see the masks and
the row filter from the other side. Verification and the scorecard are read from what the pipeline recorded
in `<catalog>.audit`, measured as the catalog owner (docs/adr/0009).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from gov_engine.render import declared_policies, render_plan
from gov_engine.spec import Spec

Query = Callable[[str], list[dict]]

PII_SAMPLE = ("SELECT customer_id, full_name, email, phone, date_of_birth, national_id "
              "FROM {c}.customer_silver.customers ORDER BY customer_id LIMIT 3")
REGIONS = "SELECT region, count(*) AS customers FROM {c}.customer_gold.customer_360 GROUP BY region ORDER BY region"
METRIC_ORDER = ["pct_owned", "pct_classified", "pct_pii_masked", "restricted_tables", "drift_critical",
                "drift_warning", "untagged_pii", "erasure_requests", "erasure_residual"]
WHOAMI = "SELECT current_user() AS user, {checks}"


def _table(rows: list[dict], log: Callable[[str], None]) -> None:
    if not rows:
        log("  (no rows visible)")
        return
    cols = list(rows[0])
    width = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    log("  " + "  ".join(c.ljust(width[c]) for c in cols))
    log("  " + "  ".join("-" * width[c] for c in cols))
    for r in rows:
        log("  " + "  ".join(str(r[c]).ljust(width[c]) for c in cols))


def run_demo(spec: Spec, env: str, query: Query, log: Callable[[str], None] = print) -> int:
    catalog = spec.catalog(env)
    cache: dict[str, list[dict]] = {}

    def q(sql: str) -> list[dict]:
        if sql not in cache:
            cache[sql] = query(sql)
        return cache[sql]

    def step(n: int, title: str) -> None:
        log(f"\n{'=' * 78}\n {n}. {title}\n{'=' * 78}")

    step(1, "DECLARE - policy lives in governance/*.yml")
    pii = sum(bool(c.pii_type) for t in spec.tables for c in t.columns)
    log(f"  {len(spec.layout.environments)} environments, {len(spec.layout.domains)} domains, "
        f"{len(spec.layout.all_schemas())} schemas per catalog")
    log(f"  {len(spec.tables)} data contracts, {sum(len(t.columns) for t in spec.tables)} columns, {pii} PII columns")
    log(f"  {len(spec.classification.levels)} classification levels, {len(spec.classification.pii_types)} PII types, "
        f"{len(spec.access.principals)} groups, {len(spec.access.grants)} grant rules")

    step(2, f"APPLY - the engine renders idempotent Unity Catalog SQL for {catalog}")
    plan = render_plan(spec, env)
    for phase, n in Counter(s.phase for s in plan).items():
        log(f"  {phase:<15} {n:>3} statements")
    policies = declared_policies(spec, env)
    log(f"  {len(policies)} catalog-wide ABAC policies: {', '.join(p.name for p in policies)}")

    step(3, "ENFORCE - what you see right now")
    checks = ", ".join(f"is_account_group_member('{g}') AS `{p}`"
                       for p, g in spec.access.principals.items() if p in ("pii_readers", "analysts_amer"))
    _table(q(WHOAMI.format(checks=checks)), log)
    log("\n  Silver customers (masked by ABAC unless you are exempt):")
    _table(q(PII_SAMPLE.format(c=catalog)), log)
    log("\n  Gold customer_360 by region (row filter by group -> region mapping):")
    _table(q(REGIONS.format(c=catalog)), log)

    # information_schema shows every grant and policy only to the catalog owner, so the checks are reported
    # as the pipeline's scorecard task measured them (as the deployer), not recomputed as the caller.
    step(4, "VERIFY - drift, PII propagation and erasure, as the pipeline measured them")
    latest = f"(SELECT max(run_time) FROM {catalog}.audit.scorecard)"
    metrics = q(f"SELECT run_id, run_time, metric, value, numerator, denominator, description "
                f"FROM {catalog}.audit.scorecard WHERE run_time = {latest}")
    metrics.sort(key=lambda m: METRIC_ORDER.index(m["metric"]) if m["metric"] in METRIC_ORDER else len(METRIC_ORDER))
    if not metrics:
        log("  no scorecard recorded yet: run the pipeline first (make pipeline)")
        return 1
    log(f"  pipeline run {metrics[0]['run_id']} at {metrics[0]['run_time']}")
    findings = q(f"SELECT check_name, severity, securable, detail FROM {catalog}.audit.findings "
                 f"WHERE run_id = '{metrics[0]['run_id']}' ORDER BY severity, check_name, securable")
    by_name = {m["metric"]: m for m in metrics}

    def count(name: str) -> str:
        value = by_name.get(name, {}).get("value")
        return "n/a" if value is None else f"{float(value):g}"

    log(f"  drift:           {count('drift_critical')} critical, {count('drift_warning')} warning")
    log(f"  pii propagation: {count('untagged_pii')} untagged PII columns")
    log(f"  erasure:         {count('erasure_requests')} requests, {count('erasure_residual')} residual rows or gaps")
    for f in findings[:5]:
        log(f"    [{f['severity']}] {f['check_name']} {f['securable']}: {f['detail']}")

    step(5, "MEASURE - governance scorecard")
    for m in metrics:
        ratio = f"({m['numerator']}/{m['denominator']})" if m["denominator"] not in (None, "") else ""
        log(f"  {m['metric']:<18} {float(m['value']) if m['value'] is not None else 'n/a':>6g} {ratio:<8} "
            f"{m['description']}")
    log("")
    return 0
