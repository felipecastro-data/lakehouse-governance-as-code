"""Right to erasure (FR12): request rendering, scope, verification, and the job wiring."""

from pathlib import Path

import pytest
import yaml
from test_spec import _edit, _errors

from gov_engine.erasure import (
    SCOPE_SQL,
    check_erasure,
    render_delete,
    render_request,
    report_erasure,
    scope,
)
from gov_engine.render import render_plan

ROOT = Path(__file__).resolve().parents[1]
RAW_C, RAW_O = "gov_dev.customer_bronze.customers_raw", "gov_dev.sales_bronze.orders_raw"
SILVER_C, SILVER_O = "gov_dev.customer_silver.customers", "gov_dev.sales_silver.orders"
GOLD = "gov_dev.customer_gold.customer_360"
KEYED = [RAW_C, RAW_O, SILVER_C, SILVER_O, GOLD]


def fake_query(tables=KEYED, requests=0, residual=None, edges=()):
    def query(sql):
        if sql.startswith(SCOPE_SQL.split("{")[0]):
            assert "'governance'" not in sql and "'audit'" not in sql, "only domain schemas hold subjects"
            return [{"table_schema": t.split(".")[1], "table_name": t.split(".")[2]} for t in tables]
        if "UNION ALL" in sql:
            return [{"table_full_name": t, "n": str(n)} for t, n in (residual or {}).items()]
        if "count(*) AS n FROM gov_dev.governance.erasure_requests" in sql:
            return [{"n": str(requests)}]
        assert "audit.column_lineage" in sql, sql
        return [{"source_table_full_name": s, "source_column_name": "x", "target_table_full_name": t,
                 "target_column_name": "x"} for s, t in edges]
    return query


def test_scope_is_every_keyed_domain_table_downstream_first(spec):
    assert scope(spec, "dev", fake_query()) == [GOLD, SILVER_C, SILVER_O, RAW_C, RAW_O]


def test_request_stores_only_the_hash_and_is_idempotent(spec):
    sql = render_request(spec, "dev", "DSR-0001", "C000042")
    assert "sha2('C000042', 256)" in sql
    assert "MERGE INTO gov_dev.governance.erasure_requests" in sql and "WHEN NOT MATCHED" in sql
    assert "subject_id" not in sql.split("USING")[0]


@pytest.mark.parametrize("bad", ["C1' OR '1'='1", "", "a b", "x" * 65])
def test_request_rejects_unsafe_ids(spec, bad):
    with pytest.raises(ValueError):
        render_request(spec, "dev", "DSR-0001", bad)


def test_delete_matches_hashed_key_against_the_register(spec):
    assert render_delete(spec, "dev", GOLD) == (
        f"DELETE FROM {GOLD} WHERE sha2(CAST(`customer_id` AS STRING), 256) "
        "IN (SELECT subject_hash FROM gov_dev.governance.erasure_requests)")


def test_clean_erasure_passes(spec):
    report = check_erasure(spec, "dev", fake_query(requests=2, edges=[(RAW_C, SILVER_C), (SILVER_C, GOLD)]))
    assert (report.requests, report.residual, report.gaps) == (2, {}, [])
    assert report_erasure(report, log=lambda _: None) == 0


def test_residual_rows_fail(spec):
    report = check_erasure(spec, "dev", fake_query(requests=1, residual={RAW_C: 2}))
    assert report.residual == {RAW_C: 2}
    assert report_erasure(report, log=lambda _: None) == 1


def test_table_fed_by_subject_data_without_the_key_is_a_gap(spec):
    """A gold table that aggregates customers but dropped customer_id can't be erased by key."""
    report = check_erasure(spec, "dev", fake_query(edges=[(SILVER_C, "gov_dev.customer_gold.segments"),
                                                          (SILVER_C, "gov_dev.audit.scorecard")]))
    assert report.gaps == [(SILVER_C, "gov_dev.customer_gold.segments")]
    assert "erasure can't reach it" in report.findings()[0]


def test_register_is_created_by_apply_and_never_overwritten(spec):
    sql = [s.sql for s in render_plan(spec, "prod") if "erasure_requests" in s.sql]
    assert len(sql) == 1 and sql[0].startswith("CREATE TABLE IF NOT EXISTS gov_prod.governance.erasure_requests")


def test_contract_with_pii_must_carry_the_subject_key(spec_copy):
    def drop_key(d):
        d["schema"][0]["properties"] = [p for p in d["schema"][0]["properties"] if p["name"] != "customer_id"]
        d["quality"] = [q for q in d["quality"] if q["column"] != "customer_id"]
    _edit(spec_copy, "contracts/sales.orders.yml", drop_key)
    assert "has no 'customer_id' column, so it can't be erased" in _errors(spec_copy)


def test_erasure_job_runs_as_owner_and_engineers_can_only_start_it(spec):
    job = yaml.safe_load((ROOT / "resources" / "right_to_erasure.job.yml").read_text())["resources"]["jobs"]
    job = job["right_to_erasure"]
    assert [t["task_key"] for t in job["tasks"]] == ["erase", "verify"]
    assert "--verify" in job["tasks"][1]["spark_python_task"]["parameters"]
    assert "run_as" not in job
    assert job["permissions"] == [{"group_name": spec.group("data_engineers"), "level": "CAN_MANAGE_RUN"}]
