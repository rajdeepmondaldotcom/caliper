from __future__ import annotations

from types import SimpleNamespace

import pytest

from caliper import self_update
from caliper.self_update import (
    AUTO_UPGRADE_ATTEMPTED_ENV,
    AvailableRelease,
    maybe_upgrade_dashboard,
)


def test_dashboard_auto_upgrade_skips_noninteractive_runs() -> None:
    def explode() -> str:
        raise AssertionError("should not fetch PyPI")

    result = maybe_upgrade_dashboard(
        "0.0.88",
        interactive=False,
        env={},
        latest_version=explode,
    )

    assert result == "skipped"


def test_dashboard_auto_upgrade_can_be_disabled() -> None:
    def explode() -> str:
        raise AssertionError("should not fetch PyPI")

    result = maybe_upgrade_dashboard(
        "0.0.88",
        interactive=True,
        env={"CALIPER_DASHBOARD_AUTO_UPGRADE": "0"},
        latest_version=explode,
    )

    assert result == "disabled"


def test_dashboard_auto_upgrade_skips_local_builds() -> None:
    def explode() -> str:
        raise AssertionError("should not fetch PyPI")

    result = maybe_upgrade_dashboard(
        "0.0.0+local",
        interactive=True,
        env={},
        latest_version=explode,
    )

    assert result == "local"


def test_dashboard_auto_upgrade_skips_current_versions() -> None:
    calls: list[list[str]] = []

    def runner(cmd: list[str], **_kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    result = maybe_upgrade_dashboard(
        "0.0.89",
        interactive=True,
        env={},
        latest_version=lambda: "0.0.89",
        runner=runner,
    )

    assert result == "current"
    assert calls == []


def test_dashboard_auto_upgrade_installs_and_reexecs() -> None:
    messages: list[str] = []
    commands: list[list[str]] = []
    reexec: list[tuple[str, list[str]]] = []
    env: dict[str, str] = {}

    def runner(cmd: list[str], **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0)

    def execv(path: str, args: list[str]) -> None:
        reexec.append((path, args))
        raise RuntimeError("reexec")

    with pytest.raises(RuntimeError, match="reexec"):
        maybe_upgrade_dashboard(
            "0.0.88",
            interactive=True,
            argv=["caliper", "dashboard", "--demo"],
            env=env,
            echo=messages.append,
            latest_version=lambda: "0.0.89",
            runner=runner,
            execv=execv,
        )

    assert commands == [
        [*reexec[0][1][:1], "-m", "pip", "install", "--upgrade", "caliper-ai==0.0.89"]
    ]
    assert reexec[0][1][1:] == ["-m", "caliper", "dashboard", "--demo"]
    assert env[AUTO_UPGRADE_ATTEMPTED_ENV] == "1"
    assert any("upgrading" in message for message in messages)


def test_fetch_latest_version_prefers_simple_index(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(url: str, **_kwargs) -> str:
        if url == self_update.PYPI_PROJECT_URL:
            return '{"info": {"version": "0.0.88"}}'
        assert url == self_update.PYPI_SIMPLE_URL
        return """
        <a href="https://files.pythonhosted.org/caliper_ai-0.0.88-py3-none-any.whl">
          caliper_ai-0.0.88-py3-none-any.whl
        </a>
        <a href="https://files.pythonhosted.org/caliper_ai-0.0.90.tar.gz">
          caliper_ai-0.0.90.tar.gz
        </a>
        <a href="https://files.pythonhosted.org/caliper_ai-0.0.89-py3-none-any.whl">
          caliper_ai-0.0.89-py3-none-any.whl
        </a>
        """

    monkeypatch.setattr(self_update, "fetch_text", fake_fetch)

    assert self_update.fetch_latest_version() == "0.0.90"


def test_fetch_latest_version_falls_back_to_project_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_fetch(url: str, **_kwargs) -> str:
        calls.append(url)
        if url == self_update.PYPI_SIMPLE_URL:
            raise OSError("simple index unavailable")
        assert url == self_update.PYPI_PROJECT_URL
        return '{"info": {"version": "0.0.89"}}'

    monkeypatch.setattr(self_update, "fetch_text", fake_fetch)

    assert self_update.fetch_latest_version() == "0.0.89"
    assert calls == [self_update.PYPI_SIMPLE_URL, self_update.PYPI_PROJECT_URL]


def test_dashboard_auto_upgrade_can_install_direct_release_url() -> None:
    commands: list[list[str]] = []
    reexec: list[tuple[str, list[str]]] = []

    def runner(cmd: list[str], **_kwargs):
        commands.append(cmd)
        return SimpleNamespace(returncode=0)

    def execv(path: str, args: list[str]) -> None:
        reexec.append((path, args))
        raise RuntimeError("reexec")

    with pytest.raises(RuntimeError, match="reexec"):
        maybe_upgrade_dashboard(
            "0.0.88",
            interactive=True,
            argv=["caliper", "dashboard"],
            env={},
            latest_version=lambda: AvailableRelease(
                version="0.0.91",
                install_target="https://github.com/example/caliper_ai-0.0.91-py3-none-any.whl",
            ),
            runner=runner,
            execv=execv,
        )

    assert commands == [
        [
            reexec[0][1][0],
            "-m",
            "pip",
            "install",
            "--upgrade",
            "https://github.com/example/caliper_ai-0.0.91-py3-none-any.whl",
        ]
    ]


def test_fetch_latest_release_prefers_github_wheel(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve(url: str, **_kwargs) -> str:
        assert url == self_update.GITHUB_LATEST_RELEASE_URL
        return "https://github.com/rajdeepmondaldotcom/caliper/releases/tag/v0.0.91"

    monkeypatch.setattr(self_update, "resolve_url", fake_resolve)

    release = self_update.fetch_latest_release()

    assert release == AvailableRelease(
        version="0.0.91",
        install_target="https://github.com/rajdeepmondaldotcom/caliper/releases/download/v0.0.91/caliper_ai-0.0.91-py3-none-any.whl",
    )
