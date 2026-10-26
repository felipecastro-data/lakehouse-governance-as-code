"""Command line: validate the spec, preview SQL, print the access matrix."""

from __future__ import annotations

import argparse
import sys

from gov_engine.render import PHASES, render_access_matrix, render_bootstrap, render_plan
from gov_engine.spec import SpecError, load_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gov_engine", description=__doc__)
    parser.add_argument("--root", default=".", help="repository root containing governance/")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="validate governance/*.yml")

    plan = sub.add_parser("plan", help="print the SQL that apply would run")
    plan.add_argument("--env", required=True)
    plan.add_argument("--phase", action="append", choices=PHASES, help="limit to phase (repeatable)")

    boot = sub.add_parser("bootstrap", help="print one-time setup SQL (catalog)")
    boot.add_argument("--env", required=True)

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
    elif args.command == "bootstrap":
        for stmt in render_bootstrap(spec, args.env):
            print(stmt.sql + ";")
    elif args.command == "principals":
        print("\n".join(spec.access.principals.values()))
    elif args.command == "matrix":
        print(render_access_matrix(spec, args.env))
    return 0
