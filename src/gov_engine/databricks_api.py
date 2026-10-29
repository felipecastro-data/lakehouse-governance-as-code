"""ApiCall adapters (the Databricks SDK inside jobs, the Databricks CLI on a laptop or in CI) and SQL
through the Statement Execution API on a SQL warehouse."""

from __future__ import annotations

import json
import subprocess
import time
from typing import Any
from urllib.parse import urlencode

from gov_engine.tag_policies import ApiCall


def sdk_api() -> ApiCall:
    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient()

    def call(method: str, path: str, query: dict[str, str] | None, body: dict[str, Any] | None) -> dict[str, Any]:
        return client.api_client.do(method, path, query=query, body=body) or {}

    return call


def cli_api(profile: str | None = None) -> ApiCall:
    def call(method: str, path: str, query: dict[str, str] | None, body: dict[str, Any] | None) -> dict[str, Any]:
        url = f"{path}?{urlencode(query)}" if query else path
        cmd = ["databricks", "api", method.lower(), url]
        if body is not None:
            cmd += ["--json", json.dumps(body)]
        if profile:
            cmd += ["--profile", profile]
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if out.returncode:
            raise RuntimeError(f"databricks api {method} {path} failed: {out.stderr.strip()}")
        return json.loads(out.stdout) if out.stdout.strip() else {}

    return call


WAREHOUSES = "/api/2.0/sql/warehouses"
STATEMENTS = "/api/2.0/sql/statements"


def pick_warehouse(api: ApiCall) -> str:
    """First serverless warehouse, else the first one."""
    warehouses = api("GET", WAREHOUSES, None, None).get("warehouses", [])
    if not warehouses:
        raise RuntimeError("no SQL warehouse found; pass --warehouse-id")
    serverless = [w for w in warehouses if w.get("enable_serverless_compute")]
    return (serverless or warehouses)[0]["id"]


def run_statement(api: ApiCall, warehouse_id: str, sql: str, poll_seconds: float = 2.0) -> dict[str, Any]:
    resp = api("POST", STATEMENTS, None, {"warehouse_id": warehouse_id, "statement": sql, "wait_timeout": "50s",
                                          "disposition": "INLINE", "format": "JSON_ARRAY"})
    while resp.get("status", {}).get("state") in ("PENDING", "RUNNING"):
        time.sleep(poll_seconds)
        resp = api("GET", f"{STATEMENTS}/{resp['statement_id']}", None, None)
    status = resp.get("status", {})
    if status.get("state") != "SUCCEEDED":
        raise RuntimeError(f"{sql!r} failed: {status.get('error', {}).get('message', status)}")
    return resp


def query_rows(api: ApiCall, warehouse_id: str, sql: str) -> list[dict[str, Any]]:
    """Rows as dicts. JSON_ARRAY returns every value as a string; arrays and structs are JSON-decoded."""
    resp = run_statement(api, warehouse_id, sql)
    columns = resp.get("manifest", {}).get("schema", {}).get("columns", [])
    result = resp.get("result", {})
    data = list(result.get("data_array") or [])
    while (chunk := result.get("next_chunk_index")) is not None:
        result = api("GET", f"{STATEMENTS}/{resp['statement_id']}/result/chunks/{chunk}", None, None)
        data += result.get("data_array") or []

    def decode(value: str | None, type_name: str) -> Any:
        return json.loads(value) if value is not None and type_name in ("ARRAY", "STRUCT", "MAP") else value

    return [{c["name"]: decode(v, c.get("type_name", "")) for c, v in zip(columns, row, strict=True)} for row in data]
