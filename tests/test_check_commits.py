import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_commits.sh"


@pytest.mark.parametrize(
    ("subject", "ok"),
    [
        ("ci: enforce squash merges", True),
        ("feat(engine)!: drop legacy grants", True),
        ("Phase 6: governance", False),
        ("Dashboard: fix tiles", False),
        ("", False),
    ],
)
def test_subject_check(subject, ok):
    result = subprocess.run(["bash", str(SCRIPT), "--subject", subject], capture_output=True)
    assert (result.returncode == 0) is ok
