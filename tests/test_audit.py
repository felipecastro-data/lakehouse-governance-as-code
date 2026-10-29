"""Audit views (FR10) and the scorecard dashboard that reads them (FR11)."""

import json
import re
from pathlib import Path

import yaml

from gov_engine.audit import VIEWS_SQL, create_audit_views, render_audit_views
from gov_engine.render import expand_grants
from gov_engine.scorecard import TABLES

ROOT = Path(__file__).resolve().parents[1]
DEPLOYER = "deployer-sp-id"


def views(catalog="gov_dev"):
    return render_audit_views((ROOT / VIEWS_SQL).read_text(), catalog, DEPLOYER)


def view_names(statements):
    return [m.group(1) for s in statements if (m := re.match(r"CREATE OR REPLACE VIEW \S+\.audit\.(\w+)", s))]


def test_views_are_filled_in_and_live_in_the_audit_schema():
    statements = views("gov_prod")
    assert not any("{{" in s for s in statements)
    creates = [s for s in statements if s.startswith("CREATE")]
    assert len(view_names(statements)) == len(creates)
    assert all(s.startswith("CREATE OR REPLACE VIEW gov_prod.audit.") for s in creates)
    assert all(re.search(r"'%?gov_prod[.%']", s) and "gov_dev" not in s for s in creates), "views filter to the catalog"


def test_only_grant_is_lineage_to_the_deployer():
    """Auditors read the views through their audit schema grant; nobody gets system.* (FR10)."""
    grants = [s for s in views() if not s.startswith("CREATE")]
    assert grants == [f"GRANT SELECT ON VIEW gov_dev.audit.column_lineage TO `{DEPLOYER}`"]


def test_auditors_get_the_audit_schema_and_nothing_else(spec):
    for env, catalog in spec.layout.environments.items():
        grants = {s: privs for (s, p), privs in expand_grants(spec, env).items() if p == "auditors"}
        assert grants == {f"CATALOG {catalog}": ["USE_CATALOG"], f"SCHEMA {catalog}.audit": ["USE_SCHEMA", "SELECT"]}


def test_create_audit_views_runs_as_the_caller_and_grants_the_catalog_owner(spec):
    calls = []

    def api(method, path, query, body):
        calls.append(body["statement"])
        if "information_schema.catalogs" in body["statement"]:
            return {"status": {"state": "SUCCEEDED"}, "manifest": {"schema": {"columns": [{"name": "catalog_owner"}]}},
                    "result": {"data_array": [[DEPLOYER]]}}
        return {"status": {"state": "SUCCEEDED"}}

    statements = create_audit_views(spec, "dev", ROOT, api, "wh", log=lambda _: None)
    assert calls[0].endswith("catalog_name = 'gov_dev'") and calls[1:] == statements == views()


def dashboard():
    return json.loads((ROOT / "src" / "dashboards" / "governance_scorecard.lvdash.json").read_text())


def test_dashboard_reads_only_audit_objects():
    known = set(view_names(views())) | set(TABLES)
    for ds in dashboard()["datasets"]:
        sql = "".join(ds["queryLines"])
        assert "system." not in sql and "information_schema" not in sql, ds["name"]
        ctes = set(re.findall(r"(?:WITH|,)\s*(\w+) AS \(", sql))
        tables = set(re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE)) - ctes
        assert tables <= known, f"{ds['name']} reads {tables - known}"


def test_dashboard_widgets_use_declared_datasets_and_fields():
    d = dashboard()
    datasets = {ds["name"]: "".join(ds["queryLines"]) for ds in d["datasets"]}
    for page in d["pages"]:
        for item in page["layout"]:
            for q in item["widget"].get("queries", []):
                sql = datasets[q["query"]["datasetName"]]
                for f in q["query"]["fields"]:
                    assert re.search(rf"\b{f['name']}\b", sql), f"{item['widget']['name']}: {f['name']}"


def test_dashboard_resource_is_for_auditors_without_embedded_credentials(spec):
    res = yaml.safe_load((ROOT / "resources" / "governance_scorecard.dashboard.yml").read_text())
    dash = res["resources"]["dashboards"]["governance_scorecard"]
    assert dash["embed_credentials"] is False, "viewers must query with their own grants"
    assert (dash["dataset_catalog"], dash["dataset_schema"]) == ("${var.catalog}", "audit")
    assert dash["permissions"] == [{"group_name": spec.group("auditors"), "level": "CAN_VIEW"}]
    assert (ROOT / "resources" / dash["file_path"]).resolve().exists()
