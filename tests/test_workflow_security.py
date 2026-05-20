from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_DIR = Path(__file__).parent.parent / ".github" / "workflows"
PINNED_ACTION_RE = re.compile(r"uses:\s+[^@\s]+@[0-9a-f]{40}(?:\s+#\s+\S+)?$")


def test_workflow_actions_are_pinned_to_commit_sha() -> None:
    for workflow in WORKFLOW_DIR.glob("*.yml"):
        for line_number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            if "uses:" not in line:
                continue
            assert PINNED_ACTION_RE.search(line), (
                f"{workflow.relative_to(WORKFLOW_DIR.parent.parent)}:{line_number} "
                "must pin actions to a full commit SHA"
            )
