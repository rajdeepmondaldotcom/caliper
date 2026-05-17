#!/usr/bin/env bash
# Local release preparation. This script never uploads to PyPI.
#
# Usage:
#   ./scripts/publish.sh              # prepares the version in pyproject.toml
#   ./scripts/publish.sh 0.0.30       # bumps pyproject, then prepares artifacts
#
# PyPI publish happens through the GitHub Actions release workflow using
# the protected `pypi` environment secret. Push an annotated vX.Y.Z tag
# after this script passes.

set -euo pipefail

cd "$(dirname "$0")/.."

# Optional version-bump arg.
if [[ $# -ge 1 ]]; then
  new_version="$1"
  if ! [[ "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "error: version '$new_version' must look like 0.1.2."
    exit 2
  fi
  current=$(grep '^version = ' pyproject.toml | head -n1 | awk -F'"' '{print $2}')
  if [[ "$current" == "$new_version" ]]; then
    echo "note: pyproject already at $new_version, skipping bump."
  else
    /usr/bin/sed -i.bak "s/^version = \"$current\"/version = \"$new_version\"/" pyproject.toml
    rm -f pyproject.toml.bak
    echo "ok: bumped pyproject.toml $current -> $new_version"
  fi
fi

VER=$(grep '^version = ' pyproject.toml | head -n1 | awk -F'"' '{print $2}')
echo "==> preparing caliper-ai $VER"

echo "==> running tests"
uv run pytest -q

echo "==> ruff check + format"
uv run ruff check .
uv run ruff format --check .

echo "==> clean dist/"
rm -rf dist

echo "==> build sdist + wheel"
uv run python -m build

echo "==> twine check"
uvx twine check dist/*

echo "==> release smoke"
bash scripts/release-smoke.sh

cat <<EOF

  ==============================
  caliper-ai $VER prepared locally.

  Next steps (run yourself; this script does not commit, tag, push, or upload):

    git add pyproject.toml uv.lock CHANGELOG.md .github/workflows/release.yml \\
      SECURITY.md docs/release-and-ux-overhaul/RUNBOOK-publish.md \\
      tests/test_release_workflow.py scripts/publish.sh
    git commit -m "chore(release): $VER"
    git push origin main
    git tag -a "v$VER" -m "v$VER"
    git push origin "v$VER"

  CI will detect the tag, re-build, publish to PyPI through the protected
  pypi environment, publish the GitHub release, and run the post-release smoke.
EOF
