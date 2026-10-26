"""Drift detection: declared state (spec) vs actual state (information_schema). Phase 3.

Planned checks:
- grants:   `system.information_schema.catalog_privileges` / `schema_privileges` vs `expand_grants()`;
            undeclared grants and grants to individual users are findings.
- tags:     `table_tags` / `column_tags` vs contract-derived tags.
- masks:    `column_masks` vs contract `piiType` columns; any PII column without a mask is critical.
- filters:  `row_filters` vs contract `rowFilter`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gov_engine.spec import Spec


@dataclass(frozen=True)
class DriftFinding:
    severity: str  # critical | warning
    kind: str  # grant | tag | mask | row_filter
    securable: str
    detail: str


def detect_drift(spec: Spec, env: str, query: Callable[[str], list[dict]]) -> list[DriftFinding]:
    raise NotImplementedError("Phase 3: drift detection")
