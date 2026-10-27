import pytest
import yaml

from gov_engine.spec import SpecError, load_spec


def _edit(root, rel, fn):
    path = root / "governance" / rel
    data = yaml.safe_load(path.read_text())
    fn(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _errors(root):
    with pytest.raises(SpecError) as exc:
        load_spec(root)
    return "\n".join(exc.value.errors)


def test_repository_spec_is_valid(spec):
    assert {t.name for t in spec.tables} == {"customers", "orders", "customer_360"}


def test_pii_column_inherits_its_type_level(spec):
    customers = next(t for t in spec.tables if t.name == "customers")
    national_id = next(c for c in customers.columns if c.name == "national_id")
    assert spec.column_classification(national_id) == "restricted"
    assert spec.table_classification(customers) == "restricted"


def test_unknown_principal_is_rejected(spec_copy):
    _edit(spec_copy, "access_policy.yml", lambda d: d["grants"][0]["principals"].append("ghosts"))
    assert "unknown principal 'ghosts'" in _errors(spec_copy)


def test_unknown_privilege_is_rejected(spec_copy):
    _edit(spec_copy, "access_policy.yml", lambda d: d["grants"][0]["privileges"].append("ALL_POWER"))
    assert "unknown privilege 'ALL_POWER'" in _errors(spec_copy)


def test_classification_cannot_be_lowered_below_pii_level(spec_copy):
    def lower(d):
        email = next(p for p in d["schema"][0]["properties"] if p["name"] == "email")
        email["classification"] = "public"

    _edit(spec_copy, "contracts/customer.customers.yml", lower)
    assert "below the 'confidential' required for piiType 'email'" in _errors(spec_copy)


def test_mask_strategy_must_match_column_type(spec_copy):
    def retype(d):
        dob = next(p for p in d["schema"][0]["properties"] if p["name"] == "date_of_birth")
        dob["logicalType"] = "string"

    _edit(spec_copy, "contracts/customer.customers.yml", retype)
    assert "returns DATE, column is string" in _errors(spec_copy)


def test_row_filter_column_must_exist(spec_copy):
    _edit(spec_copy, "access_policy.yml", lambda d: d["row_filters"]["region"].update(column="territory"))
    errors = _errors(spec_copy)
    assert "needs column 'territory'" in errors


def test_contract_schema_must_exist_in_layout(spec_copy):
    def move(d):
        d["schema"][0]["physicalName"] = "marketing_gold.customer_360"

    _edit(spec_copy, "contracts/customer.customer_360.yml", move)
    assert "schema 'marketing_gold' is not in layout" in _errors(spec_copy)


def test_all_errors_reported_at_once(spec_copy):
    def break_two(d):
        d["grants"][0]["principals"].append("ghosts")
        d["grants"][0]["privileges"].append("ALL_POWER")

    _edit(spec_copy, "access_policy.yml", break_two)
    errors = _errors(spec_copy)
    assert "ghosts" in errors and "ALL_POWER" in errors


def test_system_tags_must_be_class_tags(spec_copy):
    _edit(spec_copy, "classification.yml", lambda d: d["pii_types"]["email"].update(system_tags=["pii_email"]))
    assert "'pii_email' is not a `class.*` system tag" in _errors(spec_copy)


def test_contract_quality_rules_are_validated(spec_copy):
    def break_rules(d):
        d["quality"] = [
            {"rule": "isFresh", "column": "order_id"},
            {"rule": "uniqueness", "column": "nope"},
            {"rule": "referentialIntegrity", "column": "customer_id", "references": "customer.ghosts.id"},
        ]
    _edit(spec_copy, "contracts/sales.orders.yml", break_rules)
    errors = _errors(spec_copy)
    assert "quality isFresh(order_id): unknown rule" in errors
    assert "quality uniqueness(nope): unknown column" in errors
    assert "references 'customer.ghosts.id' is not <contract id>.<column>" in errors
