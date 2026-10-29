"""Drift detection: declared state (spec) vs actual state (`<catalog>.information_schema`).

Pure SQL over information_schema, so it runs the same in a job (Spark) and from a laptop (SQL warehouse).
Run it as the catalog owner (`gov-deployer`): information_schema only shows other principals' grants
and policies to the owner, so a less privileged caller would see missing grants that are not missing.

Severity:
- critical: weakens protection or widens access. An undeclared grant, a PII or filter tag missing from
  a contract column, a missing or altered ABAC policy, an undeclared GRANT/DENY policy.
- warning: everything else that differs. Apply fixes most of it on the next run; undeclared grants,
  tags and tables are never removed by apply, so they stay drift until a person cleans them up.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from gov_engine.render import (
    DDL_TYPES,
    TAG_CLASSIFICATION,
    TAG_FILTER_KEY,
    TAG_PII_TYPE,
    declared_policies,
    declared_tags,
    expand_grants,
)
from gov_engine.spec import Spec

Query = Callable[[str], list[dict]]

# Tag keys the engine owns. Anything else (system `class.*` tags, ad-hoc tags) is not drift.
ENGINE_TAG_KEYS = (TAG_CLASSIFICATION, TAG_PII_TYPE, TAG_FILTER_KEY, "domain", "layer", "owner", "data_contract")
PROTECTION_TAG_KEYS = (TAG_PII_TYPE, TAG_FILTER_KEY)  # policies match on these
SYSTEM_SCHEMAS = ("information_schema",)

QUERIES = {
    "schemas": "SELECT schema_name FROM {c}.information_schema.schemata",
    "owner": "SELECT catalog_owner FROM {c}.information_schema.catalogs",
    "catalog_privileges": "SELECT grantee, privilege_type FROM {c}.information_schema.catalog_privileges "
                          "WHERE inherited_from = 'NONE'",
    "schema_privileges": "SELECT schema_name, grantee, privilege_type FROM {c}.information_schema.schema_privileges "
                         "WHERE inherited_from = 'NONE'",
    "table_privileges": "SELECT table_schema, table_name, grantee, privilege_type "
                        "FROM {c}.information_schema.table_privileges WHERE inherited_from = 'NONE'",
    "columns": "SELECT table_schema, table_name, column_name, full_data_type, is_nullable "
               "FROM {c}.information_schema.columns",
    "table_tags": "SELECT schema_name, table_name, tag_name, tag_value FROM {c}.information_schema.table_tags",
    "column_tags": "SELECT schema_name, table_name, column_name, tag_name, tag_value "
                   "FROM {c}.information_schema.column_tags",
    "policies": "SELECT policy_name, policy_type, on_securable_type, to_principals, except_principals "
                "FROM {c}.information_schema.abac_policy_definitions",
    "column_masks": "SELECT table_schema, table_name, column_name, mask_name FROM {c}.information_schema.column_masks",
    "row_filters": "SELECT table_schema, table_name, filter_name FROM {c}.information_schema.row_filters",
}


@dataclass(frozen=True)
class DriftFinding:
    severity: str  # critical | warning
    kind: str  # schema | grant | table | column | tag | policy | mask
    securable: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.kind} {self.securable}: {self.detail}"


def detect_drift(spec: Spec, env: str, query: Query) -> list[DriftFinding]:
    catalog = spec.catalog(env)
    cache: dict[str, list[dict]] = {}

    def q(name: str) -> list[dict]:
        if name not in cache:
            cache[name] = query(QUERIES[name].format(c=catalog))
        return cache[name]

    findings = [
        *_schemas(spec, catalog, q),
        *_grants(spec, env, catalog, q),
        *_tables(spec, catalog, q),
        *_tags(spec, env, catalog, q),
        *_policies(spec, env, q),
        *_per_column_controls(catalog, q),
    ]
    return sorted(findings, key=lambda f: (f.severity != "critical", f.kind, f.securable, f.detail))


def _schemas(spec: Spec, catalog: str, q: Callable[[str], list[dict]]) -> list[DriftFinding]:
    declared = set(spec.layout.all_schemas())
    actual = {r["schema_name"] for r in q("schemas")} - set(SYSTEM_SCHEMAS)
    return [
        *(DriftFinding("critical", "schema", f"{catalog}.{s}", "declared in layout.yml but missing")
          for s in sorted(declared - actual)),
        *(DriftFinding("warning", "schema", f"{catalog}.{s}", "not declared in layout.yml")
          for s in sorted(actual - declared)),
    ]


def _grants(spec: Spec, env: str, catalog: str, q: Callable[[str], list[dict]]) -> list[DriftFinding]:
    declared: dict[tuple[str, str], set[str]] = {
        (securable, spec.group(principal)): set(privs)
        for (securable, principal), privs in expand_grants(spec, env).items()
    }
    # The catalog owner (the deployer) can grant itself anything, so a grant to it widens nothing. One is
    # expected: SELECT on audit.column_lineage, granted by the account admin who owns that view (ADR-0008).
    owners = {r["catalog_owner"] for r in q("owner")}
    actual: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in q("catalog_privileges"):
        actual[(f"CATALOG {catalog}", r["grantee"])].add(r["privilege_type"])
    for r in q("schema_privileges"):
        if r["schema_name"] not in SYSTEM_SCHEMAS:
            actual[(f"SCHEMA {catalog}.{r['schema_name']}", r["grantee"])].add(r["privilege_type"])
    for r in q("table_privileges"):  # the engine never grants on tables
        if r["table_schema"] not in SYSTEM_SCHEMAS:
            actual[(f"TABLE {catalog}.{r['table_schema']}.{r['table_name']}", r["grantee"])].add(r["privilege_type"])

    findings = []
    for key in sorted(declared.keys() | actual.keys() - {k for k in actual if k[1] in owners}):
        securable, grantee = key
        extra = actual.get(key, set()) - declared.get(key, set())
        missing = declared.get(key, set()) - actual.get(key, set())
        who = f"individual user {grantee}" if "@" in grantee else f"`{grantee}`"
        if extra:
            findings.append(DriftFinding("critical", "grant", securable,
                                         f"undeclared {', '.join(sorted(extra))} to {who}"))
        if missing:
            findings.append(DriftFinding("warning", "grant", securable,
                                         f"declared {', '.join(sorted(missing))} to {who} is missing"))
    return findings


def _tables(spec: Spec, catalog: str, q: Callable[[str], list[dict]]) -> list[DriftFinding]:
    """Contract columns vs actual columns. Silver and gold tables must have a contract; bronze is the
    raw landing zone and has none (docs/adr/0008)."""
    actual: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in q("columns"):
        actual[f"{catalog}.{r['table_schema']}.{r['table_name']}"][r["column_name"]] = r

    findings = []
    contract_tables = set()
    for t in spec.tables:
        fq = f"{catalog}.{t.schema}.{t.name}"
        contract_tables.add(fq)
        if fq not in actual:
            findings.append(DriftFinding("warning", "table", fq, f"contract {t.contract_id} table is missing"))
            continue
        columns = actual[fq]
        for c in t.columns:
            if c.name not in columns:
                findings.append(DriftFinding("warning", "column", f"{fq}.{c.name}", "in contract but missing"))
                continue
            got = columns[c.name]
            want_type = DDL_TYPES[c.logical_type].lower()
            if got["full_data_type"].lower() != want_type:
                findings.append(DriftFinding("warning", "column", f"{fq}.{c.name}",
                                             f"type {got['full_data_type']}, contract says {want_type}"))
            if c.required and got["is_nullable"] != "NO":
                findings.append(DriftFinding("warning", "column", f"{fq}.{c.name}", "nullable, contract says required"))
        for name in sorted(columns.keys() - {c.name for c in t.columns}):
            findings.append(DriftFinding("warning", "column", f"{fq}.{name}", f"not in contract {t.contract_id}"))

    governed_schemas = {s for s, _, layer in spec.layout.domain_schemas() if layer != spec.layout.layers[0]}
    for fq in sorted(actual.keys() - contract_tables):
        if fq.split(".")[1] in governed_schemas:
            findings.append(DriftFinding("warning", "table", fq, "no data contract"))
    return findings


def _tags(spec: Spec, env: str, catalog: str, q: Callable[[str], list[dict]]) -> list[DriftFinding]:
    """Engine-owned tags on contract tables and columns. Tables that don't exist yet are reported by _tables."""
    actual: dict[tuple[str, str | None], dict[str, str]] = defaultdict(dict)
    for r in q("table_tags"):
        if r["tag_name"] in ENGINE_TAG_KEYS:
            actual[(f"{catalog}.{r['schema_name']}.{r['table_name']}", None)][r["tag_name"]] = r["tag_value"]
    for r in q("column_tags"):
        if r["tag_name"] in ENGINE_TAG_KEYS:
            fq = f"{catalog}.{r['schema_name']}.{r['table_name']}"
            actual[(fq, r["column_name"])][r["tag_name"]] = r["tag_value"]
    existing = {f"{catalog}.{r['table_schema']}.{r['table_name']}" for r in q("columns")}

    findings = []
    declared = {k: v for k, v in declared_tags(spec, env).items() if k[0] in existing}
    actual = {k: v for k, v in actual.items() if k[0] in existing}
    for key in sorted(declared.keys() | actual.keys(), key=lambda k: (k[0], k[1] or "")):
        fq, column = key
        securable = f"{fq}.{column}" if column else fq
        want, got = declared.get(key, {}), actual.get(key, {})
        for tag in sorted(want.keys() | got.keys()):
            severity = "critical" if tag in PROTECTION_TAG_KEYS else "warning"
            if tag not in got:
                findings.append(DriftFinding(severity, "tag", securable, f"{tag}={want[tag]} is missing"))
            elif tag not in want:
                findings.append(DriftFinding("warning", "tag", securable,
                                             f"{tag}={got[tag]} is not declared in a contract"))
            elif got[tag] != want[tag]:
                findings.append(DriftFinding(severity, "tag", securable, f"{tag}={got[tag]}, declared {want[tag]}"))
    return findings


def _policies(spec: Spec, env: str, q: Callable[[str], list[dict]]) -> list[DriftFinding]:
    declared = {p.name: p for p in declared_policies(spec, env)}
    actual = {r["policy_name"]: r for r in q("policies")}
    findings = []
    for name in sorted(declared.keys() | actual.keys()):
        want, got = declared.get(name), actual.get(name)
        if got is None:
            findings.append(DriftFinding("critical", "policy", name, "declared but missing"))
            continue
        if want is None:
            grants_access = got["policy_type"] not in ("COLUMN_MASK", "ROW_FILTER")
            findings.append(DriftFinding("critical" if grants_access else "warning", "policy", name,
                                         f"undeclared {got['policy_type']} policy"))
            continue
        problems = []
        if got["policy_type"] != want.policy_type:
            problems.append(f"type {got['policy_type']}, declared {want.policy_type}")
        if (got.get("on_securable_type") or "CATALOG") != "CATALOG":
            problems.append(f"attached to a {got['on_securable_type']}, declared on the catalog")
        if set(got.get("to_principals") or []) != {"account users"}:
            problems.append(f"applies to {sorted(got.get('to_principals') or [])}, declared ['account users']")
        if set(got.get("except_principals") or []) != set(want.exempt):
            extra = sorted(set(got.get("except_principals") or []) - set(want.exempt))
            missing = sorted(set(want.exempt) - set(got.get("except_principals") or []))
            problems.append(f"exemptions differ (undeclared: {extra or '-'}, missing: {missing or '-'})")
        findings += [DriftFinding("critical", "policy", name, p) for p in problems]
    return findings


def _per_column_controls(catalog: str, q: Callable[[str], list[dict]]) -> list[DriftFinding]:
    """The engine protects data only through ABAC policies; a per-column SET MASK / SET ROW FILTER was
    added by hand and bypasses the spec."""
    return [
        *(DriftFinding("warning", "mask", f"{catalog}.{r['table_schema']}.{r['table_name']}.{r['column_name']}",
                       f"per-column mask {r['mask_name']} outside ABAC")
          for r in q("column_masks")),
        *(DriftFinding("warning", "mask", f"{catalog}.{r['table_schema']}.{r['table_name']}",
                       f"per-table row filter {r['filter_name']} outside ABAC")
          for r in q("row_filters")),
    ]
