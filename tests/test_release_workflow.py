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
PUBLISH_SCRIPT = Path(__file__).parent.parent / "scripts" / "publish.sh"


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
    assert "RELEASE_TAG" in text
    assert "RELEASE_VERSION" in text


def test_pypi_publish_uses_environment_scoped_token():
    text = _workflow_text()
    assert "${{ secrets.PYPI_API_TOKEN }}" in text
    assert "pypa/gh-action-pypi-publish@v1.14.0" in text
    assert re.search(
        r"pypi:\n(?:    .*\n)*?    environment:\n(?:      .*\n)*?      name: pypi",
        text,
    ), "PyPI publish job must use the protected pypi environment"


def test_post_publish_smoke_uses_caliper_executable_not_package_name():
    """The smoke step must invoke `caliper`, not `caliper-ai`."""
    text = _workflow_text()
    pattern = re.compile(r"uvx[^\n]+--from[^\n]+caliper-ai==[^\n]+caliper\s+--version")
    assert pattern.search(text), (
        "Expected `uvx --refresh --from caliper-ai==<ver> caliper --version` "
        "in the post-publish smoke step."
    )


def test_manual_dispatch_uses_input_tag_for_checkout_and_release_steps():
    text = _workflow_text()

    assert "ref: ${{ env.RELEASE_TAG }}" in text
    assert 'tag="${RELEASE_TAG}"' in text
    assert 'CALIPER_SMOKE_VERSION="${RELEASE_VERSION}"' in text


def test_release_smokes_dashboard_from_wheel_and_pypi():
    text = _workflow_text()

    assert "caliper dashboard --demo --output" in text
    assert "scripts/live-release-smoke.sh" in text
    assert "CALIPER_SMOKE_VERSION" in text


def test_local_publish_script_does_not_use_twine_credentials():
    text = PUBLISH_SCRIPT.read_text()

    assert "twine upload" not in text
    assert "TWINE_PASSWORD" not in text
