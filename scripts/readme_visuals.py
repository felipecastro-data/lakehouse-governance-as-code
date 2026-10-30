"""Render the README charts in docs/images/ as static SVG (light and dark via prefers-color-scheme).

    PYTHONPATH=src .venv/bin/python scripts/readme_visuals.py [--env dev]

The access matrix and classification charts come from governance/*.yml; the scorecard tiles are
the latest run the pipeline recorded in <catalog>.audit.scorecard (read through the Databricks CLI login).
Every chart has the same numbers as a table in the README, so nothing depends on color alone.
"""

from __future__ import annotations

import argparse
from html import escape
from pathlib import Path

from gov_engine.render import expand_grants
from gov_engine.spec import Spec, load_spec

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'

# Reference palette (dataviz skill): surfaces, ink, the blue ramp for ordinal steps, status "good".
STYLE = """
  .surface { fill: #fcfcfb; } .card { fill: #ffffff; stroke: rgba(11,11,11,0.10); }
  .ink { fill: #0b0b0b; } .ink2 { fill: #52514e; } .muted { fill: #898781; }
  .grid { stroke: #e1e0d9; } .none { fill: #f0efec; }
  .s1 { fill: #86b6ef; } .s2 { fill: #3987e5; } .s3 { fill: #1c5cab; } .s4 { fill: #0d366b; }
  .on-light { fill: #0b0b0b; } .on-dark { fill: #ffffff; } .good { fill: #0ca30c; } .good-text { fill: #006300; }
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; } .card { fill: #222221; stroke: rgba(255,255,255,0.10); }
    .ink { fill: #f0efec; } .ink2 { fill: #c3c2b7; } .grid { stroke: #2c2c2a; } .none { fill: #2c2c2a; }
    .s1 { fill: #184f95; } .s2 { fill: #256abf; } .s3 { fill: #3987e5; } .s4 { fill: #86b6ef; }
    .on-light { fill: #ffffff; } .good-text { fill: #0ca30c; }
    text.on-s4 { fill: #0b0b0b; }
  }
"""


def svg(width: int, height: int, title: str, body: list[str]) -> str:
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="{escape(title)}" font-family=\'{FONT}\'>',
        f"<title>{escape(title)}</title><style>{STYLE}</style>",
        f'<rect class="surface" width="{width}" height="{height}" rx="12"/>',
        *body,
        "</svg>",
    ])


def text(x: float, y: float, s: str, cls: str = "ink", size: int = 13, anchor: str = "start", weight: int = 400) -> str:
    return (f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{escape(s)}</text>')


# --------------------------------------------------------------------------- access matrix

LEVELS = [  # (label, css class for the cell, css class for its text)
    ("—", "none", "muted"), ("read", "s1", "on-light"), ("read + tag", "s2", "on-dark"),
    ("read + write", "s3", "on-dark"), ("all (admin)", "s4", "on-dark on-s4"),
]


def access_level(privs: set[str]) -> int:
    if "MODIFY" in privs and "CREATE_FUNCTION" in privs:
        return 4
    if "MODIFY" in privs:
        return 3
    if "APPLY_TAG" in privs:
        return 2
    if "SELECT" in privs:
        return 1
    return 0


def access_matrix(spec: Spec, env: str) -> str:
    grants = expand_grants(spec, env)
    layers = spec.layout.layers
    schemas = [*(s for s, _, _ in sorted(spec.layout.domain_schemas(), key=lambda t: (layers.index(t[2]), t[1]))),
               "audit"]
    catalog = spec.catalog(env)
    principals = [p for p in spec.access.principals if p != "pipelines"]
    cell_w, cell_h, left, top = 92, 30, 190, 92
    width, height = left + cell_w * len(schemas) + 24, top + cell_h * len(principals) + 74
    body = [text(24, 34, f"Who can do what in {catalog}", size=17, weight=600),
            text(24, 56, "Schema privileges rendered from access_policy.yml. Masks and row filters apply on top.",
                 "ink2", 12)]
    for j, s in enumerate(schemas):
        x = left + j * cell_w + cell_w / 2
        domain, _, layer = s.rpartition("_")
        body.append(text(x, top - 22, domain or s, "ink2", 11, "middle"))
        body.append(text(x, top - 8, layer if domain else "", "muted", 11, "middle"))
    for i, p in enumerate(principals):
        y = top + i * cell_h
        body.append(text(left - 12, y + cell_h / 2 + 4, spec.group(p), "ink", 12, "end"))
        catalog_privs = set(grants.get((f"CATALOG {catalog}", p), []))
        for j, s in enumerate(schemas):
            privs = set(grants.get((f"SCHEMA {catalog}.{s}", p), [])) | (catalog_privs - {"USE_CATALOG"})
            label, fill, ink = LEVELS[access_level(privs)]
            x = left + j * cell_w
            body.append(f'<rect class="{fill}" x="{x + 1}" y="{y + 1}" '
                        f'width="{cell_w - 2}" height="{cell_h - 2}" rx="4"/>')
            body.append(text(x + cell_w / 2, y + cell_h / 2 + 4, label, ink, 11, "middle"))
    ly = top + cell_h * len(principals) + 34
    x = left
    for label, fill, _ in LEVELS[1:]:
        body.append(f'<rect class="{fill}" x="{x}" y="{ly - 11}" width="14" height="14" rx="3"/>')
        body.append(text(x + 20, ly, label, "ink2", 12))
        x += 30 + 7 * len(label)
    return svg(width, height, f"Access matrix for {catalog}", body)


# --------------------------------------------------------------------------- classification

def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def classification(spec: Spec) -> str:
    levels = [lvl.name for lvl in spec.classification.levels if any(
        spec.column_classification(c) == lvl.name for t in spec.tables for c in t.columns)]
    fills = {name: f for name, f in zip(levels, ("s1", "s2", "s4"), strict=False)}
    inks = {"s1": "on-light", "s2": "on-dark", "s4": "on-dark on-s4"}
    left, top, bar_h, gap, unit = 230, 78, 30, 16, 52
    width = left + unit * max(len(t.columns) for t in spec.tables) + 110
    height = top + (bar_h + gap) * len(spec.tables) + 50
    body = [text(24, 34, "Every column classified, every PII column typed", size=17, weight=600),
            text(24, 56, "Columns per data contract by classification level (from the ODCS contracts).", "ink2", 12)]
    for i, t in enumerate(spec.tables):
        y = top + i * (bar_h + gap)
        body.append(text(left - 12, y + bar_h / 2 - 2, f"{t.schema}.{t.name}", "ink", 12, "end"))
        body.append(text(left - 12, y + bar_h / 2 + 13, _plural(sum(bool(c.pii_type) for c in t.columns), "PII column"),
                         "muted", 11, "end"))
        x = left
        for lvl in levels:
            n = sum(spec.column_classification(c) == lvl for c in t.columns)
            if not n:
                continue
            w = n * unit
            body.append(f'<rect class="{fills[lvl]}" x="{x}" y="{y}" width="{w - 2}" height="{bar_h}" rx="4"/>')
            body.append(text(x + (w - 2) / 2, y + bar_h / 2 + 4, str(n), inks[fills[lvl]], 12, "middle", 600))
            x += w
        body.append(text(x + 6, y + bar_h / 2 + 4, f"{len(t.columns)} columns", "ink2", 12))
    ly, x = height - 22, left
    for lvl in levels:
        body.append(f'<rect class="{fills[lvl]}" x="{x}" y="{ly - 11}" width="14" height="14" rx="3"/>')
        body.append(text(x + 20, ly, lvl, "ink2", 12))
        x += 40 + 7 * len(lvl)
    return svg(width, height, "Columns by classification level per data contract", body)


# --------------------------------------------------------------------------- scorecard tiles

def scorecard_tiles(metrics: dict[str, float], env: str) -> str:
    tiles = [
        ("pct_owned", "Tables owned", "%"), ("pct_classified", "Columns classified", "%"),
        ("pct_pii_masked", "PII columns masked", "%"), ("drift_critical", "Critical drift", ""),
        ("untagged_pii", "Untagged PII (lineage)", ""), ("erasure_residual", "Erasure residual rows", ""),
    ]
    w, h, gap, left, top = 168, 112, 12, 24, 64
    width = left * 2 + w * len(tiles) + gap * (len(tiles) - 1)
    body = [text(24, 36, f"Governance scorecard · {env}, latest pipeline run", size=17, weight=600)]
    for i, (key, label, unit) in enumerate(tiles):
        x = left + i * (w + gap)
        value = metrics.get(key)
        target_met = value == (100 if unit else 0)
        shown = "n/a" if value is None else f"{value:g}{unit}"
        body.append(f'<rect class="card" x="{x}" y="{top}" width="{w}" height="{h}" rx="10"/>')
        body.append(text(x + 16, top + 26, label, "ink2", 12))
        body.append(text(x + 16, top + 66, shown, "ink", 34, weight=600))
        if target_met:
            body.append(f'<circle class="good" cx="{x + 22}" cy="{top + 90}" r="6"/>')
            body.append(f'<path d="M{x + 19} {top + 90} l2 2 l4 -4" stroke="#fff" stroke-width="1.6" fill="none"/>')
            body.append(text(x + 34, top + 94, "target met", "good-text", 11))
    return svg(width, top + h + 24, f"Governance scorecard for {env}", body)


def live_metrics(spec: Spec, env: str) -> dict[str, float]:
    """The latest run recorded by the pipeline's scorecard task, which measures as the catalog owner."""
    from gov_engine.databricks_api import cli_api, pick_warehouse, query_rows

    api = cli_api()
    table = f"{spec.catalog(env)}.audit.scorecard"
    rows = query_rows(api, pick_warehouse(api), f"SELECT metric, value FROM {table} "
                      f"WHERE run_time = (SELECT max(run_time) FROM {table})")
    return {r["metric"]: float(r["value"]) for r in rows if r["value"] is not None}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="dev")
    args = parser.parse_args()
    spec = load_spec(ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "access-matrix.svg").write_text(access_matrix(spec, "prod"))
    (OUT / "classification.svg").write_text(classification(spec))
    metrics = live_metrics(spec, args.env)
    (OUT / "scorecard.svg").write_text(scorecard_tiles(metrics, args.env))
    for name in ("access-matrix", "classification", "scorecard"):
        print(f"[ok] docs/images/{name}.svg")
    print(metrics)


if __name__ == "__main__":
    main()
