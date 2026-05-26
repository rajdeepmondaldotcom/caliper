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

    assert "project-scoped" in security
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


def _dist_name(spec: str) -> str:
    import re

    match = re.match(r"[A-Za-z0-9._-]+", spec.strip())
    return match.group(0).replace("_", "-").lower() if match else ""


def test_every_directly_imported_third_party_package_is_declared() -> None:
    """Guard against the 0.0.59 regression: ``click`` was imported directly in
    caliper.cli but only declared transitively via Typer. When Typer 0.26
    dropped its click dependency, fresh installs crashed on ``import click``.
    Any third-party package imported in the source must be a declared
    dependency (or live behind an optional extra)."""
    import ast
    import sys
    import tomllib

    meta = tomllib.loads(PYPROJECT.read_text())["project"]
    declared = {_dist_name(s) for s in meta.get("dependencies", [])}
    for extra_specs in meta.get("optional-dependencies", {}).values():
        declared.update(_dist_name(s) for s in extra_specs)

    # import-name -> distribution-name, where they differ.
    import_to_dist = {"prometheus_client": "prometheus-client"}
    stdlib = set(sys.stdlib_module_names)

    roots: set[str] = set()
    for path in Path("src/caliper").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])

    for root in sorted(roots):
        if root in stdlib or root in {"caliper", "__future__"}:
            continue
        dist = import_to_dist.get(root, root).replace("_", "-").lower()
        assert dist in declared, (
            f"`{root}` is imported in src/caliper but `{dist}` is not a declared "
            f"dependency in pyproject.toml (declared: {sorted(declared)})"
        )


def test_local_publish_script_does_not_upload_to_pypi() -> None:
    script = PUBLISH_SCRIPT.read_text()

    assert "twine upload" not in script
    assert "TWINE_PASSWORD" not in script


def test_docs_and_outreach_trees_are_ignored() -> None:
    ignore = GITIGNORE.read_text()

    for path in ("docs/", "docs-site/", "design-brief/", "editor/", "*.local.md"):
        assert path in ignore
