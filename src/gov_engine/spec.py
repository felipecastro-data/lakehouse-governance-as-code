"""Load and validate the declarative governance spec in `governance/`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Canonical order, also used to sort privileges in rendered GRANT statements.
PRIVILEGES = (
    "BROWSE", "USE_CATALOG", "USE_SCHEMA", "SELECT", "MODIFY", "EXECUTE", "READ_VOLUME", "WRITE_VOLUME",
    "CREATE_TABLE", "CREATE_FUNCTION", "CREATE_VOLUME", "APPLY_TAG",
)

# ODCS logicalType -> Databricks SQL type, used to check mask strategies fit the column.
LOGICAL_TO_SQL = {
    "string": "STRING", "date": "DATE", "timestamp": "TIMESTAMP", "integer": "BIGINT",
    "number": "DECIMAL", "boolean": "BOOLEAN",
}

QUALITY_RULES = ("uniqueness", "notNull", "referentialIntegrity")

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_TAG_VALUE = re.compile(r"^[A-Za-z0-9_.\- ]+$")
_SYSTEM_TAG = re.compile(r"^class\.[a-z0-9_]+$")


class SpecError(ValueError):
    """Raised with every validation problem found, not just the first."""

    def __init__(self, errors: list[str]):
        super().__init__("Invalid governance spec:\n  - " + "\n  - ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Domain:
    name: str
    steward: str
    description: str = ""


@dataclass(frozen=True)
class Layout:
    environments: dict[str, str]  # env name -> catalog
    domains: dict[str, Domain]
    layers: tuple[str, ...]
    shared_schemas: tuple[str, ...]

    def domain_schemas(self) -> list[tuple[str, str, str]]:
        """(schema, domain, layer) for every domain × layer."""
        return [(f"{d}_{lyr}", d, lyr) for d in self.domains for lyr in self.layers]

    def all_schemas(self) -> list[str]:
        return [s for s, _, _ in self.domain_schemas()] + list(self.shared_schemas)


@dataclass(frozen=True)
class Level:
    name: str
    unmasked_for: tuple[str, ...] | None  # None means everyone
    description: str = ""


@dataclass(frozen=True)
class MaskStrategy:
    name: str
    data_type: str
    expression: str


@dataclass(frozen=True)
class PiiType:
    name: str
    classification: str
    strategy: str
    system_tags: tuple[str, ...] = ()  # Databricks `class.*` tags that also trigger this mask


@dataclass(frozen=True)
class Classification:
    levels: tuple[Level, ...]  # least -> most sensitive
    strategies: dict[str, MaskStrategy]
    pii_types: dict[str, PiiType]

    def level_names(self) -> list[str]:
        return [lvl.name for lvl in self.levels]

    def rank(self, level: str) -> int:
        return self.level_names().index(level)


@dataclass(frozen=True)
class SchemaSelector:
    domains: tuple[str, ...] = ()
    layers: tuple[str, ...] = ()
    names: tuple[str, ...] = ()


@dataclass(frozen=True)
class Grant:
    principals: tuple[str, ...]
    securable: str  # "catalog" | "schemas"
    selector: SchemaSelector | None
    privileges: tuple[str, ...]
    environments: tuple[str, ...] | None  # None means all
    reason: str = ""


@dataclass(frozen=True)
class RowFilter:
    name: str
    function: str
    column: str
    bypass: tuple[str, ...]
    mapping: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class AccessPolicy:
    principals: dict[str, str]  # logical name -> group name
    grants: tuple[Grant, ...]
    row_filters: dict[str, RowFilter]


@dataclass(frozen=True)
class Column:
    name: str
    logical_type: str
    classification: str | None
    pii_type: str | None
    required: bool = False
    primary_key: bool = False


@dataclass(frozen=True)
class QualityRule:
    rule: str
    column: str
    references: str | None = None  # "<contract id>.<column>", for referentialIntegrity


@dataclass(frozen=True)
class Table:
    contract_id: str
    schema: str
    name: str
    domain: str
    owner: str
    row_filter: str | None
    columns: tuple[Column, ...]
    description: str = ""
    quality: tuple[QualityRule, ...] = ()

    @property
    def layer(self) -> str:
        return self.schema.rsplit("_", 1)[-1]


@dataclass(frozen=True)
class Spec:
    layout: Layout
    classification: Classification
    access: AccessPolicy
    tables: tuple[Table, ...]

    def catalog(self, env: str) -> str:
        if env not in self.layout.environments:
            raise KeyError(f"Unknown environment {env!r}; expected one of {sorted(self.layout.environments)}")
        return self.layout.environments[env]

    def group(self, principal: str) -> str:
        return self.access.principals[principal]

    def column_classification(self, column: Column) -> str | None:
        """Effective level: the declared one, else the pii_type's level."""
        if column.classification:
            return column.classification
        if column.pii_type:
            return self.classification.pii_types[column.pii_type].classification
        return None

    def table_classification(self, table: Table) -> str:
        """A table is as sensitive as its most sensitive column."""
        levels = [lvl for c in table.columns if (lvl := self.column_classification(c))]
        if not levels:
            return self.classification.level_names()[0]
        return max(levels, key=self.classification.rank)


# --------------------------------------------------------------------------- loading


def _read(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def _custom(props: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {p["property"]: p.get("value") for p in props or []}


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _load_layout(raw: dict[str, Any]) -> Layout:
    return Layout(
        environments={name: cfg["catalog"] for name, cfg in raw["environments"].items()},
        domains={
            name: Domain(name=name, steward=cfg["steward"], description=cfg.get("description", ""))
            for name, cfg in raw["domains"].items()
        },
        layers=tuple(raw["layers"]),
        shared_schemas=tuple(raw.get("shared_schemas", [])),
    )


def _load_classification(raw: dict[str, Any]) -> Classification:
    levels = tuple(
        Level(
            name=name,
            unmasked_for=None if cfg.get("unmasked_for") == "all" else _tuple(cfg.get("unmasked_for")),
            description=cfg.get("description", ""),
        )
        for name, cfg in raw["levels"].items()
    )
    return Classification(
        levels=levels,
        strategies={
            name: MaskStrategy(name=name, data_type=cfg["data_type"].upper(), expression=cfg["expression"])
            for name, cfg in raw["mask_strategies"].items()
        },
        pii_types={
            name: PiiType(
                name=name, classification=cfg["classification"], strategy=cfg["strategy"],
                system_tags=_tuple(cfg.get("system_tags")),
            )
            for name, cfg in raw["pii_types"].items()
        },
    )


def _load_grant(raw: dict[str, Any]) -> Grant:
    on = raw["scope"]
    if on == "catalog":
        securable, selector = "catalog", None
    else:
        sel = on.get("schemas", {}) if isinstance(on, dict) else {}
        securable = "schemas"
        selector = SchemaSelector(
            domains=_tuple(sel.get("domains")), layers=_tuple(sel.get("layers")), names=_tuple(sel.get("names"))
        )
    envs = raw.get("environments")
    return Grant(
        principals=_tuple(raw["principals"]),
        securable=securable,
        selector=selector,
        privileges=_tuple(raw["privileges"]),
        environments=_tuple(envs) if envs is not None else None,
        reason=raw.get("reason", ""),
    )


def _load_access(raw: dict[str, Any]) -> AccessPolicy:
    return AccessPolicy(
        principals=dict(raw["principals"]),
        grants=tuple(_load_grant(g) for g in raw.get("grants", [])),
        row_filters={
            name: RowFilter(
                name=name,
                function=cfg["function"],
                column=cfg["column"],
                bypass=_tuple(cfg.get("bypass")),
                mapping={p: _tuple(v) for p, v in cfg.get("mapping", {}).items()},
            )
            for name, cfg in raw.get("row_filters", {}).items()
        },
    )


def _load_contract(raw: dict[str, Any]) -> list[Table]:
    owner = _custom(raw.get("customProperties")).get("owner", "")
    tables = []
    for obj in raw.get("schema", []):
        schema, _, name = obj["physicalName"].partition(".")
        props = _custom(obj.get("customProperties"))
        columns = tuple(
            Column(
                name=p["name"],
                logical_type=p.get("logicalType", "string"),
                classification=p.get("classification"),
                pii_type=_custom(p.get("customProperties")).get("piiType"),
                required=bool(p.get("required") or p.get("primaryKey")),
                primary_key=bool(p.get("primaryKey")),
            )
            for p in obj.get("properties", [])
        )
        tables.append(Table(
            contract_id=raw["id"], schema=schema, name=name, domain=raw.get("domain", ""),
            owner=owner, row_filter=props.get("rowFilter"), columns=columns,
            description=(raw.get("description") or {}).get("purpose", ""),
            quality=tuple(
                QualityRule(rule=q["rule"], column=q["column"], references=q.get("references"))
                for q in raw.get("quality", [])
            ),
        ))
    return tables


def load_spec(root: str | Path = ".") -> Spec:
    """Load `governance/` under `root` and validate it. Raises SpecError on problems."""
    gov = Path(root) / "governance"
    tables: list[Table] = []
    for path in sorted((gov / "contracts").glob("*.yml")):
        tables.extend(_load_contract(_read(path)))
    spec = Spec(
        layout=_load_layout(_read(gov / "layout.yml")),
        classification=_load_classification(_read(gov / "classification.yml")),
        access=_load_access(_read(gov / "access_policy.yml")),
        tables=tuple(tables),
    )
    errors = validate(spec)
    if errors:
        raise SpecError(errors)
    return spec


# --------------------------------------------------------------------------- validation


def validate(spec: Spec) -> list[str]:
    """Return every problem in the spec; an empty list means it is valid."""
    errors: list[str] = []
    layout, cls, access = spec.layout, spec.classification, spec.access
    principals = set(access.principals)
    level_names = cls.level_names()

    def check_principals(where: str, names: tuple[str, ...]) -> None:
        for p in names:
            if p not in principals:
                errors.append(f"{where}: unknown principal {p!r}")

    for name in [*layout.environments.values(), *layout.all_schemas()]:
        if not _IDENTIFIER.match(name):
            errors.append(f"layout: {name!r} is not a valid lowercase identifier")
    for d in layout.domains.values():
        check_principals(f"layout.domains.{d.name}.steward", (d.steward,))

    for lvl in cls.levels:
        check_principals(f"classification.levels.{lvl.name}.unmasked_for", lvl.unmasked_for or ())
    for pii in cls.pii_types.values():
        if pii.classification not in level_names:
            errors.append(f"classification.pii_types.{pii.name}: unknown level {pii.classification!r}")
        if pii.strategy not in cls.strategies:
            errors.append(f"classification.pii_types.{pii.name}: unknown strategy {pii.strategy!r}")
        if not _IDENTIFIER.match(pii.name):
            errors.append(f"classification.pii_types.{pii.name}: name must be a lowercase identifier")
        for tag in pii.system_tags:
            if not _SYSTEM_TAG.match(tag):
                errors.append(f"classification.pii_types.{pii.name}: {tag!r} is not a `class.*` system tag")

    for i, g in enumerate(access.grants):
        where = f"access_policy.grants[{i}]"
        check_principals(where, g.principals)
        for priv in g.privileges:
            if priv not in PRIVILEGES:
                errors.append(f"{where}: unknown privilege {priv!r}")
        for env in g.environments or ():
            if env not in layout.environments:
                errors.append(f"{where}: unknown environment {env!r}")
        if g.selector:
            sel = g.selector
            errors += [f"{where}: unknown domain {d!r}" for d in sel.domains if d not in layout.domains]
            errors += [f"{where}: unknown layer {lyr!r}" for lyr in sel.layers if lyr not in layout.layers]
            errors += [f"{where}: unknown schema {n!r}" for n in sel.names if n not in layout.all_schemas()]
            if sel.names and (sel.domains or sel.layers):
                errors.append(f"{where}: use either `names` or `domains`/`layers`, not both")
            if not (sel.names or sel.domains or sel.layers):
                errors.append(f"{where}: schema selector is empty")

    for rf in access.row_filters.values():
        where = f"access_policy.row_filters.{rf.name}"
        check_principals(f"{where}.bypass", rf.bypass)
        check_principals(f"{where}.mapping", tuple(rf.mapping))
        if not _IDENTIFIER.match(rf.function):
            errors.append(f"{where}: function {rf.function!r} is not a valid identifier")
        for values in rf.mapping.values():
            errors += [f"{where}: invalid value {v!r}" for v in values if not _TAG_VALUE.match(v)]

    seen: set[str] = set()
    by_contract = {t.contract_id: t for t in spec.tables}
    domain_schemas = {s for s, _, _ in layout.domain_schemas()}
    for t in spec.tables:
        where = f"contract {t.contract_id} ({t.schema}.{t.name})"
        fq = f"{t.schema}.{t.name}"
        if fq in seen:
            errors.append(f"{where}: table declared more than once")
        seen.add(fq)
        if t.schema not in domain_schemas:
            errors.append(f"{where}: schema {t.schema!r} is not in layout")
        if t.domain not in layout.domains:
            errors.append(f"{where}: unknown domain {t.domain!r}")
        if not t.owner:
            errors.append(f"{where}: missing owner")
        else:
            check_principals(where, (t.owner,))
        column_names = {c.name for c in t.columns}
        if t.row_filter:
            rf = access.row_filters.get(t.row_filter)
            if rf is None:
                errors.append(f"{where}: unknown row filter {t.row_filter!r}")
            elif rf.column not in column_names:
                errors.append(f"{where}: row filter {rf.name!r} needs column {rf.column!r}")
        for q in t.quality:
            qw = f"{where}: quality {q.rule}({q.column})"
            if q.rule not in QUALITY_RULES:
                errors.append(f"{qw}: unknown rule; expected one of {QUALITY_RULES}")
            if q.column not in column_names:
                errors.append(f"{qw}: unknown column")
            if q.rule == "referentialIntegrity":
                ref_contract, _, ref_column = (q.references or "").rpartition(".")
                ref = by_contract.get(ref_contract)
                if ref is None or ref_column not in {c.name for c in ref.columns}:
                    errors.append(f"{qw}: references {q.references!r} is not <contract id>.<column>")
        for c in t.columns:
            cw = f"{where}.{c.name}"
            if c.logical_type not in LOGICAL_TO_SQL:
                errors.append(f"{cw}: unknown logicalType {c.logical_type!r}")
            if c.classification and c.classification not in level_names:
                errors.append(f"{cw}: unknown classification {c.classification!r}")
            if c.pii_type:
                pii = cls.pii_types.get(c.pii_type)
                if pii is None:
                    errors.append(f"{cw}: unknown piiType {c.pii_type!r}")
                    continue
                if c.classification and c.classification in level_names and pii.classification in level_names \
                        and cls.rank(c.classification) < cls.rank(pii.classification):
                    errors.append(
                        f"{cw}: classification {c.classification!r} is below the {pii.classification!r} "
                        f"required for piiType {pii.name!r}"
                    )
                strategy = cls.strategies.get(pii.strategy)
                if strategy and LOGICAL_TO_SQL.get(c.logical_type) != strategy.data_type:
                    errors.append(
                        f"{cw}: mask strategy {strategy.name!r} returns {strategy.data_type}, "
                        f"column is {c.logical_type}"
                    )
    return errors
