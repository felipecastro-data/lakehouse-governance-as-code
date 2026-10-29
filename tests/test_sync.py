"""Tag policy and group sync against a fake Databricks API."""

from gov_engine.identity import ACCOUNT_GROUPS, ASSIGNMENTS, sync_groups
from gov_engine.tag_policies import API, desired_tag_policies, sync_tag_policies


class FakeApi:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, method, path, query, body):
        self.calls.append((method, path, query, body))
        return self.responses.get((method, path), {})

    def writes(self):
        return [(m, p) for m, p, _, _ in self.calls if m != "GET"]


def test_tag_policies_cover_levels_pii_types_and_filters(spec):
    keys = {tp["tag_key"]: [v["name"] for v in tp["values"]] for tp in desired_tag_policies(spec)}
    assert keys["classification"] == ["public", "internal", "confidential", "restricted"]
    assert "email" in keys["pii_type"]
    assert keys["filter_key"] == ["region"]


def test_sync_creates_missing_and_updates_changed(spec):
    desired = {tp["tag_key"]: tp for tp in desired_tag_policies(spec)}
    stale = dict(desired["pii_type"], values=[{"name": "email"}])
    api = FakeApi({("GET", API): {"tag_policies": [desired["classification"], stale]}})

    created = sync_tag_policies(spec, api, log=lambda _: None)

    assert created is True
    assert api.writes() == [("PATCH", f"{API}/pii_type"), ("POST", API)]


def test_sync_is_noop_when_in_sync(spec):
    api = FakeApi({("GET", API): {"tag_policies": desired_tag_policies(spec)}})
    assert sync_tag_policies(spec, api, log=lambda _: None) is False
    assert api.writes() == []


def test_dry_run_writes_nothing(spec):
    api = FakeApi({("GET", API): {"tag_policies": []}})
    sync_tag_policies(spec, api, dry_run=True, log=lambda _: None)
    sync_groups(spec, api, dry_run=True, log=lambda _: None)
    assert api.writes() == []


def test_groups_are_created_through_the_account_api_and_assigned(spec):
    api = FakeApi({
        ("GET", ACCOUNT_GROUPS): {"totalResults": 1, "Resources": [{"displayName": "gov-auditors", "id": "7"}]},
        ("POST", ACCOUNT_GROUPS): {"id": "42"},
        ("GET", ASSIGNMENTS): {"permission_assignments": [{"principal": {"group_name": "gov-pii-readers"}}]},
    })
    created = sync_groups(spec, api, log=lambda _: None)
    n = len(spec.access.principals)

    assert "gov-auditors" not in created and len(created) == n - 1
    writes = api.writes()
    assert writes.count(("POST", ACCOUNT_GROUPS)) == n - 1
    puts = [(p, b) for m, p, _, b in api.calls if m == "PUT"]
    assert len(puts) == n - 1  # everything except the already assigned gov-pii-readers
    assert (f"{ASSIGNMENTS}/principals/7", {"permissions": ["USER"]}) in puts


def test_ensure_catalog_runs_sql_on_a_serverless_warehouse(spec):
    from gov_engine.catalog import ensure_catalog
    from gov_engine.databricks_api import STATEMENTS, WAREHOUSES

    api = FakeApi({
        ("GET", WAREHOUSES): {"warehouses": [{"id": "classic"}, {"id": "sls", "enable_serverless_compute": True}]},
        ("POST", STATEMENTS): {"statement_id": "1", "status": {"state": "SUCCEEDED"}},
    })
    create, drop = ensure_catalog(spec, "dev", api, log=lambda _: None)

    assert create.startswith("CREATE CATALOG IF NOT EXISTS gov_dev COMMENT")
    assert drop == "DROP SCHEMA IF EXISTS gov_dev.default"  # no CASCADE: only dropped while empty
    bodies = [b for m, _, _, b in api.calls if m == "POST"]
    assert [b["statement"] for b in bodies] == [create, drop]
    assert all(b["warehouse_id"] == "sls" for b in bodies)
