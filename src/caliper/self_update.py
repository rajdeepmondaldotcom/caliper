from __future__ import annotations

import json
import os
import re
import subprocess  # nosec
import sys
from collections.abc import Callable, MutableMapping
from typing import Any

from caliper.network import fetch_text

PYPI_PROJECT_URL = "https://pypi.org/pypi/caliper-ai/json"
AUTO_UPGRADE_ATTEMPTED_ENV = "CALIPER_DASHBOARD_UPGRADE_ATTEMPTED"
AUTO_UPGRADE_ENV = "CALIPER_DASHBOARD_AUTO_UPGRADE"
NO_AUTO_UPGRADE_ENV = "CALIPER_NO_AUTO_UPGRADE"

_FALSEY = {"0", "false", "no", "off"}
_TRUTHY = {"1", "true", "yes", "on"}


def maybe_upgrade_dashboard(
    current_version: str,
    *,
    interactive: bool,
    quiet: bool = False,
    argv: list[str] | None = None,
    env: MutableMapping[str, str] | None = None,
    echo: Callable[[str], None] | None = None,
    latest_version: Callable[[], str | None] = lambda: fetch_latest_version(),
    runner: Callable[..., Any] = subprocess.run,
    execv: Callable[[str, list[str]], Any] = os.execv,
) -> str:
    """Upgrade an installed Caliper before rendering the dashboard.

    Returns a short status for tests/diagnostics. On a successful upgrade this
    process is replaced with ``python -m caliper ...`` and normally never
    returns.
    """
    env = os.environ if env is None else env
    argv = sys.argv if argv is None else argv
    echo = (lambda _text: None) if echo is None else echo

    if not interactive or quiet:
        return "skipped"
    if not _auto_upgrade_enabled(env):
        return "disabled"
    if env.get(AUTO_UPGRADE_ATTEMPTED_ENV):
        return "attempted"
    if _is_local_version(current_version):
        return "local"

    latest = latest_version()
    if not latest:
        return "unavailable"
    if _version_tuple(latest) <= _version_tuple(current_version):
        return "current"

    echo(f"Caliper {latest} is available; upgrading before rendering the dashboard...")
    completed = runner(
        [sys.executable, "-m", "pip", "install", "--upgrade", "caliper-ai"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
    )
    if getattr(completed, "returncode", 1) != 0:
        echo(f"Caliper auto-upgrade failed; continuing with {current_version}.")
        return "failed"

    env[AUTO_UPGRADE_ATTEMPTED_ENV] = "1"
    if env is not os.environ:
        os.environ[AUTO_UPGRADE_ATTEMPTED_ENV] = "1"
    echo(f"Caliper upgraded to {latest}; restarting dashboard...")
    execv(sys.executable, [sys.executable, "-m", "caliper", *argv[1:]])
    return "reexec"


def fetch_latest_version(timeout: int = 2) -> str | None:
    try:
        text = fetch_text(
            PYPI_PROJECT_URL,
            allowed_schemes={"https"},
            source_kind="PyPI package metadata",
            accept="application/json",
            timeout=timeout,
        )
        payload = json.loads(text)
    except (OSError, TimeoutError, json.JSONDecodeError):
        return None
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    return str(version) if version else None


def _auto_upgrade_enabled(env: MutableMapping[str, str]) -> bool:
    value = env.get(AUTO_UPGRADE_ENV, "1").strip().lower()
    no_value = env.get(NO_AUTO_UPGRADE_ENV, "").strip().lower()
    if value in _FALSEY:
        return False
    return no_value not in _TRUTHY


def _is_local_version(version: str) -> bool:
    return "+" in version or version == "0.0.0"


def _version_tuple(version: str) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", version.split("+", 1)[0])]
    return tuple(parts or [0])
