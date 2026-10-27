"""Render a validated Spec into idempotent Unity Catalog SQL for one environment.

Masks and row filters are attached by ABAC policies that match governed tags, so the engine never
touches individual columns with `SET MASK` / `SET ROW FILTER`. See docs/adr/0005-native-abac.md.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from gov_engine.spec import PRIVILEGES, Grant, Spec

GOVERNANCE_SCHEMA = "governance"
MANAGED_BY = "Managed by gov_engine - do not edit by hand"
ALL_USERS = "account users"

# Governed tag keys (tag policies) the engine owns. See gov_engine.tag_policies.
TAG_CLASSIFICATION = "classification"
TAG_PII_TYPE = "pii_type"
TAG_FILTER_KEY = "filter_key"

# Order matters: row filter functions read the mapping tables, and policies need the functions.
PHASES = ("reference_data", "functions", "grants", "tags", "policies")


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


def _gov(catalog: str, obj: str) -> str:
    return f"{catalog}.{GOVERNANCE_SCHEMA}.{obj}"


def _principals(groups: list[str]) -> str:
    return ", ".join(_ident(g) for g in groups)


def render_functions(spec: Spec, env: str) -> list[Statement]:
    """Mask functions are pure transformations; who is exempt lives in the policy's EXCEPT clause."""
    catalog = spec.catalog(env)
    stmts = []
    for pii in spec.classification.pii_types.values():
        strategy = spec.classification.strategies[pii.strategy]
        stmts.append(Statement("functions", "\n".join([
            f"CREATE OR REPLACE FUNCTION {_gov(catalog, 'mask_' + pii.name)}(v {strategy.data_type})",
            f"RETURNS {strategy.data_type}",
            f"COMMENT {_lit(f'Mask for pii_type={pii.name} ({strategy.name}). {MANAGED_BY}')}",
            f"RETURN {strategy.expression}",
        ])))

    for rf in spec.access.row_filters.values():
        mapping_table = _gov(catalog, f"{rf.name}_access")
        stmts.append(Statement("functions", "\n".join([
            f"CREATE OR REPLACE FUNCTION {_gov(catalog, rf.function)}(row_value STRING)",
            "RETURNS BOOLEAN",
            f"COMMENT {_lit(f'Row filter on {rf.column}, backed by {rf.name}_access. {MANAGED_BY}')}",
            f"RETURN EXISTS (SELECT 1 FROM {mapping_table} a",
            "  WHERE a.value = row_value AND is_account_group_member(a.group_name))",
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
    """{(securable, principal): privileges in canonical order} for an environment, merged across rules."""
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


def render_tags(spec: Spec, env: str) -> list[Statement]:
    """Tags are the only per-table statements: policies find columns through them."""
    catalog = spec.catalog(env)
    stmts = []
    for t in spec.tables:
        fq = f"{catalog}.{t.schema}.{t.name}"
        table_tags = {
            TAG_CLASSIFICATION: spec.table_classification(t),
            "domain": t.domain,
            "layer": t.layer,
            "owner": spec.group(t.owner),
            "data_contract": t.contract_id,
        }
        stmts.append(Statement("tags", f"ALTER TABLE {fq} SET TAGS ({_tags(table_tags)})", fq))
        filter_column = spec.access.row_filters[t.row_filter].column if t.row_filter else None
        for c in t.columns:
            col_tags = {}
            if level := spec.column_classification(c):
                col_tags[TAG_CLASSIFICATION] = level
            if c.pii_type:
                col_tags[TAG_PII_TYPE] = c.pii_type
            if c.name == filter_column:
                col_tags[TAG_FILTER_KEY] = t.row_filter
            if col_tags:
                stmts.append(Statement(
                    "tags", f"ALTER TABLE {fq} ALTER COLUMN {_ident(c.name)} SET TAGS ({_tags(col_tags)})", fq
                ))
    return stmts


def render_policies(spec: Spec, env: str) -> list[Statement]:
    """Catalog-wide ABAC policies: one column mask per PII type, one row filter per filter key."""
    catalog = spec.catalog(env)
    stmts = []
    for pii in spec.classification.pii_types.values():
        level = next(lvl for lvl in spec.classification.levels if lvl.name == pii.classification)
        if level.unmasked_for is None:
            continue  # level is visible to everyone; nothing to mask
        match = " OR ".join([
            f"has_tag_value({_lit(TAG_PII_TYPE)}, {_lit(pii.name)})",
            *(f"has_tag({_lit(tag)})" for tag in pii.system_tags),
        ])
        exempt = [spec.group(p) for p in level.unmasked_for]
        stmts.append(Statement("policies", "\n".join([
            f"CREATE OR REPLACE POLICY mask_{pii.name} ON CATALOG {catalog}",
            f"COMMENT {_lit(f'Mask {pii.name} ({pii.classification}). {MANAGED_BY}')}",
            f"COLUMN MASK {_gov(catalog, 'mask_' + pii.name)}",
            f"TO {_ident(ALL_USERS)}" + (f" EXCEPT {_principals(exempt)}" if exempt else ""),
            "FOR TABLES",
            f"MATCH COLUMNS {match} AS col",
            "ON COLUMN col",
        ])))

    for rf in spec.access.row_filters.values():
        bypass = [spec.group(p) for p in rf.bypass]
        stmts.append(Statement("policies", "\n".join([
            f"CREATE OR REPLACE POLICY filter_{rf.name} ON CATALOG {catalog}",
            f"COMMENT {_lit(f'Row filter on {TAG_FILTER_KEY}={rf.name}. {MANAGED_BY}')}",
            f"ROW FILTER {_gov(catalog, rf.function)}",
            f"TO {_ident(ALL_USERS)}" + (f" EXCEPT {_principals(bypass)}" if bypass else ""),
            "FOR TABLES",
            f"MATCH COLUMNS has_tag_value({_lit(TAG_FILTER_KEY)}, {_lit(rf.name)}) AS col",
            "USING COLUMNS (col)",
        ])))
    return stmts


def render_plan(spec: Spec, env: str, phases: tuple[str, ...] = PHASES) -> list[Statement]:
    """Every SQL statement needed to bring `env` to the declared state, in dependency order.

    Governed tags (tag policies) are account-level and synced through the REST API first;
    see gov_engine.tag_policies.
    """
    stmts = [
        *render_reference_data(spec, env),
        *render_functions(spec, env),
        *render_grants(spec, env),
        *render_tags(spec, env),
        *render_policies(spec, env),
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
