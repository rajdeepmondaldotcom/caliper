from __future__ import annotations

from pathlib import Path

SECURITY = Path("SECURITY.md")
PYPROJECT = Path("pyproject.toml")
CHANGELOG = Path("CHANGELOG.md")
CONTRIBUTING = Path("CONTRIBUTING.md")
PUBLISH_SCRIPT = Path("scripts/publish.sh")
GITIGNORE = Path(".gitignore")


def test_security_doc_has_no_broken_trusted_publisher_setup_link() -> None:
    security = SECURITY.read_text()

    assert "Trusted Publisher" in security
    assert "docs/caliper-vision/10-pypi-trusted-publisher-setup.md" not in security


def test_release_metadata_mentions_current_version() -> None:
    import re
    import tomllib

    version = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    changelog = CHANGELOG.read_text()
    security = SECURITY.read_text()

    assert re.search(rf"^## {re.escape(version)}(?:\s+-[^\n]*)?$", changelog, re.MULTILINE)
    assert f"| `{version}` | yes |" in security


def test_contributing_dependency_and_coverage_contract_matches_package() -> None:
    contributing = CONTRIBUTING.read_text()

    assert "coverage floor is 88%" in contributing
    for dep in ("rich", "typer", "platformdirs", "textual", "watchdog"):
        assert dep in contributing


def test_local_publish_script_does_not_upload_to_pypi() -> None:
    script = PUBLISH_SCRIPT.read_text()

    assert "twine upload" not in script
    assert "TWINE_PASSWORD" not in script


def test_docs_and_outreach_trees_are_ignored() -> None:
    ignore = GITIGNORE.read_text()

    for path in ("docs/", "docs-site/", "design-brief/", "editor/", "*.local.md"):
        assert path in ignore
