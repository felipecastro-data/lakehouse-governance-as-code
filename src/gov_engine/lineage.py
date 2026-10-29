"""PII propagation check using column lineage (FR9). See docs/adr/0008-drift-and-pii-propagation.md.

A column is *protected* when it carries a `pii_type` tag, or a system `class.*` tag that one of the
ABAC mask policies matches. Starting from protected columns, the check walks
`system.access.column_lineage` downstream and flags every column in a curated layer (silver, gold)
that is fed by PII but is not protected: personal data leaking into a column no policy masks.

Bronze is the raw landing zone. It has no contracts and no tags; its PII is contained by access
(engineers only). Its columns become PII *sources* by inference: a bronze column that feeds a
`pii_type` column is raw PII of that type, so anything else it feeds is checked too.

Lineage reflects the latest run that wrote each target table (within LOOKBACK_DAYS), so a column a
transform no longer reads stops being reported. System tables lag, so a change shows up a run later.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from gov_engine.render import TAG_PII_TYPE
from gov_engine.spec import Spec

LOOKBACK_DAYS = 30

LINEAGE_SQL = """SELECT source_table_full_name, source_column_name, target_table_full_name, target_column_name
FROM (
  SELECT *, max_by(coalesce(entity_run_id, event_id), event_time)
              OVER (PARTITION BY target_table_full_name) AS latest_run
  FROM system.access.column_lineage
  WHERE target_table_catalog = '{c}' AND source_table_catalog = '{c}' AND source_column_name IS NOT NULL
    AND event_date >= date_sub(current_date(), {days})
)
WHERE coalesce(entity_run_id, event_id) = latest_run
GROUP BY ALL"""

TAGS_SQL = ("SELECT schema_name, table_name, column_name, tag_name, tag_value FROM {c}.information_schema.column_tags "
            "WHERE tag_name = 'pii_type' OR tag_name LIKE 'class.%'")


@dataclass(frozen=True)
class PropagationFinding:
    source_column: str
    target_column: str
    pii_type: str

    def __str__(self) -> str:
        return (f"[critical] {self.target_column} is fed by {self.pii_type} PII from {self.source_column} "
                "but has no pii_type tag")


@dataclass(frozen=True)
class PropagationReport:
    findings: list[PropagationFinding]
    inferred_raw_pii: dict[str, str]  # raw (bronze) column -> pii_type, inferred from lineage
    edges: int


def protected_columns(spec: Spec, catalog: str, query: Callable[[str], list[dict]]) -> dict[str, str]:
    """{catalog.schema.table.column: pii_type} for columns an ABAC mask policy matches."""
    by_system_tag = {tag: pii.name for pii in spec.classification.pii_types.values() for tag in pii.system_tags}
    protected = {}
    for r in query(TAGS_SQL.format(c=catalog)):
        fq = f"{catalog}.{r['schema_name']}.{r['table_name']}.{r['column_name']}"
        if r["tag_name"] == TAG_PII_TYPE:
            protected[fq] = r["tag_value"]
        elif r["tag_name"] in by_system_tag:
            protected.setdefault(fq, by_system_tag[r["tag_name"]])
    return protected


def find_untagged_pii(spec: Spec, env: str, query: Callable[[str], list[dict]]) -> PropagationReport:
    catalog = spec.catalog(env)
    raw_schemas = {s for s, _, layer in spec.layout.domain_schemas() if layer == spec.layout.layers[0]}
    protected = protected_columns(spec, catalog, query)

    downstream: dict[str, set[str]] = defaultdict(set)
    edges = 0
    for r in query(LINEAGE_SQL.format(c=catalog, days=LOOKBACK_DAYS)):
        src = f"{r['source_table_full_name']}.{r['source_column_name']}"
        tgt = f"{r['target_table_full_name']}.{r['target_column_name']}"
        if src != tgt:
            downstream[src].add(tgt)
            edges += 1

    def is_raw(column: str) -> bool:
        return column.split(".")[1] in raw_schemas

    inferred = {
        src: protected[tgt]
        for src, targets in sorted(downstream.items()) if is_raw(src) and src not in protected
        for tgt in sorted(targets) if tgt in protected
    }

    # Breadth-first from every PII source; an unprotected column fed by PII carries that PII further.
    pii: dict[str, str] = {**protected, **inferred}
    queue = deque(sorted(pii))
    findings = []
    while queue:
        src = queue.popleft()
        for tgt in sorted(downstream.get(src, ())):
            if tgt in protected or is_raw(tgt):
                continue
            findings.append(PropagationFinding(src, tgt, pii[src]))
            if tgt not in pii:
                pii[tgt] = pii[src]
                queue.append(tgt)
    return PropagationReport(sorted(set(findings), key=lambda f: (f.target_column, f.source_column)), inferred, edges)
