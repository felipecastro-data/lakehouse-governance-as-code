"""Groups declared in access_policy.yml, created as **account** groups.

Unity Catalog only resolves account-level principals. On a workspace, `/api/2.0/preview/scim/v2/Groups`
(what `databricks groups create` uses) creates workspace-local groups that grants and ABAC policies
cannot see, so this goes through the workspace proxy for the account SCIM API instead.
Membership is managed by people, not by this engine.
"""

from __future__ import annotations

from collections.abc import Callable

from gov_engine.spec import Spec
from gov_engine.tag_policies import ApiCall

ACCOUNT_GROUPS = "/api/2.0/account/scim/v2/Groups"


def sync_groups(spec: Spec, api: ApiCall, dry_run: bool = False, log: Callable[[str], None] = print) -> list[str]:
    """Create missing account groups. Returns the names created."""
    existing: set[str] = set()
    start = 1
    while True:
        page = api("GET", ACCOUNT_GROUPS, {"startIndex": str(start), "count": "100"}, None)
        resources = page.get("Resources", [])
        existing.update(g["displayName"] for g in resources)
        start += len(resources)
        if not resources or start > int(page.get("totalResults", 0)):
            break

    created = []
    for group in spec.access.principals.values():
        if group in existing:
            log(f"[ok] [groups] exists {group}")
            continue
        if not dry_run:
            api("POST", ACCOUNT_GROUPS, None, {"displayName": group})
        log(f"[{'dry-run' if dry_run else 'ok'}] [groups] create {group}")
        created.append(group)
    return created
