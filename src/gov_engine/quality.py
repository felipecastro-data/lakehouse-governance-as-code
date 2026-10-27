"""Data quality checks rendered from the `quality` section of each contract.

Every check is a query returning the number of violating rows; 0 means the rule holds.
"""

from __future__ import annotations

from dataclasses import dataclass

from gov_engine.spec import QualityRule, Spec, Table


@dataclass(frozen=True)
class Check:
    name: str
    sql: str


def _fq(catalog: str, t: Table) -> str:
    return f"{catalog}.{t.schema}.{t.name}"


def _check_sql(spec: Spec, catalog: str, t: Table, q: QualityRule) -> str:
    table, col = _fq(catalog, t), f"`{q.column}`"
    if q.rule == "uniqueness":
        return f"SELECT count(*) FROM (SELECT {col} FROM {table} GROUP BY {col} HAVING count(*) > 1)"
    if q.rule == "notNull":
        return f"SELECT count(*) FROM {table} WHERE {col} IS NULL"
    if q.rule == "referentialIntegrity":
        ref_contract, _, ref_col = q.references.rpartition(".")
        ref = next(r for r in spec.tables if r.contract_id == ref_contract)
        return (f"SELECT count(*) FROM {table} t LEFT ANTI JOIN {_fq(catalog, ref)} r "
                f"ON t.{col} = r.`{ref_col}`")
    raise ValueError(f"unknown rule {q.rule!r}")  # validate() rejects these first


def render_checks(spec: Spec, env: str) -> list[Check]:
    catalog = spec.catalog(env)
    return [
        Check(f"{t.schema}.{t.name}: {q.rule}({q.column})", _check_sql(spec, catalog, t, q))
        for t in spec.tables for q in t.quality
    ]
