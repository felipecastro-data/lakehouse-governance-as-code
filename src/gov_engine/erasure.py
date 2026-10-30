"""Right to erasure (FR12). See docs/adr/0010-right-to-erasure.md.

A request is recorded in `<catalog>.governance.<register>` (privacy.yml) as the SHA-256 of the subject
key, never the key itself, and then erased from every layer:

- Scope: every table in a domain schema that has the subject key column, read from information_schema,
  so a new table is covered without a code change. Contracts must carry the key (validated in CI).
- Gaps: column lineage from a scope table into a domain table *without* the key. The subject's data
  may have flowed there and can't be found by key, so the check fails until the table carries it.
- Re-ingestion: sources deliver the same people again (here the generator rebuilds bronze on every
  run), so the pipeline re-applies the whole register right after ingestion, before silver is built.
- Physical deletion: DELETE is logical in Delta. The erase job runs REORG ... APPLY (PURGE) to rewrite
  the files; the old files stay reachable through time travel until VACUUM removes them after the
  retention period (7 days by default; predictive optimization runs it on managed tables).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from gov_engine.lineage import LINEAGE_SQL, LOOKBACK_DAYS
from gov_engine.render import GOVERNANCE_SCHEMA
from gov_engine.spec import Spec

Query = Callable[[str], list[dict]]

_ID = re.compile(r"^[A-Za-z0-9_.\-]{1,64}$")

SCOPE_SQL = ("SELECT DISTINCT table_schema, table_name FROM {c}.information_schema.columns "
             "WHERE column_name = '{key}' AND table_schema IN ({schemas})")

# Output table in <catalog>.audit, written by the erasure job: evidence for auditors. Column order is the insert order.
LOG_TABLE = ("erasure_log",
             "run_id STRING, run_time TIMESTAMP, request_id STRING, table_full_name STRING, rows_deleted BIGINT",
             "Rows deleted per table by the right_to_erasure job and the pipeline re-apply (ADR-0010).")


def register(spec: Spec, env: str) -> str:
    return f"{spec.catalog(env)}.{GOVERNANCE_SCHEMA}.{spec.erasure.register}"


def _hashed(column: str) -> str:
    return f"sha2(CAST(`{column}` AS STRING), 256)"


def _erased(spec: Spec, env: str) -> str:
    """WHERE clause matching rows of every subject in the register."""
    return f"{_hashed(spec.erasure.subject_key)} IN (SELECT subject_hash FROM {register(spec, env)})"


def scope(spec: Spec, env: str, query: Query) -> list[str]:
    """Domain tables holding the subject key, downstream layers first (gold, silver, bronze)."""
    catalog = spec.catalog(env)
    layer_of = {s: layer for s, _, layer in spec.layout.domain_schemas()}
    schemas = ", ".join(f"'{s}'" for s in sorted(layer_of))
    rows = query(SCOPE_SQL.format(c=catalog, key=spec.erasure.subject_key, schemas=schemas))
    order = {layer: i for i, layer in enumerate(reversed(spec.layout.layers))}
    return [f"{catalog}.{s}.{t}" for s, t in
            sorted({(r["table_schema"], r["table_name"]) for r in rows}, key=lambda st: (order[layer_of[st[0]]], st))]


def render_request(spec: Spec, env: str, request_id: str, subject_id: str) -> str:
    """Record a request; a request id that is already registered is left as it is."""
    for name, value in (("request id", request_id), ("subject id", subject_id)):
        if not _ID.match(value):
            raise ValueError(f"invalid {name} {value!r}: letters, digits, '_', '.', '-' only")
    return "\n".join([
        f"MERGE INTO {register(spec, env)} r",
        f"USING (SELECT '{request_id}' AS request_id, sha2('{subject_id}', 256) AS subject_hash) s",
        "ON r.request_id = s.request_id",
        "WHEN NOT MATCHED THEN INSERT (request_id, subject_hash, requested_at, requested_by)",
        "  VALUES (s.request_id, s.subject_hash, current_timestamp(), current_user())",
    ])


def render_delete(spec: Spec, env: str, table: str) -> str:
    return f"DELETE FROM {table} WHERE {_erased(spec, env)}"


def render_purge(table: str) -> str:
    return f"REORG TABLE {table} APPLY (PURGE)"


@dataclass(frozen=True)
class ErasureReport:
    tables: list[str]
    requests: int
    residual: dict[str, int]  # table -> rows still matching a registered subject
    gaps: list[tuple[str, str]]  # (scope table, domain table it feeds that has no subject key)

    def findings(self) -> list[str]:
        return [
            *(f"[critical] {t}: {n} rows of erased subjects remain" for t, n in sorted(self.residual.items())),
            *(f"[critical] {tgt}: fed by {src} but has no subject key, so erasure can't reach it"
              for src, tgt in self.gaps),
        ]


def check_erasure(spec: Spec, env: str, query: Query) -> ErasureReport:
    catalog = spec.catalog(env)
    tables = scope(spec, env, query)
    requests = int(query(f"SELECT count(*) AS n FROM {register(spec, env)}")[0]["n"])
    residual: dict[str, int] = {}
    if requests and tables:
        sql = "\nUNION ALL\n".join(f"SELECT '{t}' AS table_full_name, count(*) AS n FROM {t} WHERE {_erased(spec, env)}"
                                   for t in tables)
        residual = {r["table_full_name"]: int(r["n"]) for r in query(sql) if int(r["n"])}

    domain = {s for s, _, _ in spec.layout.domain_schemas()}
    in_scope = set(tables)
    gaps = sorted({
        (r["source_table_full_name"], r["target_table_full_name"])
        for r in query(LINEAGE_SQL.format(c=catalog, days=LOOKBACK_DAYS))
        if r["source_table_full_name"] in in_scope and r["target_table_full_name"] not in in_scope
        and r["target_table_full_name"].split(".")[1] in domain
    })
    return ErasureReport(tables, requests, residual, gaps)


def report_erasure(report: ErasureReport, log=print) -> int:
    """Print the erasure report; 1 if a registered subject is still present or a table can't be erased."""
    for line in report.findings():
        log(line)
    log(f"erasure: {report.requests} requests, {len(report.tables)} tables in scope, "
        f"{sum(report.residual.values())} residual rows, {len(report.gaps)} gaps")
    return 1 if report.residual or report.gaps else 0
