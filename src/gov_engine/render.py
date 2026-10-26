"""Render a validated Spec into idempotent Unity Catalog SQL for one environment."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from gov_engine.spec import PRIVILEGES, Grant, Spec

GOVERNANCE_SCHEMA = "governance"
MANAGED_BY = "Managed by gov_engine - do not edit by hand"

# Order matters: row filter functions read the mapping tables, and masks/filters need the functions.
PHASES = ("reference_data", "functions", "grants", "tags", "masks", "row_filters")


@dataclass(frozen=True)
class Statement:
    phase: str
    sql: str
    target: str | None = None  # fully qualified table this needs; apply skips it if missing


def _ident(name: str) -> str:
    return f"`{name}`"


def _lit(value: str) -> str:
    if "'" in value or "\\" in value:
        raise ValueError(f"Refusing to render unsafe literal {value!r}")
    return f"'{value}'"


def _member(group: str) -> str:
    return f"is_account_group_member({_lit(group)})"


def _gov(catalog: str, obj: str) -> str:
    return f"{catalog}.{GOVERNANCE_SCHEMA}.{obj}"


def render_bootstrap(spec: Spec, env: str) -> list[Statement]:
    """One-time setup the bundle cannot do: the catalog itself."""
    catalog = spec.catalog(env)
    comment = _lit(f"{env} environment. {MANAGED_BY}")
    return [Statement("bootstrap", f"CREATE CATALOG IF NOT EXISTS {catalog} COMMENT {comment}")]


def render_functions(spec: Spec, env: str) -> list[Statement]:
    catalog = spec.catalog(env)
    stmts = []

    cases = []
    for level in spec.classification.levels:
        if level.unmasked_for is None:
            cond = "TRUE"
        elif level.unmasked_for:
            cond = " OR ".join(_member(spec.group(p)) for p in level.unmasked_for)
        else:
            cond = "FALSE"
        cases.append(f"    WHEN {_lit(level.name)} THEN {cond}")
    stmts.append(Statement("functions", "\n".join([
        f"CREATE OR REPLACE FUNCTION {_gov(catalog, 'can_see')}(level STRING)",
        "RETURNS BOOLEAN",
        f"COMMENT {_lit('True if the current user may see unmasked values at this level. ' + MANAGED_BY)}",
        "RETURN CASE level",
        *cases,
        "    ELSE FALSE",
        "  END",
    ])))

    for pii in spec.classification.pii_types.values():
        strategy = spec.classification.strategies[pii.strategy]
        stmts.append(Statement("functions", "\n".join([
            f"CREATE OR REPLACE FUNCTION {_gov(catalog, 'mask_' + pii.name)}(v {strategy.data_type})",
            f"RETURNS {strategy.data_type}",
            f"COMMENT {_lit(f'Mask for pii_type={pii.name} ({pii.classification}, {strategy.name}). {MANAGED_BY}')}",
            f"RETURN CASE WHEN {_gov(catalog, 'can_see')}({_lit(pii.classification)}) THEN v",
            f"  ELSE {strategy.expression} END",
        ])))

    for rf in spec.access.row_filters.values():
        bypass = [_member(spec.group(p)) for p in rf.bypass]
        mapping_table = _gov(catalog, f"{rf.name}_access")
        exists = (
            f"EXISTS (SELECT 1 FROM {mapping_table} a "
            f"WHERE a.value = row_value AND is_account_group_member(a.group_name))"
        )
        stmts.append(Statement("functions", "\n".join([
            f"CREATE OR REPLACE FUNCTION {_gov(catalog, rf.function)}(row_value STRING)",
            "RETURNS BOOLEAN",
            f"COMMENT {_lit(f'Row filter on {rf.column}, backed by {rf.name}_access. {MANAGED_BY}')}",
            "RETURN " + "\n  OR ".join([*bypass, exists]),
        ])))
    return stmts


def render_reference_data(spec: Spec, env: str) -> list[Statement]:
    """Mapping tables behind row filters, overwritten from the spec on every apply."""
    catalog = spec.catalog(env)
    stmts = []
    for rf in spec.access.row_filters.values():
        table = _gov(catalog, f"{rf.name}_access")
        stmts.append(Statement(
            "reference_data",
            f"CREATE TABLE IF NOT EXISTS {table} (group_name STRING NOT NULL, value STRING NOT NULL) "
            f"COMMENT {_lit(f'Group to {rf.column} mapping for row filter {rf.name}. {MANAGED_BY}')}",
        ))
        rows = sorted((spec.group(p), v) for p, values in rf.mapping.items() for v in values)
        if rows:
            values = ",\n  ".join(f"({_lit(g)}, {_lit(v)})" for g, v in rows)
            stmts.append(Statement("reference_data", f"INSERT OVERWRITE {table} VALUES\n  {values}"))
        else:
            stmts.append(Statement("reference_data", f"DELETE FROM {table}"))
    return stmts


def _grant_applies(grant: Grant, env: str) -> bool:
    return grant.environments is None or env in grant.environments


def expand_grants(spec: Spec, env: str) -> dict[tuple[str, str], list[str]]:
    """{(securable, principal): sorted privileges} for an environment, merged across rules."""
    catalog = spec.catalog(env)
    merged: dict[tuple[str, str], set[str]] = defaultdict(set)
    for grant in spec.access.grants:
        if not _grant_applies(grant, env):
            continue
        if grant.securable == "catalog":
            securables = [f"CATALOG {catalog}"]
        else:
            securables = [f"SCHEMA {catalog}.{s}" for s in select_schemas(spec, grant)]
        for securable in securables:
            for principal in grant.principals:
                merged[(securable, principal)].update(grant.privileges)
    return {key: sorted(privs, key=PRIVILEGES.index) for key, privs in sorted(merged.items())}


def select_schemas(spec: Spec, grant: Grant) -> list[str]:
    sel = grant.selector
    if sel is None:
        return []
    if sel.names:
        return list(sel.names)
    return [
        schema for schema, domain, layer in spec.layout.domain_schemas()
        if (not sel.domains or domain in sel.domains) and (not sel.layers or layer in sel.layers)
    ]


def render_grants(spec: Spec, env: str) -> list[Statement]:
    return [
        Statement(
            "grants",
            f"GRANT {', '.join(p.replace('_', ' ') for p in privs)} ON {securable} TO {_ident(spec.group(principal))}",
        )
        for (securable, principal), privs in expand_grants(spec, env).items()
    ]


def _tags(pairs: dict[str, str]) -> str:
    return ", ".join(f"{_lit(k)} = {_lit(v)}" for k, v in pairs.items())


def render_table_policies(spec: Spec, env: str) -> list[Statement]:
    catalog = spec.catalog(env)
    stmts = []
    for t in spec.tables:
        fq = f"{catalog}.{t.schema}.{t.name}"
        table_tags = {
            "classification": spec.table_classification(t),
            "domain": t.domain,
            "layer": t.layer,
            "owner": spec.group(t.owner),
            "data_contract": t.contract_id,
        }
        stmts.append(Statement("tags", f"ALTER TABLE {fq} SET TAGS ({_tags(table_tags)})", fq))
        for c in t.columns:
            level = spec.column_classification(c)
            col_tags = {}
            if level:
                col_tags["classification"] = level
            if c.pii_type:
                col_tags["pii_type"] = c.pii_type
            if col_tags:
                stmts.append(Statement(
                    "tags", f"ALTER TABLE {fq} ALTER COLUMN {_ident(c.name)} SET TAGS ({_tags(col_tags)})", fq
                ))
            if c.pii_type:
                stmts.append(Statement(
                    "masks",
                    f"ALTER TABLE {fq} ALTER COLUMN {_ident(c.name)} SET MASK {_gov(catalog, 'mask_' + c.pii_type)}",
                    fq,
                ))
        if t.row_filter:
            rf = spec.access.row_filters[t.row_filter]
            stmts.append(Statement(
                "row_filters",
                f"ALTER TABLE {fq} SET ROW FILTER {_gov(catalog, rf.function)} ON ({_ident(rf.column)})",
                fq,
            ))
    return stmts


def render_plan(spec: Spec, env: str, phases: tuple[str, ...] = PHASES) -> list[Statement]:
    """Every statement needed to bring `env` to the declared state, in dependency order."""
    stmts = [
        *render_functions(spec, env),
        *render_reference_data(spec, env),
        *render_grants(spec, env),
        *render_table_policies(spec, env),
    ]
    return sorted((s for s in stmts if s.phase in phases), key=lambda s: PHASES.index(s.phase))


def render_access_matrix(spec: Spec, env: str) -> str:
    """Markdown matrix of principal × securable -> privileges, for docs and PR review."""
    grants = expand_grants(spec, env)
    securables = sorted({s for s, _ in grants}, key=lambda s: (not s.startswith("CATALOG"), s))
    principals = list(spec.access.principals)
    short = [s.split(" ", 1)[1].split(".")[-1] if s.startswith("SCHEMA") else "(catalog)" for s in securables]
    lines = [
        f"| principal | {' | '.join(short)} |",
        f"|---|{'---|' * len(securables)}",
    ]
    for p in principals:
        cells = [", ".join(grants.get((s, p), [])).replace("_", " ") or "–" for s in securables]
        lines.append(f"| `{p}` | {' | '.join(cells)} |")
    return "\n".join(lines)
