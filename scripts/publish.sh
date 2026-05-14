#!/usr/bin/env bash
# Local PyPI publish, keyed off the repo-local .env.
#
# Usage:
#   ./scripts/publish.sh              # publishes the version in pyproject.toml
#   ./scripts/publish.sh 0.0.15       # bumps pyproject + CHANGELOG header, then publishes
#
# Reads TWINE_USERNAME and TWINE_PASSWORD from .env (git-ignored).
# Never prints the token. Never commits .env.

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "error: .env not found at repo root."
  echo "       create it with TWINE_USERNAME=__token__ and TWINE_PASSWORD=pypi-...,"
  echo "       then re-run."
  exit 2
fi

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
echo "==> publishing caliper-ai $VER"

# Load .env into the environment. Twine reads TWINE_USERNAME / TWINE_PASSWORD.
set -a
# shellcheck disable=SC1091
source .env
set +a

if [[ -z "${TWINE_USERNAME:-}" || -z "${TWINE_PASSWORD:-}" ]]; then
  echo "error: TWINE_USERNAME / TWINE_PASSWORD not set after sourcing .env."
  exit 2
fi

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

echo "==> twine upload"
uvx twine upload dist/*

echo "==> polling PyPI for $VER"
for attempt in 1 2 3 4 5 6 7 8; do
  if uvx --refresh --from "caliper-ai==$VER" caliper --version >/dev/null 2>&1; then
    echo "ok: caliper-ai $VER installable from PyPI"
    break
  fi
  echo "    attempt $attempt: index lag, sleeping 15s..."
  sleep 15
done

cat <<EOF

  ==============================
  caliper-ai $VER published.

  Next steps (run yourself, this script does not push):

    git add pyproject.toml CHANGELOG.md
    git commit -m "chore(release): $VER"
    git push origin main
    git tag -a "v$VER" -m "v$VER"
    git push origin "v$VER"

  CI will detect the tag, re-build, and stage a GitHub release.
EOF
