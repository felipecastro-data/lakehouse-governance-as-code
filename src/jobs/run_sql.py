"""Databricks job entrypoint: run a SQL transform file against one catalog.

`{{catalog}}` in the file is replaced with --catalog. Statements are separated by `;` at line end.
"""

import argparse
from pathlib import Path


def statements(text: str, catalog: str) -> list[str]:
    body = "\n".join(line for line in text.replace("{{catalog}}", catalog).splitlines()
                     if not line.lstrip().startswith("--"))
    parts = (s.strip().rstrip(";").strip() for s in body.split(";\n"))
    return [s for s in parts if s]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--file", required=True)
    args = parser.parse_args()

    from pyspark.sql import SparkSession

    spark = SparkSession.builder.getOrCreate()
    for sql in statements(Path(args.file).read_text(), args.catalog):
        spark.sql(sql)
        print(f"[ok] {sql.splitlines()[0]}")


if __name__ == "__main__":
    main()
