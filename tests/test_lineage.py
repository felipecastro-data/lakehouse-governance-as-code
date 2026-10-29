"""PII propagation over a fake column lineage graph shaped like the dev pipeline."""

from gov_engine.lineage import LINEAGE_SQL, find_untagged_pii

RAW, SILVER, GOLD = "gov_dev.customer_bronze.customers_raw", "gov_dev.customer_silver.customers", \
    "gov_dev.customer_gold.customer_360"


def fake_query(edges, tags):
    def query(sql):
        if "column_lineage" in sql:
            assert "FROM gov_dev.audit.column_lineage" in sql and "target_table_catalog = 'gov_dev'" in sql
            return [{"source_table_full_name": s.rsplit(".", 1)[0], "source_column_name": s.rsplit(".", 1)[1],
                     "target_table_full_name": t.rsplit(".", 1)[0], "target_column_name": t.rsplit(".", 1)[1]}
                    for s, t in edges]
        assert "information_schema.column_tags" in sql
        return [{"schema_name": c.split(".")[1], "table_name": c.split(".")[2], "column_name": c.split(".")[3],
                 "tag_name": k, "tag_value": v} for c, k, v in tags]
    return query


EDGES = [
    (f"{RAW}.email", f"{SILVER}.email"),
    (f"{RAW}.first_name", f"{SILVER}.full_name"),
    (f"{RAW}.country_code", f"{SILVER}.region"),
    (f"{SILVER}.email", f"{GOLD}.email"),
    (f"{SILVER}.region", f"{GOLD}.region"),
]
TAGS = [
    (f"{SILVER}.email", "pii_type", "email"),
    (f"{SILVER}.full_name", "pii_type", "person_name"),
    (f"{GOLD}.email", "pii_type", "email"),
    (f"{SILVER}.region", "filter_key", "region"),  # filtered out by the tags query in real life
]


def test_tagged_pipeline_has_no_findings_and_infers_raw_pii(spec):
    report = find_untagged_pii(spec, "dev", fake_query(EDGES, TAGS[:3]))
    assert report.findings == []
    assert report.inferred_raw_pii == {f"{RAW}.email": "email", f"{RAW}.first_name": "person_name"}
    assert report.edges == len(EDGES)


def test_untagged_downstream_column_is_flagged_transitively(spec):
    """FR9 acceptance: a column fed by PII without a pii_type tag is flagged, and so is what it feeds."""
    edges = [*EDGES,
             (f"{RAW}.email", f"{SILVER}.email_domain"),              # raw PII, inferred from silver.email
             (f"{SILVER}.email_domain", f"{GOLD}.top_domain"),         # leak carried one layer further
             (f"{SILVER}.full_name", "gov_dev.sales_gold.report.name")]
    report = find_untagged_pii(spec, "dev", fake_query(edges, TAGS[:3]))
    assert [(f.source_column, f.target_column, f.pii_type) for f in report.findings] == [
        (f"{SILVER}.email_domain", f"{GOLD}.top_domain", "email"),
        (f"{RAW}.email", f"{SILVER}.email_domain", "email"),
        (f"{SILVER}.full_name", "gov_dev.sales_gold.report.name", "person_name"),
    ]


def test_system_class_tags_count_as_protected(spec):
    edges = [*EDGES, (f"{SILVER}.email", f"{GOLD}.contact")]
    tags = [*TAGS[:3], (f"{GOLD}.contact", "class.email_address", None)]
    assert find_untagged_pii(spec, "dev", fake_query(edges, tags)).findings == []


def test_raw_columns_are_never_targets(spec):
    edges = [(f"{SILVER}.email", f"{RAW}.email_copy")]
    assert find_untagged_pii(spec, "dev", fake_query(edges, TAGS[:1])).findings == []


def test_lineage_sql_keeps_only_the_latest_run_per_table():
    sql = LINEAGE_SQL.format(c="gov_dev", days=30)
    assert "PARTITION BY target_table_full_name" in sql and "= latest_run" in sql
