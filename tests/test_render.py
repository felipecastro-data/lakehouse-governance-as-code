from gov_engine.render import PHASES, expand_grants, render_access_matrix, render_plan


def _sql(spec, env, phase):
    return [s.sql for s in render_plan(spec, env, (phase,))]


def test_phases_are_in_dependency_order(spec):
    phases = [s.phase for s in render_plan(spec, "dev")]
    assert phases == sorted(phases, key=PHASES.index)
    assert phases.index("reference_data") < phases.index("functions") < phases.index("policies")


def test_mask_functions_are_pure_transformations(spec):
    masks = [s for s in _sql(spec, "dev", "functions") if ".mask_" in s.splitlines()[0]]
    assert len(masks) == len(spec.classification.pii_types)
    assert not any("is_account_group_member" in m for m in masks), "who is exempt belongs in the policy"
    dob = next(s for s in masks if "mask_date_of_birth" in s)
    assert "(v DATE)" in dob and "RETURNS DATE" in dob


def test_one_mask_policy_per_pii_type_exempts_unmask_groups(spec):
    policies = _sql(spec, "prod", "policies")
    email = next(p for p in policies if p.startswith("CREATE OR REPLACE POLICY mask_email ON CATALOG gov_prod"))
    assert "COLUMN MASK gov_prod.governance.mask_email" in email
    assert "TO `account users` EXCEPT `gov-pii-readers`, `gov-pii-restricted-readers`" in email
    assert "MATCH COLUMNS has_tag_value('pii_type', 'email') OR has_tag('class.email_address') AS col" in email
    card = next(p for p in policies if "POLICY mask_card_number" in p)
    assert "EXCEPT `gov-pii-restricted-readers`\n" in card


def test_row_filter_policy_matches_filter_key_and_bypasses(spec):
    policy = next(p for p in _sql(spec, "dev", "policies") if "POLICY filter_region" in p)
    assert "ROW FILTER gov_dev.governance.filter_region" in policy
    assert "EXCEPT `gov-platform-admins`, `gov-data-engineers`" in policy
    assert "MATCH COLUMNS has_tag_value('filter_key', 'region') AS col\nUSING COLUMNS (col)" in policy


def test_no_per_column_masks_or_filters(spec):
    sql = "\n".join(s.sql for s in render_plan(spec, "prod"))
    assert "SET MASK" not in sql and "SET ROW FILTER" not in sql


def test_engineers_cannot_modify_prod(spec):
    prod = expand_grants(spec, "prod")
    dev = expand_grants(spec, "dev")
    assert not any("MODIFY" in p for (_, who), p in prod.items() if who == "data_engineers")
    assert any("MODIFY" in p for (_, who), p in dev.items() if who == "data_engineers")


def test_analysts_only_reach_gold(spec):
    schemas = {sec for (sec, who) in expand_grants(spec, "prod") if who == "analysts_amer" and sec.startswith("SCHEMA")}
    assert schemas == {"SCHEMA gov_prod.customer_gold", "SCHEMA gov_prod.sales_gold"}


def test_bronze_is_engineers_only(spec):
    bronze_principals = {who for (sec, who) in expand_grants(spec, "prod") if sec.endswith("_bronze")}
    assert bronze_principals == {"data_engineers"}  # admins inherit from the catalog grant


def test_grants_target_groups_with_quoted_names(spec):
    grants = _sql(spec, "prod", "grants")
    assert "GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_gold TO `gov-analysts-amer`" in grants


def test_columns_get_governed_tags(spec):
    tags = _sql(spec, "prod", "tags")
    assert ("ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `email` "
            "SET TAGS ('classification' = 'confidential', 'pii_type' = 'email')") in tags
    assert ("ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `region` "
            "SET TAGS ('classification' = 'internal', 'filter_key' = 'region')") in tags


def test_table_tags_include_owner_and_classification(spec):
    assert any(
        s.startswith("ALTER TABLE gov_prod.sales_silver.orders SET TAGS")
        and "'classification' = 'restricted'" in s and "'owner' = 'gov-sales-stewards'" in s
        for s in _sql(spec, "prod", "tags")
    )


def test_mapping_table_is_rendered_from_policy(spec):
    ref = _sql(spec, "dev", "reference_data")
    assert any("INSERT OVERWRITE gov_dev.governance.region_access" in s and "('gov-analysts-amer', 'AMER')" in s
               for s in ref)


def test_render_is_deterministic(spec):
    assert render_plan(spec, "prod") == render_plan(spec, "prod")


def test_access_matrix_lists_every_principal(spec):
    matrix = render_access_matrix(spec, "prod")
    for principal in spec.access.principals:
        assert f"`{principal}`" in matrix
