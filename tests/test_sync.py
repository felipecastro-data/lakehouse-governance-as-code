"""Tag policy and group sync against a fake Databricks API."""

from gov_engine.identity import ACCOUNT_GROUPS, sync_groups
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


def test_groups_are_created_through_the_account_api(spec):
    api = FakeApi({("GET", ACCOUNT_GROUPS): {"totalResults": 1, "Resources": [{"displayName": "gov-auditors"}]}})
    created = sync_groups(spec, api, log=lambda _: None)
    assert "gov-auditors" not in created
    assert len(created) == len(spec.access.principals) - 1
    assert all(path == ACCOUNT_GROUPS for _, path in api.writes())
