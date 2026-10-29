"""Command line: validate the spec, preview SQL, print the access matrix, check drift and PII lineage,
measure the scorecard and create the audit views."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gov_engine.audit import create_audit_views
from gov_engine.catalog import ensure_catalog
from gov_engine.databricks_api import cli_api, pick_warehouse, query_rows
from gov_engine.drift import detect_drift
from gov_engine.identity import sync_groups
from gov_engine.lineage import find_untagged_pii
from gov_engine.render import PHASES, render_access_matrix, render_plan
from gov_engine.scorecard import build_scorecard
from gov_engine.spec import SpecError, load_spec
from gov_engine.tag_policies import desired_tag_policies, sync_tag_policies


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gov_engine", description=__doc__)
    parser.add_argument("--root", default=".", help="repository root containing governance/")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="validate governance/*.yml")

    plan = sub.add_parser("plan", help="print the SQL that apply would run")
    plan.add_argument("--env", required=True)
    plan.add_argument("--phase", action="append", choices=PHASES, help="limit to phase (repeatable)")

    sub.add_parser("tag-policies", help="print the governed tags (tag policies) as JSON")

    for name, help_text in (("sync-groups", "create missing account groups"),
                            ("sync-tags", "create/update governed tags")):
        cmd = sub.add_parser(name, help=f"{help_text} (uses the Databricks CLI login)")
        cmd.add_argument("--dry-run", action="store_true")
        cmd.add_argument("--profile", help="Databricks CLI profile")

    catalog = sub.add_parser("ensure-catalog", help="create the env catalog via SQL (run before bundle deploy)")
    catalog.add_argument("--env", required=True)
    catalog.add_argument("--warehouse-id", help="default: first serverless SQL warehouse")
    catalog.add_argument("--dry-run", action="store_true")
    catalog.add_argument("--profile", help="Databricks CLI profile")

    for name, help_text in (("drift", "compare declared and actual state; exit 1 on critical drift"),
                            ("pii-propagation", "flag untagged columns fed by PII (column lineage); exit 1 if any"),
                            ("scorecard", "print the governance scorecard (no write; the pipeline records it)")):
        cmd = sub.add_parser(name, help=f"{help_text}. Run as the catalog owner to see every grant and policy")
        cmd.add_argument("--env", required=True)
        cmd.add_argument("--warehouse-id", help="default: first serverless SQL warehouse")
        cmd.add_argument("--profile", help="Databricks CLI profile")

    audit = sub.add_parser("audit-views", help="create the audit views over system tables. Run as an account admin")
    audit.add_argument("--env", required=True)
    audit.add_argument("--warehouse-id", help="default: first serverless SQL warehouse")
    audit.add_argument("--dry-run", action="store_true")
    audit.add_argument("--profile", help="Databricks CLI profile")

    sub.add_parser("principals", help="print group names, one per line")

    matrix = sub.add_parser("matrix", help="print the access matrix as Markdown")
    matrix.add_argument("--env", required=True)

    args = parser.parse_args(argv)
    try:
        spec = load_spec(args.root)
    except SpecError as exc:
        print(exc, file=sys.stderr)
        return 1

    if args.command == "validate":
        print(f"OK: {len(spec.tables)} tables, {len(spec.access.grants)} grant rules, "
              f"{len(spec.layout.environments)} environments")
    elif args.command == "plan":
        current = None
        for stmt in render_plan(spec, args.env, tuple(args.phase or PHASES)):
            if stmt.phase != current:
                current = stmt.phase
                print(f"\n-- ===== {current} =====")
            print(stmt.sql + ";")
    elif args.command == "tag-policies":
        print(json.dumps(desired_tag_policies(spec), indent=2))
    elif args.command == "sync-groups":
        sync_groups(spec, cli_api(args.profile), dry_run=args.dry_run)
    elif args.command == "sync-tags":
        sync_tag_policies(spec, cli_api(args.profile), dry_run=args.dry_run)
    elif args.command == "ensure-catalog":
        ensure_catalog(spec, args.env, cli_api(args.profile), args.warehouse_id, dry_run=args.dry_run)
    elif args.command == "audit-views":
        api = cli_api(args.profile)
        create_audit_views(spec, args.env, Path(args.root), api, args.warehouse_id or pick_warehouse(api),
                           dry_run=args.dry_run)
    elif args.command in ("drift", "pii-propagation", "scorecard"):
        api = cli_api(args.profile)
        warehouse = args.warehouse_id or pick_warehouse(api)

        def query(sql: str) -> list[dict]:
            return query_rows(api, warehouse, sql)

        if args.command == "drift":
            return report_drift(detect_drift(spec, args.env, query))
        if args.command == "scorecard":
            print("\n".join(map(str, build_scorecard(spec, args.env, query).metrics)))
            return 0
        return report_propagation(find_untagged_pii(spec, args.env, query))
    elif args.command == "principals":
        print("\n".join(spec.access.principals.values()))
    elif args.command == "matrix":
        print(render_access_matrix(spec, args.env))
    return 0


def report_drift(findings: list, log=print) -> int:
    """Print findings; 1 if any is critical. Shared by the CLI and the pipeline task."""
    for f in findings:
        log(str(f))
    critical = sum(f.severity == "critical" for f in findings)
    log(f"drift: {critical} critical, {len(findings) - critical} warning")
    return 1 if critical else 0


def report_propagation(report, log=print) -> int:
    """Print the PII propagation report; 1 if any untagged column is fed by PII."""
    for column, pii_type in report.inferred_raw_pii.items():
        log(f"[info] raw PII by lineage: {column} -> {pii_type}")
    for f in report.findings:
        log(str(f))
    log(f"pii propagation: {report.edges} lineage edges, {len(report.inferred_raw_pii)} raw PII columns inferred, "
        f"{len(report.findings)} untagged PII columns")
    return 1 if report.findings else 0
