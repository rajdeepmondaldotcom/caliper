from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess  # nosec
import sys
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from codex_meter.humanize import format_int
from codex_meter.models import LoadResult, RuntimeOptions
from codex_meter.parse_cache import default_cache_path
from codex_meter.pricing import PRICING_SOURCES, RateCard

HEALTH_STATUS_STYLES = {"ok": "green", "warn": "yellow", "fail": "red"}
HEALTH_EXIT_CODES = {"ok": 0, "warn": 1, "fail": 2}
HEALTH_SEVERITY_RANK = {"ok": 0, "warn": 1, "fail": 2}


@dataclass(frozen=True)
class HealthCheck:
    label: str
    status: str
    detail: str

    def to_record(self) -> dict[str, str]:
        return {"label": self.label, "status": self.status, "detail": self.detail}


def doctor_check(label: str, status: str, detail: str) -> HealthCheck:
    return HealthCheck(label, status, detail)


def build_health_report(
    *,
    options: RuntimeOptions,
    session_file_count: int,
    result: LoadResult | None,
) -> list[HealthCheck]:
    checks = [
        check_python_version(),
        doctor_check(
            "Session root",
            "ok" if options.session_root.exists() else "fail",
            f"{options.session_root} ({format_int(session_file_count)} JSONL files)",
        ),
        doctor_check(
            "State DB",
            "ok" if options.state_db.exists() else "warn",
            str(options.state_db),
        ),
        check_state_db_readable(options.state_db),
        doctor_check(
            "Codex config",
            "ok" if options.config_path.exists() else "warn",
            str(options.config_path),
        ),
        check_codex_cli_version(),
        check_rate_card_age(),
        check_rates_file(options.rates_file),
        doctor_check("Parse cache", "ok", str(default_cache_path())),
        check_clock_skew(result.events if result else []),
    ]

    if result:
        checks.append(doctor_check("Events loaded", "ok", f"{len(result.events):,} in last 7 days"))
        if result.events:
            inferred = result.tier_sources.get("assumed", 0) + result.tier_sources.get(
                "current-config", 0
            )
            if inferred == len(result.events):
                checks.append(
                    doctor_check(
                        "Tier coverage",
                        "warn",
                        "No events recorded a tier; pin one with --service-tier "
                        "or --tier-overrides.",
                    )
                )
        for warning in result.warnings:
            checks.append(doctor_check("Parser warning", "warn", warning))
    return checks


def worst_health_status(checks: Iterable[HealthCheck]) -> str:
    worst = "ok"
    for check in checks:
        if HEALTH_SEVERITY_RANK[check.status] > HEALTH_SEVERITY_RANK[worst]:
            worst = check.status
    return worst


def check_codex_cli_version() -> HealthCheck:
    try:
        completed = subprocess.run(  # noqa: S603 # nosec
            ["codex", "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except FileNotFoundError:
        return doctor_check("Codex CLI", "warn", "not found on PATH; install Codex for live data.")
    except (subprocess.TimeoutExpired, OSError) as exc:
        return doctor_check("Codex CLI", "warn", f"could not invoke (`{exc}`)")
    version = (completed.stdout or completed.stderr or "").strip().splitlines()[0:1]
    return doctor_check("Codex CLI", "ok", version[0] if version else "found")


def check_clock_skew(events) -> HealthCheck:
    if not events:
        return doctor_check("Clock", "ok", "no events to compare")
    latest = max(event.timestamp for event in events)
    now = dt.datetime.now(tz=dt.UTC)
    skew = (latest - now).total_seconds()
    detail = clock_skew_detail(skew)
    if abs(skew) <= 300:
        return doctor_check("Clock", "ok", f"latest event {detail}")
    if abs(skew) <= 86400:
        return doctor_check("Clock", "warn", f"latest event {detail}")
    return doctor_check("Clock", "fail", f"latest event {detail}")


def clock_skew_detail(skew_seconds: float) -> str:
    seconds = int(abs(skew_seconds))
    if seconds < 60:
        amount = f"{seconds}s"
    else:
        minutes, rem_seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        amount = f"{hours}h {minutes}m" if hours else f"{minutes}m {rem_seconds}s"
    if skew_seconds > 0:
        return f"{amount} in the future"
    return f"{amount} ago"


def check_rate_card_age() -> HealthCheck:
    age = rate_card_age_days()
    if age <= 30:
        return doctor_check("Rate card", "ok", f"checked {age} days ago")
    if age <= 90:
        return doctor_check("Rate card", "warn", f"checked {age} days ago")
    return doctor_check(
        "Rate card",
        "fail",
        f"checked {age} days ago — run `codex-meter rates show` and consider updating.",
    )


def rate_card_age_days() -> int:
    today = dt.date.today()
    ages: list[int] = []
    for source in PRICING_SOURCES:
        try:
            checked = dt.date.fromisoformat(source.checked)
        except ValueError:
            continue
        ages.append((today - checked).days)
    return max(ages) if ages else 0


def check_state_db_readable(path: Path) -> HealthCheck:
    if not path.exists():
        return doctor_check("State DB readable", "warn", "state DB is missing")
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            conn.execute("select count(*) from sqlite_master").fetchone()
    except sqlite3.Error as exc:
        return doctor_check("State DB readable", "warn", f"could not open read-only: {exc}")
    return doctor_check("State DB readable", "ok", "read-only open succeeded")


def check_rates_file(path: Path | None) -> HealthCheck:
    if path is None:
        return doctor_check("Rates file", "ok", "using embedded rate card")
    try:
        RateCard.load(path)
    except ValueError as exc:
        return doctor_check("Rates file", "fail", str(exc))
    return doctor_check("Rates file", "ok", str(path))


def check_python_version() -> HealthCheck:
    info = sys.version_info
    if info < (3, 11):
        return doctor_check("Python", "fail", f"{info.major}.{info.minor} — requires >= 3.11")
    return doctor_check("Python", "ok", f"{info.major}.{info.minor}.{info.micro}")
