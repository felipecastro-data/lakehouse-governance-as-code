"""Databricks job entrypoint: measure governance coverage and record it in <catalog>.audit (docs/adr/0009).

Runs as the deployer after the checks, even when they fail, so a bad run is on the scorecard too.
Appends to audit.scorecard and audit.findings, and replaces audit.table_inventory.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--root", required=True, help="bundle file path containing governance/ and src/")
    parser.add_argument("--run-id", required=True, help="the pipeline's job run id")
    args = parser.parse_args()

    root = Path(args.root)
    sys.path.insert(0, str(root / "src"))

    from pyspark.sql import SparkSession

    from gov_engine.scorecard import TABLES, build_scorecard
    from gov_engine.spec import load_spec

    spark = SparkSession.builder.getOrCreate()
    spec = load_spec(root)
    catalog = spec.catalog(args.env)

    def query(sql: str) -> list[dict]:
        return [row.asDict(recursive=True) for row in spark.sql(sql).collect()]

    card = build_scorecard(spec, args.env, query)
    run = {"run_id": args.run_id, "run_time": datetime.now(timezone.utc)}
    rows = {
        "scorecard": [{**run, "metric": m.name, "value": m.value, "numerator": m.numerator,
                       "denominator": m.denominator, "description": m.description} for m in card.metrics],
        "findings": [{**run, **f} for f in card.finding_rows()],
        "table_inventory": card.inventory,
    }
    for name, (columns, comment) in TABLES.items():
        table = f"{catalog}.audit.{name}"
        spark.sql(f"CREATE TABLE IF NOT EXISTS {table} ({columns}) COMMENT '{comment}'")
        df = spark.createDataFrame([tuple(r.get(c.split()[0]) for c in columns.split(", ")) for r in rows[name]],
                                   schema=columns)
        df.write.insertInto(table, overwrite=name == "table_inventory")
        print(f"[ok] {table}: {len(rows[name])} rows")
    for m in card.metrics:
        print(m)


if __name__ == "__main__":
    main()
