# Manual publish runbook

Use when the GitHub Actions release workflow is unavailable or you
need to ship a hotfix faster than CI. The standard path is still
`git push origin vX.Y.Z`; this runbook is the safety net.

## Prerequisites

- Local clone of `caliper-ai` with a clean working tree.
- `.env` at the repo root containing the PyPI API token. The file is
  git-ignored and never leaves your machine. Format:

    ```env
    TWINE_USERNAME=__token__
    TWINE_PASSWORD=pypi-...
    PYPI_API_TOKEN=pypi-...   # alias, same value
    ```

- `uv` on PATH. `uvx` ships with it.

## Steps

```bash
# 1. Confirm the version you intend to publish.
grep '^version' pyproject.toml          # version = "0.0.X"
VER=$(grep '^version' pyproject.toml | awk -F'"' '{print $2}')
echo "publishing $VER"

# 2. Load credentials. `.env` never enters CI.
set -a
source .env
set +a

# 3. Build a clean wheel + sdist.
rm -rf dist
uv run python -m build

# 4. Validate distributions.
uvx twine check dist/*

# 5. Upload to PyPI.
uvx twine upload dist/*

# 6. Wait for PyPI to surface the new version.
for i in 1 2 3 4 5 6; do
  if uvx --refresh --from "caliper-ai==$VER" caliper --version; then
    echo "ok: $VER installable from PyPI"
    break
  fi
  sleep 15
done

# 7. Tag and push.
git tag -a "v$VER" -m "v$VER"
git push origin "v$VER"
```

## Notes

- The post-tag CI workflow still runs. Its verify step now uses
  `--from` so it will succeed on the same release.
- If PyPI rejects a version because of a deleted-filename clash,
  bump the patch and try again. PyPI permanently reserves deleted
  filenames.
- Never commit `.env` or paste the token into a chat. If the token
  leaks, revoke it on `pypi.org` and rotate before re-publishing.
- The token has upload-only scope by default. Confirm scope under
  `pypi.org → Account → API tokens` before relying on this path.

## What to do if the verify-step poll never resolves

Six attempts at 15 s is the budget. If PyPI is slow, the upload may
still have succeeded. Check `https://pypi.org/project/caliper-ai/`
directly. The wheel and sdist appear immediately in the project file
listing even when the simple index lags.
