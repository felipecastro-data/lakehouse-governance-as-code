"""Scorecard over the fake information_schema from test_drift plus a small lineage graph."""

import pytest
from test_drift import CATALOG, clean_state

from gov_engine.drift import QUERIES
from gov_engine.lineage import TAGS_SQL
from gov_engine.scorecard import TABLES, TABLES_SQL, build_scorecard

RAW, SILVER, GOLD = "gov_dev.customer_bronze.customers_raw", "gov_dev.customer_silver.customers", \
    "gov_dev.customer_gold.customer_360"


def fake_query(state, edges):
    by_sql = {sql.format(c=CATALOG): name for name, sql in QUERIES.items()}

    def query(sql):
        if sql in by_sql:
            return state[by_sql[sql]]
        if sql == TABLES_SQL.format(c=CATALOG):
            return [{"table_schema": s, "table_name": t}
                    for s, t in sorted({(c["table_schema"], c["table_name"]) for c in state["columns"]})]
        if sql == TAGS_SQL.format(c=CATALOG):
            return [r for r in state["column_tags"]
                    if r["tag_name"] == "pii_type" or r["tag_name"].startswith("class.")]
        assert "audit.column_lineage" in sql, sql
        return [{"source_table_full_name": s.rsplit(".", 1)[0], "source_column_name": s.rsplit(".", 1)[1],
                 "target_table_full_name": t.rsplit(".", 1)[0], "target_column_name": t.rsplit(".", 1)[1]}
                for s, t in edges]
    return query


@pytest.fixture
def state(spec):
    return clean_state(spec)


def card(spec, state, edges=((f"{RAW}.email", f"{SILVER}.email"),)):
    result = build_scorecard(spec, "dev", fake_query(state, edges))
    return result, {m.name: m for m in result.metrics}


def test_declared_state_scores_full_coverage(spec, state):
    result, m = card(spec, state)
    assert [m[k].value for k in ("pct_owned", "pct_classified", "pct_pii_masked")] == [100.0, 100.0, 100.0]
    assert m["pct_owned"].denominator == len(spec.tables)
    assert (m["drift_critical"].value, m["drift_warning"].value, m["untagged_pii"].value) == (0, 0, 0)
    assert result.finding_rows() == []


def test_bronze_is_classified_from_lineage_not_counted_in_coverage(spec, state):
    result, m = card(spec, state)
    raw = next(t for t in result.inventory if t["table_full_name"] == RAW)
    assert (raw["layer"], raw["classification"], raw["classified_by"], raw["pii_columns"]) == \
        ("bronze", "confidential", "lineage", 1)
    assert raw["owner"] is None and m["pct_owned"].value == 100.0


def test_missing_mask_policy_lowers_pii_masked_and_is_critical_drift(spec, state):
    state["policies"] = [p for p in state["policies"] if p["policy_name"] != "mask_email"]
    result, m = card(spec, state)
    emails = sum(1 for r in state["column_tags"] if r["tag_name"] == "pii_type" and r["tag_value"] == "email")
    assert m["pct_pii_masked"].denominator - m["pct_pii_masked"].numerator == emails
    assert m["drift_critical"].value == 1
    assert {r["check_name"] for r in result.finding_rows()} == {"drift"}


def test_untagged_pii_counts_against_coverage(spec, state):
    """A gold column fed by a tagged email column but carrying no pii_type tag is unmasked PII."""
    state["column_tags"] = [r for r in state["column_tags"]
                            if not (r["table_name"] == "customer_360" and r["column_name"] == "email")]
    result, m = card(spec, state, edges=[(f"{SILVER}.email", f"{GOLD}.email")])
    assert m["untagged_pii"].value == 1
    assert m["pct_pii_masked"].numerator == m["pct_pii_masked"].denominator - 1
    [row] = [r for r in result.finding_rows() if r["check_name"] == "pii_propagation"]
    assert row["securable"] == f"{GOLD}.email"


def test_output_rows_match_table_columns(spec, state):
    result, _ = card(spec, state, edges=())
    columns = {name: [c.split()[0] for c in ddl.split(", ")] for name, (ddl, _) in TABLES.items()}
    assert all(list(row) == columns["table_inventory"] for row in result.inventory)
    state["policies"] = []
    result, _ = card(spec, state, edges=())
    assert all(["run_id", "run_time", *row] == columns["findings"] for row in result.finding_rows())
    assert ["run_id", "run_time", "metric", "value", "numerator", "denominator", "description"] == columns["scorecard"]
