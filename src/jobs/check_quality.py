"""Databricks job entrypoint: run the quality rules declared in the data contracts.

Fails the run if any rule has violating rows, so bad data never reaches consumers unnoticed.
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

    from gov_engine.quality import render_checks
    from gov_engine.spec import load_spec

    spark = SparkSession.builder.getOrCreate()
    failed = 0
    for check in render_checks(load_spec(root), args.env):
        violations = spark.sql(check.sql).collect()[0][0]
        print(f"[{'ok' if violations == 0 else 'FAILED'}] {check.name}: {violations} violating rows")
        failed += violations > 0
    if failed:
        sys.exit(f"{failed} quality rule(s) failed")


if __name__ == "__main__":
    main()
