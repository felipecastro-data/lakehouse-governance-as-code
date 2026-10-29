"""Databricks job entrypoint: flag curated columns fed by PII (column lineage) that carry no pii_type tag.

Reads lineage from <catalog>.audit.column_lineage, a view an account admin owns (docs/adr/0008).
System tables lag, so lineage from this run's writes is usually checked on the next run.
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

    from gov_engine.cli import report_propagation
    from gov_engine.lineage import find_untagged_pii
    from gov_engine.spec import load_spec

    spark = SparkSession.builder.getOrCreate()
    spec = load_spec(root)

    def query(sql: str) -> list[dict]:
        return [row.asDict(recursive=True) for row in spark.sql(sql).collect()]

    sys.exit(report_propagation(find_untagged_pii(spec, args.env, query)))


if __name__ == "__main__":
    main()
