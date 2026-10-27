"""Create the environment's catalog before `bundle deploy`.

On Free Edition (Default Storage) the catalogs REST API, which the bundle `catalogs` resource uses,
fails with "Metastore storage root URL does not exist". SQL `CREATE CATALOG` works, so the catalog is
created through the SQL Statement Execution API on a SQL warehouse instead. Schemas and jobs stay in
the bundle. The catalog is owned by whoever runs this: `gov-deployer` in CI (ADR-0006).
"""

from __future__ import annotations

import time
from collections.abc import Callable

from gov_engine.spec import Spec
from gov_engine.tag_policies import ApiCall

WAREHOUSES = "/api/2.0/sql/warehouses"
STATEMENTS = "/api/2.0/sql/statements"
COMMENT = "Governed lakehouse ({env}). Access, tags and policies managed by gov_engine."


def pick_warehouse(api: ApiCall) -> str:
    """First serverless warehouse, else the first one."""
    warehouses = api("GET", WAREHOUSES, None, None).get("warehouses", [])
    if not warehouses:
        raise RuntimeError("no SQL warehouse found; pass --warehouse-id")
    serverless = [w for w in warehouses if w.get("enable_serverless_compute")]
    return (serverless or warehouses)[0]["id"]


def run_statement(api: ApiCall, warehouse_id: str, sql: str, poll_seconds: float = 2.0) -> None:
    resp = api("POST", STATEMENTS, None, {"warehouse_id": warehouse_id, "statement": sql, "wait_timeout": "50s"})
    while resp.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(poll_seconds)
        resp = api("GET", f"{STATEMENTS}/{resp['statement_id']}", None, None)
    status = resp.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(f"{sql!r} failed: {status.get('error', {}).get('message', status)}")


def ensure_catalog(spec: Spec, env: str, api: ApiCall, warehouse_id: str | None = None,
                   dry_run: bool = False, log: Callable[[str], None] = print) -> str:
    """CREATE CATALOG IF NOT EXISTS for env. Returns the SQL."""
    catalog = spec.layout.environments[env]
    comment = COMMENT.format(env=env).replace("'", "''")
    sql = f"CREATE CATALOG IF NOT EXISTS {catalog} COMMENT '{comment}'"
    if not dry_run:
        run_statement(api, warehouse_id or pick_warehouse(api), sql)
    log(f"[{'dry-run' if dry_run else 'ok'}] [catalog] {sql}")
    return sql
