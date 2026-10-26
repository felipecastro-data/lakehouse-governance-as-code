"""Databricks job entrypoint: apply the governance spec to one environment."""

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--root", required=True, help="bundle file path containing governance/ and src/")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root)
    sys.path.insert(0, str(root / "src"))

    from pyspark.sql import SparkSession

    from gov_engine.apply import apply_statements
    from gov_engine.render import render_plan
    from gov_engine.spec import load_spec

    spark = SparkSession.builder.getOrCreate()
    spec = load_spec(root)
    result = apply_statements(
        render_plan(spec, args.env),
        run_sql=spark.sql,
        table_exists=spark.catalog.tableExists,
        dry_run=args.dry_run,
    )
    if not result.ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
