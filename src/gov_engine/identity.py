"""Groups declared in access_policy.yml, created as **account** groups.

Unity Catalog only resolves account-level principals. On a workspace, `/api/2.0/preview/scim/v2/Groups`
(what `databricks groups create` uses) creates workspace-local groups that grants and ABAC policies
cannot see, so this goes through the workspace proxy for the account SCIM API instead.
Account groups are then assigned to this workspace (USER), so they show up on the workspace Groups
page and their members can sign in. Membership is managed by people, not by this engine.
"""

from __future__ import annotations

from collections.abc import Callable

from gov_engine.spec import Spec
from gov_engine.tag_policies import ApiCall

ACCOUNT_GROUPS = "/api/2.0/account/scim/v2/Groups"
ASSIGNMENTS = "/api/2.0/preview/permissionassignments"


def sync_groups(spec: Spec, api: ApiCall, dry_run: bool = False, log: Callable[[str], None] = print) -> list[str]:
    """Create missing account groups and assign them to the workspace. Returns the names created."""
    ids: dict[str, str] = {}
    start = 1
    while True:
        page = api("GET", ACCOUNT_GROUPS, {"startIndex": str(start), "count": "100"}, None)
        resources = page.get("Resources", [])
        ids.update((g["displayName"], g.get("id", "")) for g in resources)
        start += len(resources)
        if not resources or start > int(page.get("totalResults", 0)):
            break

    created = []
    for group in spec.access.principals.values():
        if group in ids:
            log(f"[ok] [groups] exists {group}")
            continue
        if not dry_run:
            ids[group] = api("POST", ACCOUNT_GROUPS, None, {"displayName": group}).get("id", "")
        log(f"[{'dry-run' if dry_run else 'ok'}] [groups] create {group}")
        created.append(group)

    assigned = {a["principal"].get("group_name")
                for a in api("GET", ASSIGNMENTS, None, None).get("permission_assignments", [])}
    for group in spec.access.principals.values():
        if group in assigned:
            continue
        if not dry_run:
            api("PUT", f"{ASSIGNMENTS}/principals/{ids[group]}", None, {"permissions": ["USER"]})
        log(f"[{'dry-run' if dry_run else 'ok'}] [groups] assign {group} to workspace")
    return created
