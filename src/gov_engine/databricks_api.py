"""ApiCall adapters: the Databricks SDK inside jobs, the Databricks CLI on a laptop or in CI."""

from __future__ import annotations

import json
import subprocess
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
