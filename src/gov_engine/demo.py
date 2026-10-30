"""Scripted demo (`make demo ENV=dev`): declare -> apply -> enforce -> verify -> measure, against a deployed
environment, as the person running it. Read-only: it changes nothing.

Run it as the catalog owner or an admin to see the full drift and scorecard picture; the enforcement step
shows what *you* see, so run it again as an analyst to see the masks and the row filter from the other side.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

from gov_engine.render import declared_policies, render_plan
from gov_engine.scorecard import build_scorecard
from gov_engine.spec import Spec

Query = Callable[[str], list[dict]]

PII_SAMPLE = ("SELECT customer_id, full_name, email, phone, date_of_birth, national_id "
              "FROM {c}.customer_silver.customers ORDER BY customer_id LIMIT 3")
REGIONS = "SELECT region, count(*) AS customers FROM {c}.customer_gold.customer_360 GROUP BY region ORDER BY region"
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

    step(4, "VERIFY - drift, PII propagation and erasure")
    card = build_scorecard(spec, env, q)
    critical = sum(f.severity == "critical" for f in card.drift)
    log(f"  drift:           {critical} critical, {len(card.drift) - critical} warning")
    for f in card.drift[:5]:
        log(f"    {f}")
    log(f"  pii propagation: {card.propagation.edges} lineage edges, "
        f"{len(card.propagation.inferred_raw_pii)} raw PII columns inferred, "
        f"{len(card.propagation.findings)} untagged PII columns")
    log(f"  erasure:         {card.erasure.requests} requests, {len(card.erasure.tables)} tables in scope, "
        f"{sum(card.erasure.residual.values())} residual rows, {len(card.erasure.gaps)} gaps")

    step(5, "MEASURE - governance scorecard")
    for m in card.metrics:
        log(f"  {m}")
    log("")
    return 0
