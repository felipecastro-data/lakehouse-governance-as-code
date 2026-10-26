"""PII propagation check using column lineage. Phase 3.

Planned check: walk `system.access.column_lineage` from every column tagged `pii_type` and flag
downstream columns in governed catalogs that carry no `pii_type` tag (PII leaking into an
unclassified column).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from gov_engine.spec import Spec


@dataclass(frozen=True)
class PropagationFinding:
    source_column: str
    target_column: str
    pii_type: str


def find_untagged_pii(spec: Spec, env: str, query: Callable[[str], list[dict]]) -> list[PropagationFinding]:
    raise NotImplementedError("Phase 3: PII propagation check")
