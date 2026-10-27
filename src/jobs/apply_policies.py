"""Databricks job entrypoint: apply the governance spec to one environment.

1. Create missing account groups (policies fail on unknown principals).
2. Sync governed tags (tag policies) through the REST API.
3. Run the SQL plan: mapping tables, functions, grants, tags, ABAC policies.
"""

import argparse
import sys
import time
from pathlib import Path

TAG_POLICY_PROPAGATION_SECONDS = 90


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
    from gov_engine.databricks_api import sdk_api
    from gov_engine.identity import sync_groups
    from gov_engine.render import render_plan
    from gov_engine.spec import load_spec
    from gov_engine.tag_policies import sync_tag_policies

    spark = SparkSession.builder.getOrCreate()
    api = sdk_api()
    spec = load_spec(root)

    sync_groups(spec, api, dry_run=args.dry_run)
    if sync_tag_policies(spec, api, dry_run=args.dry_run) and not args.dry_run:
        print(f"New tag policies created; waiting {TAG_POLICY_PROPAGATION_SECONDS}s for them to propagate")
        time.sleep(TAG_POLICY_PROPAGATION_SECONDS)

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
