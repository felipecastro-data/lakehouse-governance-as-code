"""Drift detection against a fake information_schema built from the spec itself."""

import pytest

from gov_engine.drift import QUERIES, detect_drift
from gov_engine.render import DDL_TYPES, declared_policies, declared_tags, expand_grants

CATALOG = "gov_dev"


def clean_state(spec):
    """information_schema rows for an environment exactly as declared."""
    grants = expand_grants(spec, "dev")
    tags = declared_tags(spec, "dev")
    state = {name: [] for name in QUERIES}
    state["owner"] = [{"catalog_owner": "deployer-sp-id"}]
    state["schemas"] = [{"schema_name": s} for s in [*spec.layout.all_schemas(), "information_schema"]]
    for (securable, principal), privs in grants.items():
        kind, name = securable.split(" ", 1)
        for priv in privs:
            row = {"grantee": spec.group(principal), "privilege_type": priv}
            if kind == "CATALOG":
                state["catalog_privileges"].append(row)
            else:
                state["schema_privileges"].append({**row, "schema_name": name.split(".")[1]})
    for t in spec.tables:
        for c in t.columns:
            state["columns"].append({"table_schema": t.schema, "table_name": t.name, "column_name": c.name,
                                     "full_data_type": DDL_TYPES[c.logical_type].lower(),
                                     "is_nullable": "NO" if c.required else "YES"})
    state["columns"] += [{"table_schema": "customer_bronze", "table_name": "customers_raw", "column_name": "email",
                          "full_data_type": "string", "is_nullable": "YES"}]
    for (fq, column), pairs in tags.items():
        _, schema, table = fq.split(".")
        for k, v in pairs.items():
            row = {"schema_name": schema, "table_name": table, "tag_name": k, "tag_value": v}
            state["column_tags" if column else "table_tags"].append({**row, "column_name": column} if column else row)
    state["column_tags"].append({"schema_name": "customer_silver", "table_name": "customers",
                                 "column_name": "email", "tag_name": "class.email_address", "tag_value": None})
    state["policies"] = [{"policy_name": p.name, "policy_type": p.policy_type, "on_securable_type": "CATALOG",
                          "to_principals": ["account users"], "except_principals": list(p.exempt)}
                         for p in declared_policies(spec, "dev")]
    return state


def fake_query(state):
    by_sql = {sql.format(c=CATALOG): name for name, sql in QUERIES.items()}

    def query(sql):
        return state[by_sql[sql]]
    return query


@pytest.fixture
def state(spec):
    return clean_state(spec)


def drift(spec, state):
    return detect_drift(spec, "dev", fake_query(state))


def test_declared_state_has_no_drift(spec, state):
    assert drift(spec, state) == []


def test_manual_grant_is_critical_drift(spec, state):
    """FR8 acceptance: a GRANT outside the spec shows up as drift."""
    state["schema_privileges"].append({"schema_name": "customer_bronze", "grantee": "gov-analysts-amer",
                                       "privilege_type": "SELECT"})
    state["table_privileges"].append({"table_schema": "customer_silver", "table_name": "customers",
                                      "grantee": "someone@example.com", "privilege_type": "SELECT"})
    found = drift(spec, state)
    assert [(f.severity, f.kind, f.securable) for f in found] == [
        ("critical", "grant", "SCHEMA gov_dev.customer_bronze"),
        ("critical", "grant", "TABLE gov_dev.customer_silver.customers"),
    ]
    assert "individual user someone@example.com" in found[1].detail


def test_grants_to_the_catalog_owner_are_not_drift(spec, state):
    """The deployer owns the catalog; the account admin who owns audit.column_lineage grants it SELECT."""
    state["table_privileges"].append({"table_schema": "audit", "table_name": "column_lineage",
                                      "grantee": "deployer-sp-id", "privilege_type": "SELECT"})
    assert drift(spec, state) == []


def test_revoked_grant_is_a_warning(spec, state):
    state["catalog_privileges"] = [r for r in state["catalog_privileges"] if r["grantee"] != "gov-auditors"]
    [f] = drift(spec, state)
    assert (f.severity, f.securable) == ("warning", "CATALOG gov_dev") and "USE_CATALOG" in f.detail


def test_removed_pii_tag_is_critical(spec, state):
    state["column_tags"] = [r for r in state["column_tags"]
                            if not (r["column_name"] == "email" and r["tag_name"] == "pii_type")]
    found = drift(spec, state)
    assert {(f.severity, f.securable, f.detail) for f in found} == {
        ("critical", "gov_dev.customer_gold.customer_360.email", "pii_type=email is missing"),
        ("critical", "gov_dev.customer_silver.customers.email", "pii_type=email is missing"),
    }


def test_undeclared_engine_tag_is_a_warning_and_other_tags_are_ignored(spec, state):
    state["column_tags"].append({"schema_name": "customer_bronze", "table_name": "customers_raw",
                                 "column_name": "email", "tag_name": "pii_type", "tag_value": "email"})
    [f] = drift(spec, state)
    assert (f.severity, f.kind, f.securable) == ("warning", "tag", "gov_dev.customer_bronze.customers_raw.email")


def test_policy_exemption_and_missing_policy_are_critical(spec, state):
    email = next(p for p in state["policies"] if p["policy_name"] == "mask_email")
    email["except_principals"] = [*email["except_principals"], "gov-analysts-amer"]
    state["policies"] = [p for p in state["policies"] if p["policy_name"] != "filter_region"]
    state["policies"].append({"policy_name": "allow_all", "policy_type": "GRANT", "on_securable_type": "CATALOG",
                              "to_principals": ["account users"], "except_principals": []})
    found = {(f.severity, f.securable): f.detail for f in drift(spec, state)}
    assert "undeclared: ['gov-analysts-amer']" in found[("critical", "mask_email")]
    assert found[("critical", "filter_region")] == "declared but missing"
    assert found[("critical", "allow_all")] == "undeclared GRANT policy"


def test_contract_and_table_mismatches(spec, state):
    cols = state["columns"]
    next(c for c in cols if c["table_name"] == "orders" and c["column_name"] == "amount")["full_data_type"] = "double"
    next(c for c in cols if c["table_name"] == "orders" and c["column_name"] == "region")["is_nullable"] = "YES"
    cols.append({"table_schema": "sales_silver", "table_name": "orders", "column_name": "ip_address",
                 "full_data_type": "string", "is_nullable": "YES"})
    cols.append({"table_schema": "sales_gold", "table_name": "scratch", "column_name": "x",
                 "full_data_type": "string", "is_nullable": "YES"})
    state["columns"] = [c for c in cols if c["table_name"] != "customer_360"]  # dropped table: tags not compared
    state["schemas"].append({"schema_name": "tmp"})
    found = {(f.kind, f.securable): f.detail for f in drift(spec, state)}
    assert found == {
        ("column", "gov_dev.sales_silver.orders.amount"): "type double, contract says decimal(18,2)",
        ("column", "gov_dev.sales_silver.orders.region"): "nullable, contract says required",
        ("column", "gov_dev.sales_silver.orders.ip_address"): "not in contract sales.orders",
        ("table", "gov_dev.sales_gold.scratch"): "no data contract",
        ("table", "gov_dev.customer_gold.customer_360"): "contract customer.customer_360 table is missing",
        ("schema", "gov_dev.tmp"): "not declared in layout.yml",
    }


def test_per_column_mask_outside_abac(spec, state):
    state["column_masks"].append({"table_schema": "sales_silver", "table_name": "orders",
                                  "column_name": "card_number", "mask_name": "gov_dev.x.m"})
    [f] = drift(spec, state)
    assert (f.severity, f.kind) == ("warning", "mask")
