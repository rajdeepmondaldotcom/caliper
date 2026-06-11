from __future__ import annotations

from types import SimpleNamespace

import pytest

from caliper.self_update import AUTO_UPGRADE_ATTEMPTED_ENV, maybe_upgrade_dashboard


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

    assert commands == [[*reexec[0][1][:1], "-m", "pip", "install", "--upgrade", "caliper-ai"]]
    assert reexec[0][1][1:] == ["-m", "caliper", "dashboard", "--demo"]
    assert env[AUTO_UPGRADE_ATTEMPTED_ENV] == "1"
    assert any("upgrading" in message for message in messages)
