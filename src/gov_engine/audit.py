"""Audit views over system tables (FR10). See docs/adr/0009-audit-views-and-scorecard.md.

Only account admins can read `system.access`, and its grants can't be extended, so these views are
created and owned by an account admin, from their laptop: `gov_engine audit-views --env dev`. The deployer
can't create them; a view it owned would fail to read its source. Readers need only SELECT on a view:
`gov-auditors` get it through the `audit` schema grant in access_policy.yml.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gov_engine.databricks_api import query_rows, run_statement
from gov_engine.spec import Spec
from gov_engine.tag_policies import ApiCall

VIEWS_SQL = Path("src") / "audit" / "views.sql"
OWNER_SQL = "SELECT catalog_owner FROM system.information_schema.catalogs WHERE catalog_name = '{c}'"


def render_audit_views(text: str, catalog: str, deployer: str) -> list[str]:
    """Statements in views.sql with `{{catalog}}` and `{{deployer}}` filled in. Split on `;` at line end."""
    body = "\n".join(line for line in text.replace("{{catalog}}", catalog).replace("{{deployer}}", deployer)
                     .splitlines() if not line.lstrip().startswith("--"))
    return [s for s in (p.strip().rstrip(";").strip() for p in body.split(";\n")) if s]


def create_audit_views(spec: Spec, env: str, root: Path, api: ApiCall, warehouse_id: str,
                       dry_run: bool = False, log: Callable[[str], None] = print) -> list[str]:
    """Create or replace the audit views as the caller, who must be an account admin. Returns the SQL."""
    catalog = spec.catalog(env)
    owners = query_rows(api, warehouse_id, OWNER_SQL.format(c=catalog))
    if not owners:
        raise RuntimeError(f"catalog {catalog} not found; deploy it first (make deploy ENV={env})")
    statements = render_audit_views((root / VIEWS_SQL).read_text(), catalog, owners[0]["catalog_owner"])
    for sql in statements:
        if not dry_run:
            run_statement(api, warehouse_id, sql)
        log(f"[{'dry-run' if dry_run else 'ok'}] [audit] {sql.splitlines()[0]}")
    return statements
