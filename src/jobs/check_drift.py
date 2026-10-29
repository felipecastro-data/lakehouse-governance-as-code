"""Databricks job entrypoint: compare declared governance state with the catalog; fail on critical drift.

Runs as the deployer, which owns the catalog and so sees every grant and policy in information_schema.
"""

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--root", required=True, help="bundle file path containing governance/ and src/")
    args = parser.parse_args()

    root = Path(args.root)
    sys.path.insert(0, str(root / "src"))

    from pyspark.sql import SparkSession

    from gov_engine.cli import report_drift
    from gov_engine.drift import detect_drift
    from gov_engine.spec import load_spec

    spark = SparkSession.builder.getOrCreate()
    spec = load_spec(root)

    def query(sql: str) -> list[dict]:
        return [row.asDict(recursive=True) for row in spark.sql(sql).collect()]

    sys.exit(report_drift(detect_drift(spec, args.env, query)))


if __name__ == "__main__":
    main()
