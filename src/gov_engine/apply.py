"""Execute rendered statements. Decoupled from Spark so it can be tested with fakes."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from gov_engine.render import Statement


@dataclass
class ApplyResult:
    applied: list[Statement] = field(default_factory=list)
    skipped: list[Statement] = field(default_factory=list)  # target table does not exist yet
    failed: list[tuple[Statement, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def apply_statements(
    statements: Iterable[Statement],
    run_sql: Callable[[str], object],
    table_exists: Callable[[str], bool],
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> ApplyResult:
    """Run statements in order; keep going after failures so one bad table doesn't block the rest."""
    result = ApplyResult()
    exists_cache: dict[str, bool] = {}
    for stmt in statements:
        if stmt.target:
            if stmt.target not in exists_cache:
                exists_cache[stmt.target] = table_exists(stmt.target)
            if not exists_cache[stmt.target]:
                result.skipped.append(stmt)
                continue
        first_line = stmt.sql.splitlines()[0]
        if dry_run:
            log(f"[dry-run] [{stmt.phase}] {first_line}")
            result.applied.append(stmt)
            continue
        try:
            run_sql(stmt.sql)
            log(f"[ok] [{stmt.phase}] {first_line}")
            result.applied.append(stmt)
        except Exception as exc:  # noqa: BLE001 - report every failure at the end
            log(f"[failed] [{stmt.phase}] {first_line}: {exc}")
            result.failed.append((stmt, str(exc)))

    missing = sorted({s.target for s in result.skipped if s.target})
    log(f"applied={len(result.applied)} skipped={len(result.skipped)} failed={len(result.failed)}")
    if missing:
        log("skipped (table not created yet): " + ", ".join(missing))
    return result
