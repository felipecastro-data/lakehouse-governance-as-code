"""Governance scorecard (FR11). See docs/adr/0009-audit-views-and-scorecard.md.

Measured as the catalog owner, from information_schema and the two Phase 3 checks, so it sees every
tag and policy. The pipeline's `scorecard` task writes the result to tables in `<catalog>.audit`, which
the dashboard reads:

- `scorecard`: one row per metric per run (history)
- `findings`: drift and PII propagation findings per run (history)
- `table_inventory`: every domain table with its layer, owner and classification (replaced each run)

Coverage is measured on the curated layers (silver, gold). Bronze is protected by layer, not by tags
(ADR-0008), so it would only drag the ratios down; it is in the inventory, classified from lineage.
Grant changes and access to restricted data come from the admin-owned audit views when the dashboard
queries them, because the deployer can't read system tables.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from gov_engine.drift import QUERIES, DriftFinding, detect_drift
from gov_engine.lineage import PropagationReport, find_untagged_pii, protected_columns
from gov_engine.render import TAG_CLASSIFICATION, declared_policies
from gov_engine.spec import Spec

Query = Callable[[str], list[dict]]

TABLES_SQL = ("SELECT table_schema, table_name FROM {c}.information_schema.tables "
              "WHERE table_schema <> 'information_schema'")

# Output tables in <catalog>.audit, created by the scorecard task. Column order is the insert order.
TABLES = {
    "scorecard": ("run_id STRING, run_time TIMESTAMP, metric STRING, value DOUBLE, numerator BIGINT, "
                  "denominator BIGINT, description STRING",
                  "Governance scorecard history, one row per metric per pipeline run (ADR-0009)."),
    "findings": ("run_id STRING, run_time TIMESTAMP, check_name STRING, severity STRING, kind STRING, "
                 "securable STRING, detail STRING",
                 "Drift and PII propagation findings per pipeline run (ADR-0008, ADR-0009)."),
    "table_inventory": ("table_full_name STRING, table_schema STRING, domain STRING, layer STRING, owner STRING, "
                        "classification STRING, classified_by STRING, data_contract STRING, columns BIGINT, "
                        "classified_columns BIGINT, pii_columns BIGINT",
                        "Domain tables with owner and classification, as of the latest pipeline run (ADR-0009)."),
}


@dataclass(frozen=True)
class Metric:
    name: str
    value: float | None  # percent for pct_* metrics, else a count
    numerator: int | None
    denominator: int | None
    description: str

    def __str__(self) -> str:
        ratio = f" ({self.numerator}/{self.denominator})" if self.denominator is not None else ""
        value = "n/a" if self.value is None else f"{self.value:g}"
        return f"{self.name:<18} {value:>6}{ratio}  {self.description}"


@dataclass(frozen=True)
class Scorecard:
    metrics: list[Metric]
    drift: list[DriftFinding]
    propagation: PropagationReport
    inventory: list[dict]

    def finding_rows(self) -> list[dict]:
        """`findings` rows without run_id and run_time."""
        return [
            *({"check_name": "drift", "severity": f.severity, "kind": f.kind, "securable": f.securable,
               "detail": f.detail} for f in self.drift),
            *({"check_name": "pii_propagation", "severity": "critical", "kind": "column", "securable": f.target_column,
               "detail": str(f)} for f in self.propagation.findings),
        ]


def _pct(name: str, numerator: int, denominator: int, description: str) -> Metric:
    value = round(100.0 * numerator / denominator, 1) if denominator else None
    return Metric(name, value, numerator, denominator, description)


def _count(name: str, value: int, description: str) -> Metric:
    return Metric(name, float(value), None, None, description)


def build_scorecard(spec: Spec, env: str, query: Query) -> Scorecard:
    catalog = spec.catalog(env)
    cache: dict[str, list[dict]] = {}

    def q(sql: str) -> list[dict]:
        if sql not in cache:
            cache[sql] = query(sql)
        return cache[sql]

    drift = detect_drift(spec, env, q)
    propagation = find_untagged_pii(spec, env, q)

    schemas = {s: (domain, layer) for s, domain, layer in spec.layout.domain_schemas()}
    curated = {s for s, (_, layer) in schemas.items() if layer != spec.layout.layers[0]}
    tables = sorted((r["table_schema"], r["table_name"]) for r in q(TABLES_SQL.format(c=catalog))
                    if r["table_schema"] in schemas)

    table_tags: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for r in q(QUERIES["table_tags"].format(c=catalog)):
        table_tags[(r["schema_name"], r["table_name"])][r["tag_name"]] = r["tag_value"]
    columns: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in q(QUERIES["columns"].format(c=catalog)):
        columns[(r["table_schema"], r["table_name"])].append(r["column_name"])
    classified = {(r["schema_name"], r["table_name"], r["column_name"])
                  for r in q(QUERIES["column_tags"].format(c=catalog)) if r["tag_name"] == TAG_CLASSIFICATION}

    # PII columns: protected by a tag, raw PII inferred from lineage, or untagged but fed by PII.
    protected = protected_columns(spec, catalog, q)
    pii = {**propagation.inferred_raw_pii, **{f.target_column: f.pii_type for f in propagation.findings}, **protected}
    rank = spec.classification.rank
    pii_level = {name: t.classification for name, t in spec.classification.pii_types.items()}

    inventory = []
    for schema, table in tables:
        fq = f"{catalog}.{schema}.{table}"
        tags = table_tags[(schema, table)]
        types = [pii[f"{fq}.{c}"] for c in columns[(schema, table)] if f"{fq}.{c}" in pii]
        level, by = tags.get(TAG_CLASSIFICATION), "tag"
        if level is None and types:
            level, by = max((pii_level[t] for t in types), key=rank), "lineage"
        domain, layer = schemas[schema]
        inventory.append({
            "table_full_name": fq, "table_schema": schema, "domain": domain, "layer": layer,
            "owner": tags.get("owner"), "classification": level, "classified_by": by if level else None,
            "data_contract": tags.get("data_contract"), "columns": len(columns[(schema, table)]),
            "classified_columns": sum((schema, table, c) in classified for c in columns[(schema, table)]),
            "pii_columns": len(types),
        })

    groups = set(spec.access.principals.values())
    curated_tables = [t for t in inventory if t["table_schema"] in curated]
    curated_columns = [(s, t, c) for (s, t), cols in columns.items() if s in curated for c in cols]

    # A PII column is masked when the mask policy for its type exists on the catalog.
    must_mask = {p.name.removeprefix("mask_") for p in declared_policies(spec, env) if p.policy_type == "COLUMN_MASK"}
    live_masks = {r["policy_name"] for r in q(QUERIES["policies"].format(c=catalog))
                  if r["policy_type"] == "COLUMN_MASK"}
    curated_pii = {col: t for col, t in pii.items() if col.split(".")[1] in curated and t in must_mask}
    masked = [col for col, t in curated_pii.items() if col in protected and f"mask_{t}" in live_masks]

    critical = sum(f.severity == "critical" for f in drift)
    metrics = [
        _pct("pct_owned", sum(t["owner"] in groups for t in curated_tables), len(curated_tables),
             "silver/gold tables with an owner tag naming a declared group"),
        _pct("pct_classified", sum(c in classified for c in curated_columns), len(curated_columns),
             "silver/gold columns with a classification tag"),
        _pct("pct_pii_masked", len(masked), len(curated_pii),
             "silver/gold PII columns covered by a live mask policy"),
        _count("restricted_tables", sum(t["classification"] == "restricted" for t in inventory),
               "domain tables classified restricted (bronze from lineage)"),
        _count("drift_critical", critical, "critical drift findings (fail the drift task)"),
        _count("drift_warning", len(drift) - critical, "drift warnings"),
        _count("untagged_pii", len(propagation.findings), "silver/gold columns fed by PII without a pii_type tag"),
    ]
    return Scorecard(metrics, drift, propagation, inventory)
