"""Synthetic data generator, SQL runner, and pipeline <-> contract consistency."""

import random
import re
from pathlib import Path

import yaml

from jobs.generate_bronze import CUSTOMER_COLUMNS, ORDER_COLUMNS, generate_customers, generate_orders
from jobs.run_sql import statements

ROOT = Path(__file__).resolve().parents[1]


def _data(seed=7):
    rng = random.Random(seed)
    customers = generate_customers(2_000, rng)
    return customers, generate_orders(10_000, customers, rng)


def test_generator_is_deterministic_and_shaped():
    customers, orders = _data()
    assert (customers, orders) == _data()
    assert all(len(r) == len(CUSTOMER_COLUMNS) for r in customers)
    assert all(len(r) == len(ORDER_COLUMNS) for r in orders)


def test_raw_data_has_the_mess_silver_cleans():
    customers, orders = _data()
    ids = [c[0] for c in customers]
    assert len(ids) > len(set(ids)), "duplicate customer records"
    assert any(c[3] != c[3].strip().lower() for c in customers), "untrimmed / mixed-case emails"
    assert any(c[9] == "XX" for c in customers), "unknown country"
    assert any(o[1] not in set(ids) for o in orders), "orphan orders"
    assert any(o[6] == "test" for o in orders), "test orders"
    assert any(" " in o[5] for o in orders), "formatted card numbers"


def test_pii_is_fake_by_construction():
    customers, _ = _data()
    assert all(re.fullmatch(r"900-\d{2}-\d{4}", c[6]) for c in customers), "900 area is never issued"
    assert all(c[3].strip().lower().endswith("@example.com") for c in customers)


def test_run_sql_templates_catalog_and_splits_statements():
    sql = "-- comment\nINSERT INTO {{catalog}}.a.b SELECT 1;\nSELECT ';' FROM {{catalog}}.a.c;\n"
    assert statements(sql, "gov_dev") == ["INSERT INTO gov_dev.a.b SELECT 1", "SELECT ';' FROM gov_dev.a.c"]


def test_every_contract_table_has_a_transform_and_a_job_task(spec):
    job = yaml.safe_load((ROOT / "resources" / "lakehouse_pipeline.job.yml").read_text())
    params = " ".join(" ".join(t.get("spark_python_task", {}).get("parameters", []))
                      for t in job["resources"]["jobs"]["lakehouse_pipeline"]["tasks"])
    for t in spec.tables:
        path = ROOT / "src" / "transforms" / t.schema / f"{t.name}.sql"
        assert path.exists(), f"missing transform for contract {t.contract_id}"
        assert f"INSERT OVERWRITE {{{{catalog}}}}.{t.schema}.{t.name}\n" in path.read_text()
        assert f"/src/transforms/{t.schema}/{t.name}.sql" in params, f"no job task runs {path.name}"


def test_pipeline_applies_governance_before_writing_data():
    tasks = yaml.safe_load((ROOT / "resources" / "lakehouse_pipeline.job.yml").read_text())
    tasks = tasks["resources"]["jobs"]["lakehouse_pipeline"]["tasks"]
    assert tasks[0]["task_key"] == "governance" and "run_job_task" in tasks[0]
    assert tasks[1]["depends_on"] == [{"task_key": "governance"}]


def test_pipeline_ends_with_drift_and_pii_propagation_checks():
    tasks = yaml.safe_load((ROOT / "resources" / "lakehouse_pipeline.job.yml").read_text())
    tasks = {t["task_key"]: t for t in tasks["resources"]["jobs"]["lakehouse_pipeline"]["tasks"]}
    for key, script in (("drift", "check_drift.py"), ("pii_propagation", "check_pii_propagation.py")):
        assert tasks[key]["depends_on"] == [{"task_key": "quality"}]
        assert tasks[key]["spark_python_task"]["python_file"] == f"../src/jobs/{script}"
        assert (ROOT / "src" / "jobs" / script).exists()


def test_scorecard_runs_after_the_checks_even_when_they_fail():
    tasks = yaml.safe_load((ROOT / "resources" / "lakehouse_pipeline.job.yml").read_text())
    tasks = {t["task_key"]: t for t in tasks["resources"]["jobs"]["lakehouse_pipeline"]["tasks"]}
    scorecard = tasks["scorecard"]
    assert scorecard["depends_on"] == [{"task_key": "drift"}, {"task_key": "pii_propagation"}]
    assert scorecard["run_if"] == "ALL_DONE"
    assert scorecard["spark_python_task"]["python_file"] == "../src/jobs/build_scorecard.py"
    assert "{{job.run_id}}" in scorecard["spark_python_task"]["parameters"]
