"""Create the environment's catalog before `bundle deploy`.

On Free Edition (Default Storage) the catalogs REST API, which the bundle `catalogs` resource uses,
fails with "Metastore storage root URL does not exist". SQL `CREATE CATALOG` works, so the catalog is
created through the SQL Statement Execution API on a SQL warehouse instead. Schemas and jobs stay in
the bundle. The catalog is owned by whoever runs this: `gov-deployer` in CI (ADR-0006).

`CREATE CATALOG` also creates a `default` schema that is not in layout.yml. It is dropped while empty
(no CASCADE), so it never shows up as drift; a non-empty `default` is left alone with a warning.
"""

from __future__ import annotations

from collections.abc import Callable

from gov_engine.databricks_api import pick_warehouse, run_statement
from gov_engine.spec import Spec
from gov_engine.tag_policies import ApiCall

COMMENT = "Governed lakehouse ({env}). Access, tags and policies managed by gov_engine."


def ensure_catalog(spec: Spec, env: str, api: ApiCall, warehouse_id: str | None = None,
                   dry_run: bool = False, log: Callable[[str], None] = print) -> list[str]:
    """CREATE CATALOG IF NOT EXISTS for env, then drop its empty `default` schema. Returns the SQL."""
    catalog = spec.layout.environments[env]
    comment = COMMENT.format(env=env).replace("'", "''")
    statements = [f"CREATE CATALOG IF NOT EXISTS {catalog} COMMENT '{comment}'"]
    if "default" not in spec.layout.all_schemas():
        statements.append(f"DROP SCHEMA IF EXISTS {catalog}.default")
    warehouse = None if dry_run else warehouse_id or pick_warehouse(api)
    for sql in statements:
        status = "dry-run" if dry_run else "ok"
        if not dry_run:
            try:
                run_statement(api, warehouse, sql)
            except RuntimeError as exc:
                if not sql.startswith("DROP SCHEMA"):
                    raise
                status = f"warn: kept, not empty ({exc})"
        log(f"[{status}] [catalog] {sql}")
    return statements
