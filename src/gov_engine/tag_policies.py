"""Governed tags (tag policies): the allowed keys and values that ABAC policies match on.

Tag policies are account-level objects managed through the REST API, not SQL, so they are synced
separately and before the SQL plan. New tag policies take about a minute to become visible to
`CREATE POLICY`; `sync_tag_policies` reports whether any were created so the caller can wait.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gov_engine.render import MANAGED_BY, TAG_CLASSIFICATION, TAG_FILTER_KEY, TAG_PII_TYPE
from gov_engine.spec import Spec

API = "/api/2.1/tag-policies"

# api(method, path, query, body) -> parsed JSON response
ApiCall = Callable[[str, str, dict[str, str] | None, dict[str, Any] | None], dict[str, Any]]


def desired_tag_policies(spec: Spec) -> list[dict[str, Any]]:
    def policy(key: str, description: str, values: list[str]) -> dict[str, Any]:
        return {"tag_key": key, "description": f"{description} {MANAGED_BY}",
                "values": [{"name": v} for v in values]}

    return [
        policy(TAG_CLASSIFICATION, "Data sensitivity level.", spec.classification.level_names()),
        policy(TAG_PII_TYPE, "Kind of personal data in a column; drives column masks.",
               list(spec.classification.pii_types)),
        policy(TAG_FILTER_KEY, "Column a row filter policy applies to.", list(spec.access.row_filters)),
    ]


def _list_existing(api: ApiCall) -> dict[str, dict[str, Any]]:
    existing: dict[str, dict[str, Any]] = {}
    query: dict[str, str] | None = None
    while True:
        page = api("GET", API, query, None)
        for tp in page.get("tag_policies", []):
            existing[tp["tag_key"]] = tp
        token = page.get("next_page_token")
        if not token:
            return existing
        query = {"page_token": token}


def _values(tp: dict[str, Any]) -> list[str]:
    return sorted(v["name"] for v in tp.get("values", []))


def sync_tag_policies(
    spec: Spec, api: ApiCall, dry_run: bool = False, log: Callable[[str], None] = print
) -> bool:
    """Create or update the engine's governed tags. Returns True if any tag policy was created."""
    existing = _list_existing(api)
    created = False
    for want in desired_tag_policies(spec):
        key = want["tag_key"]
        have = existing.get(key)
        if have is None:
            action = "create"
            if not dry_run:
                api("POST", API, None, want)
            created = True
        elif _values(have) != _values(want) or have.get("description") != want["description"]:
            action = "update"
            if not dry_run:
                api("PATCH", f"{API}/{key}", {"update_mask": "description,values"}, want)
        else:
            action = "unchanged"
        log(f"[{'dry-run' if dry_run else 'ok'}] [tag_policies] {action} {key} = {_values(want)}")
    return created
