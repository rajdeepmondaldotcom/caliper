"""Guard the release workflow against the bug that failed 0.0.3..0.0.6.

The `Verify the published release installs` step used to run

    uvx --refresh "caliper-ai==X" caliper --version

which uvx parses as the executable name ``caliper-ai==X``. Every release
verify step failed. The fix is one flag: ``--from``.

These tests pin the invariant. Plain string scanning on the workflow
YAML so the suite stays fast and dependency-free.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "release.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text()


def test_release_workflow_exists():
    assert WORKFLOW.exists(), "release.yml must live at .github/workflows/release.yml"


def test_uvx_refresh_lines_use_from_when_pinning_a_version():
    """Any uvx --refresh that pins a == spec must also pass --from."""
    text = _workflow_text()
    for line in text.splitlines():
        if "uvx" not in line or "--refresh" not in line:
            continue
        if "==" not in line:
            continue
        assert "--from" in line, (
            f"uvx --refresh line pins a version spec without --from; "
            f"executable resolution will fail.\n  {line.strip()}"
        )


def test_validate_tag_step_exists():
    text = _workflow_text()
    assert "Validate tag matches pyproject version" in text


def test_pypi_publish_uses_token_secret():
    text = _workflow_text()
    assert "${{ secrets.PYPI_API_TOKEN }}" in text


def test_post_publish_smoke_uses_caliper_executable_not_package_name():
    """The smoke step must invoke `caliper`, not `caliper-ai`."""
    text = _workflow_text()
    pattern = re.compile(r"uvx[^\n]+--from[^\n]+caliper-ai==[^\n]+caliper\s+--version")
    assert pattern.search(text), (
        "Expected `uvx --refresh --from caliper-ai==<ver> caliper --version` "
        "in the post-publish smoke step."
    )
