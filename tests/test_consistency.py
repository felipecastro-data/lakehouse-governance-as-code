"""The bundle and the governance spec must describe the same layout."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_bundle_schemas_match_layout(spec):
    bundle = yaml.safe_load((ROOT / "resources" / "schemas.yml").read_text())
    schemas = bundle["resources"]["schemas"]
    assert {s["name"] for s in schemas.values()} == set(spec.layout.all_schemas())
    assert all(s["catalog_name"] == "${var.catalog}" for s in schemas.values())
    assert all("grants" not in s for s in schemas.values()), "grants belong to gov_engine (ADR-0002)"


def test_bundle_does_not_manage_the_catalog():
    """Default Storage rejects the catalogs API; gov_engine ensure-catalog creates it with SQL."""
    for path in (ROOT / "resources").glob("*.yml"):
        assert "catalogs" not in (yaml.safe_load(path.read_text()).get("resources") or {}), path.name


def test_bundle_targets_match_environments(spec):
    bundle = yaml.safe_load((ROOT / "databricks.yml").read_text())
    targets = {name: cfg["variables"]["catalog"] for name, cfg in bundle["targets"].items()}
    assert targets == spec.layout.environments


def test_generated_docs_are_current(spec):
    """Regenerate with: make docs"""
    from gov_engine.render import render_access_matrix

    committed = (ROOT / "docs" / "generated" / "access-matrix-prod.md").read_text().strip()
    assert committed == render_access_matrix(spec, "prod").strip()
