"""Databricks job entrypoint: right to erasure (FR12, docs/adr/0010).

Three modes, all as the deployer:
- `--request-id R --subject-id S`: register the request, delete the subject from every table in scope,
  purge the rewritten files, and log the deleted rows to audit.erasure_log (the right_to_erasure job).
- no request: re-apply the whole register (the pipeline, right after ingestion re-delivers bronze).
- `--verify`: fail if a registered subject is still present or a table fed by one has no subject key.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", required=True)
    parser.add_argument("--root", required=True, help="bundle file path containing governance/ and src/")
    parser.add_argument("--run-id", default="", help="the job run id, for the erasure log")
    parser.add_argument("--request-id")
    parser.add_argument("--subject-id")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if bool(args.request_id) != bool(args.subject_id):
        sys.exit("--request-id and --subject-id go together")

    root = Path(args.root)
    sys.path.insert(0, str(root / "src"))

    from pyspark.sql import SparkSession

    from gov_engine.erasure import (
        LOG_TABLE,
        check_erasure,
        render_delete,
        render_purge,
        render_request,
        report_erasure,
        scope,
    )
    from gov_engine.spec import load_spec

    spark = SparkSession.builder.getOrCreate()
    spec = load_spec(root)

    def query(sql: str) -> list[dict]:
        return [row.asDict(recursive=True) for row in spark.sql(sql).collect()]

    if args.verify:
        if report_erasure(check_erasure(spec, args.env, query)):
            sys.exit(1)  # sys.exit(0) also fails a serverless task, so exit only on failure
        return

    if args.request_id:
        spark.sql(render_request(spec, args.env, args.request_id, args.subject_id))
        print(f"[ok] registered {args.request_id}")

    deleted = {}
    for table in scope(spec, args.env, query):
        rows = spark.sql(render_delete(spec, args.env, table)).collect()
        deleted[table] = int(rows[0]["num_affected_rows"]) if rows else 0
        if deleted[table] and args.request_id:
            spark.sql(render_purge(table))
        print(f"[ok] {table}: {deleted[table]} rows deleted")

    name, columns, comment = LOG_TABLE
    log = f"{spec.catalog(args.env)}.audit.{name}"
    spark.sql(f"CREATE TABLE IF NOT EXISTS {log} ({columns}) COMMENT '{comment}'")
    now = datetime.now(timezone.utc)
    rows = [(args.run_id, now, args.request_id, t, n) for t, n in deleted.items() if n or args.request_id]
    if rows:
        spark.createDataFrame(rows, schema=columns).write.insertInto(log)
    print(f"erasure: {sum(deleted.values())} rows deleted from {len(deleted)} tables")


if __name__ == "__main__":
    main()
