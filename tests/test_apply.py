from gov_engine.apply import apply_statements
from gov_engine.render import Statement


def test_skips_missing_tables_and_continues_after_failures():
    stmts = [
        Statement("functions", "CREATE FUNCTION ok"),
        Statement("tags", "ALTER TABLE missing", target="c.s.missing"),
        Statement("grants", "GRANT boom"),
        Statement("tags", "ALTER TABLE present", target="c.s.present"),
    ]
    ran = []

    def run_sql(sql):
        if "boom" in sql:
            raise RuntimeError("permission denied")
        ran.append(sql)

    result = apply_statements(stmts, run_sql, table_exists=lambda t: t == "c.s.present", log=lambda _: None)
    assert ran == ["CREATE FUNCTION ok", "ALTER TABLE present"]
    assert [s.target for s in result.skipped] == ["c.s.missing"]
    assert len(result.failed) == 1 and not result.ok


def test_dry_run_executes_nothing():
    result = apply_statements([Statement("grants", "GRANT x")], run_sql=lambda _: 1 / 0,
                              table_exists=lambda _: True, dry_run=True, log=lambda _: None)
    assert result.ok and len(result.applied) == 1
