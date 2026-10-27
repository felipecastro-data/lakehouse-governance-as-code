"""Command line: validate the spec, preview SQL, print the access matrix."""

from __future__ import annotations

import argparse
import json
import sys

from gov_engine.databricks_api import cli_api
from gov_engine.identity import sync_groups
from gov_engine.render import PHASES, render_access_matrix, render_plan
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
    elif args.command == "principals":
        print("\n".join(spec.access.principals.values()))
    elif args.command == "matrix":
        print(render_access_matrix(spec, args.env))
    return 0
