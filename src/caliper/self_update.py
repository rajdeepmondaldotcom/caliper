from __future__ import annotations

import json
import os
import re
import subprocess  # nosec
import sys
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from caliper.network import BROWSER_USER_AGENT, CALIPER_USER_AGENT, fetch_text, resolve_url

GITHUB_LATEST_RELEASE_URL = "https://github.com/rajdeepmondaldotcom/caliper/releases/latest"
PYPI_PROJECT_URL = "https://pypi.org/pypi/caliper-ai/json"
PYPI_SIMPLE_URL = "https://pypi.org/simple/caliper-ai/"
AUTO_UPGRADE_ATTEMPTED_ENV = "CALIPER_DASHBOARD_UPGRADE_ATTEMPTED"
AUTO_UPGRADE_ENV = "CALIPER_DASHBOARD_AUTO_UPGRADE"
NO_AUTO_UPGRADE_ENV = "CALIPER_NO_AUTO_UPGRADE"

_FALSEY = {"0", "false", "no", "off"}
_TRUTHY = {"1", "true", "yes", "on"}
_CALIPER_FILENAME_VERSION_RE = re.compile(
    r"caliper[_-]ai-(?P<version>\d+(?:\.\d+)+(?:[A-Za-z0-9_.!+]*)?)(?=-|\.tar\.gz)"
)


@dataclass(frozen=True)
class AvailableRelease:
    version: str
    install_target: str


def maybe_upgrade_dashboard(
    current_version: str,
    *,
    interactive: bool,
    quiet: bool = False,
    argv: list[str] | None = None,
    env: MutableMapping[str, str] | None = None,
    echo: Callable[[str], None] | None = None,
    latest_version: Callable[[], str | AvailableRelease | None] = lambda: fetch_latest_release(),
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

    release = _coerce_release(latest_version())
    if not release:
        return "unavailable"
    if _version_tuple(release.version) <= _version_tuple(current_version):
        return "current"

    echo(f"Caliper {release.version} is available; upgrading before rendering the dashboard...")
    completed = runner(
        [sys.executable, "-m", "pip", "install", "--upgrade", release.install_target],
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
    echo(f"Caliper upgraded to {release.version}; restarting dashboard...")
    execv(sys.executable, [sys.executable, "-m", "caliper", *argv[1:]])
    return "reexec"


def fetch_latest_release(timeout: int = 2) -> AvailableRelease | None:
    return _fetch_latest_from_github(timeout) or _release_from_version(
        fetch_latest_version(timeout)
    )


def fetch_latest_version(timeout: int = 2) -> str | None:
    versions = [
        version
        for version in (
            _fetch_latest_from_simple_index(timeout),
            _fetch_latest_from_project_json(timeout),
        )
        if version
    ]
    return max(versions, key=_version_tuple) if versions else None


def _fetch_latest_from_github(timeout: int) -> AvailableRelease | None:
    try:
        resolved = resolve_url(
            GITHUB_LATEST_RELEASE_URL,
            allowed_schemes={"https"},
            source_kind="GitHub latest release",
            accept="text/html,*/*",
            timeout=timeout,
            user_agents=(CALIPER_USER_AGENT, BROWSER_USER_AGENT),
        )
    except (OSError, TimeoutError):
        return None

    match = re.search(r"/releases/tag/v(?P<version>\d+(?:\.\d+)+)", resolved)
    if not match:
        return None
    version = match.group("version")
    wheel_url = (
        "https://github.com/rajdeepmondaldotcom/caliper/releases/download/"
        f"v{version}/caliper_ai-{version}-py3-none-any.whl"
    )
    return AvailableRelease(version=version, install_target=wheel_url)


def _fetch_latest_from_simple_index(timeout: int) -> str | None:
    try:
        text = fetch_text(
            PYPI_SIMPLE_URL,
            allowed_schemes={"https"},
            source_kind="PyPI simple package index",
            accept="text/html",
            timeout=timeout,
            user_agents=(CALIPER_USER_AGENT, BROWSER_USER_AGENT),
            retry_statuses={503},
        )
    except (OSError, TimeoutError):
        return None
    versions = _versions_from_simple_html(text)
    return max(versions, key=_version_tuple) if versions else None


def _fetch_latest_from_project_json(timeout: int) -> str | None:
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


def _release_from_version(version: str | None) -> AvailableRelease | None:
    if not version:
        return None
    return AvailableRelease(version=version, install_target=f"caliper-ai=={version}")


def _coerce_release(value: str | AvailableRelease | None) -> AvailableRelease | None:
    if isinstance(value, AvailableRelease):
        return value
    return _release_from_version(value)


def _versions_from_simple_html(text: str) -> set[str]:
    parser = _SimpleIndexParser()
    parser.feed(text)
    return parser.versions


class _SimpleIndexParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.versions: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        match = _CALIPER_FILENAME_VERSION_RE.search(href)
        if match:
            self.versions.add(match.group("version"))


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
