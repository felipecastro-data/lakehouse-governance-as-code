from gov_engine.render import PHASES, expand_grants, render_access_matrix, render_plan


def _sql(spec, env, phase):
    return [s.sql for s in render_plan(spec, env, (phase,))]


def test_phases_are_in_dependency_order(spec):
    phases = [s.phase for s in render_plan(spec, "dev")]
    assert phases == sorted(phases, key=PHASES.index)
    assert phases.index("reference_data") < phases.index("functions") < phases.index("masks")


def test_can_see_is_generated_from_classification(spec):
    can_see = next(s for s in _sql(spec, "prod", "functions") if "can_see(level" in s)
    assert "WHEN 'public' THEN TRUE" in can_see
    assert "WHEN 'restricted' THEN is_account_group_member('gov-pii-restricted-readers')" in can_see
    assert "gov_prod.governance.can_see" in can_see


def test_one_mask_function_per_pii_type(spec):
    masks = [s for s in _sql(spec, "dev", "functions") if ".mask_" in s.splitlines()[0]]
    assert len(masks) == len(spec.classification.pii_types)
    dob = next(s for s in masks if "mask_date_of_birth" in s)
    assert "(v DATE)" in dob and "RETURNS DATE" in dob


def test_engineers_cannot_modify_prod(spec):
    prod = expand_grants(spec, "prod")
    dev = expand_grants(spec, "dev")
    eng_prod = [p for (sec, who), p in prod.items() if who == "data_engineers"]
    eng_dev = [p for (sec, who), p in dev.items() if who == "data_engineers"]
    assert not any("MODIFY" in p for p in eng_prod)
    assert any("MODIFY" in p for p in eng_dev)


def test_analysts_only_reach_gold(spec):
    schemas = {sec for (sec, who) in expand_grants(spec, "prod") if who == "analysts_amer" and sec.startswith("SCHEMA")}
    assert schemas == {"SCHEMA gov_prod.customer_gold", "SCHEMA gov_prod.sales_gold"}


def test_bronze_is_engineers_and_admins_only(spec):
    grants = expand_grants(spec, "prod")
    bronze_principals = {who for (sec, who) in grants if sec.endswith("_bronze")}
    assert bronze_principals == {"data_engineers"}  # admins inherit from the catalog grant


def test_grants_target_groups_with_quoted_names(spec):
    grants = _sql(spec, "prod", "grants")
    assert "GRANT USE SCHEMA, SELECT ON SCHEMA gov_prod.customer_gold TO `gov-analysts-amer`" in grants


def test_pii_columns_get_tags_and_masks(spec):
    tags = _sql(spec, "prod", "tags")
    masks = _sql(spec, "prod", "masks")
    assert ("ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `email` "
            "SET TAGS ('classification' = 'confidential', 'pii_type' = 'email')") in tags
    assert ("ALTER TABLE gov_prod.customer_silver.customers ALTER COLUMN `email` "
            "SET MASK gov_prod.governance.mask_email") in masks
    assert not any("`region`" in m for m in masks)


def test_table_tags_include_owner_and_classification(spec):
    tags = _sql(spec, "prod", "tags")
    assert any(
        s.startswith("ALTER TABLE gov_prod.sales_silver.orders SET TAGS")
        and "'classification' = 'restricted'" in s and "'owner' = 'gov-sales-stewards'" in s
        for s in tags
    )


def test_row_filter_uses_mapping_table(spec):
    ref = _sql(spec, "dev", "reference_data")
    assert any("INSERT OVERWRITE gov_dev.governance.region_access" in s and "('gov-analysts-amer', 'AMER')" in s
               for s in ref)
    filters = _sql(spec, "dev", "row_filters")
    assert ("ALTER TABLE gov_dev.customer_gold.customer_360 "
            "SET ROW FILTER gov_dev.governance.filter_region ON (`region`)") in filters


def test_render_is_deterministic(spec):
    assert render_plan(spec, "prod") == render_plan(spec, "prod")


def test_access_matrix_lists_every_principal(spec):
    matrix = render_access_matrix(spec, "prod")
    for principal in spec.access.principals:
        assert f"`{principal}`" in matrix
