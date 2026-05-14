from __future__ import annotations

import datetime as dt
import sqlite3
import subprocess  # nosec
import sys
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from caliper.evidence import warnings_from_parser_issues
from caliper.humanize import format_int
from caliper.models import VENDOR_CURSOR, LoadResult, ParserIssue, RuntimeOptions, UsageEvent
from caliper.parse_cache import ParseCache, default_cache_path
from caliper.pricing import (
    PRICING_SOURCES,
    RateCard,
    load_rate_card,
    normalize_model,
    pricing_catalog_status,
)

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


@dataclass(frozen=True)
class WarningSummary:
    kind: str
    count: int
    examples: list[str]

    def to_record(self) -> dict:
        return {
            "kind": self.kind,
            "count": self.count,
            "examples": self.examples,
        }


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
        check_pricing_catalog(options),
        check_rates_file(options.rates_file),
        check_parse_cache(),
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
        checks.extend(parser_warning_checks(result.warnings, result.parser_issues))
        checks.append(check_cache_creation_rates(result.events, options))
        checks.append(check_cursor_token_coverage(result.events, result.parser_issues))
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
        f"checked {age} days ago — run `caliper rates show` and consider updating.",
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


def check_pricing_catalog(options: RuntimeOptions) -> HealthCheck:
    try:
        rate_card = load_rate_card(options)
    except ValueError as exc:
        return doctor_check("Pricing catalog", "fail", str(exc))
    status = pricing_catalog_status(rate_card)
    models = int(status.get("models") or 0)
    warnings = status.get("warnings") or []
    if options.pricing_source == "embedded":
        return doctor_check("Pricing catalog", "ok", "embedded pricing source selected")
    if not models:
        detail = "no cached live catalog; using embedded rate card"
        if options.offline:
            return doctor_check("Pricing catalog", "ok", "offline mode; using embedded rate card")
        return doctor_check("Pricing catalog", "warn", "; ".join([detail, *map(str, warnings)]))
    age_hours = status.get("age_hours")
    age_text = "unknown age" if age_hours is None else f"{float(age_hours):.1f}h old"
    detail = f"{models:,} models from {status.get('source')} ({age_text})"
    if warnings:
        detail = f"{detail}; {warnings[0]}"
    if age_hours is None or float(age_hours) <= 24:
        return doctor_check("Pricing catalog", "ok", detail)
    if float(age_hours) <= 24 * 7:
        return doctor_check("Pricing catalog", "warn", detail)
    return doctor_check("Pricing catalog", "fail", detail)


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


def check_parse_cache() -> HealthCheck:
    path = default_cache_path()
    if not path.exists():
        return doctor_check("Parse cache", "ok", f"{path} (not created yet)")
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
        with ParseCache(path) as cache:
            stats = cache.indexed_stats()
    except (OSError, sqlite3.Error) as exc:
        return doctor_check("Parse cache", "warn", f"{path} unreadable: {exc}")
    return doctor_check(
        "Parse cache",
        "ok",
        (
            f"{path} ({size_mb:.1f} MiB, {stats['files']:,} indexed files, "
            f"{stats['events']:,} events, {stats['samples']:,} samples, "
            f"{stats['unsupported_files']:,} unsupported files)"
        ),
    )


def check_cache_creation_rates(events: list[UsageEvent], options: RuntimeOptions) -> HealthCheck:
    if not any(
        event.usage.cache_creation_input_tokens or event.usage.cache_creation_input_1h_tokens
        for event in events
    ):
        return doctor_check("Cache creation rates", "ok", "no cache-write events found")
    rate_card = load_rate_card(options)
    missing = 0
    for event in events:
        if not (
            event.usage.cache_creation_input_tokens or event.usage.cache_creation_input_1h_tokens
        ):
            continue
        rates = _api_rates_for_event(rate_card, event)
        if rates is None:
            missing += 1
            continue
        if event.usage.cache_creation_input_tokens and rates.cache_creation_input is None:
            missing += 1
        if event.usage.cache_creation_input_1h_tokens and rates.cache_creation_input_1h is None:
            missing += 1
    if missing:
        return doctor_check(
            "Cache creation rates",
            "warn",
            f"{missing:,} cache-write events fall back to base input pricing.",
        )
    return doctor_check("Cache creation rates", "ok", "cache-write rates are explicit")


def _api_rates_for_event(rate_card: RateCard, event: UsageEvent):
    model = normalize_model(event.model)
    if model in rate_card.api_overrides:
        return rate_card.api_overrides[model]
    card = rate_card._card_for(model)
    return card.api_rates if card else None


def check_cursor_token_coverage(
    events: list[UsageEvent],
    parser_issues: list[ParserIssue] | None = None,
) -> HealthCheck:
    unsupported = sum(
        issue.count
        for issue in parser_issues or []
        if issue.vendor == VENDOR_CURSOR and issue.kind == "unsupported:no_token_usage"
    )
    missing = sum(1 for event in events if event.vendor == VENDOR_CURSOR and event.usage.is_zero())
    if unsupported:
        noun = "file" if unsupported == 1 else "files"
        detail = f"{unsupported:,} Cursor {noun} have no per-event token counts."
        if missing:
            detail = f"{detail} {missing:,} parsed Cursor events also have zero token counts."
        return doctor_check("Cursor token coverage", "warn", detail)
    if missing:
        return doctor_check(
            "Cursor token coverage",
            "warn",
            f"{missing:,} Cursor events have no per-event token counts.",
        )
    return doctor_check("Cursor token coverage", "ok", "no Cursor token gaps found")


def check_cursor_token_sentinel(events: list[UsageEvent]) -> HealthCheck:
    return check_cursor_token_coverage(events)


CURSOR_TOKEN_WARNING_PREFIX = "Cursor session has no per-event token counts: "  # nosec B105


def parser_warning_checks(
    warnings: list[str], parser_issues: list[ParserIssue] | None = None
) -> list[HealthCheck]:
    checks: list[HealthCheck] = []
    issues = parser_issues or []
    grouped = parser_warning_summary(warnings, issues)
    for summary in grouped:
        if summary.kind == "cursor-token-coverage":
            checks.append(
                doctor_check(
                    "Parser warning",
                    "warn",
                    _cursor_token_warning_detail(summary),
                )
            )
    consumed = set(warnings_from_parser_issues(issues))
    for warning in warnings:
        if warning.startswith(CURSOR_TOKEN_WARNING_PREFIX) or warning in consumed:
            continue
        checks.append(doctor_check("Parser warning", "warn", warning))
    return checks


def parser_warning_summary(
    warnings: list[str], parser_issues: list[ParserIssue] | None = None
) -> list[WarningSummary]:
    cursor_examples: list[str] = []
    for warning in warnings:
        if warning.startswith(CURSOR_TOKEN_WARNING_PREFIX):
            cursor_examples.append(warning.removeprefix(CURSOR_TOKEN_WARNING_PREFIX))
    for issue in parser_issues or []:
        if issue.vendor == VENDOR_CURSOR and issue.kind == "unsupported:no_token_usage":
            cursor_examples.extend(issue.examples)
            if issue.count > len(issue.examples):
                cursor_examples.extend([""] * (issue.count - len(issue.examples)))
    summaries: list[WarningSummary] = []
    if cursor_examples:
        examples = [example for example in cursor_examples if example]
        summaries.append(
            WarningSummary(
                kind="cursor-token-coverage",
                count=len(cursor_examples),
                examples=examples[:3],
            )
        )
    return summaries


def _cursor_token_warning_detail(summary: WarningSummary) -> str:
    noun = "file" if summary.count == 1 else "files"
    examples = "; ".join(summary.examples)
    return f"{summary.count:,} Cursor {noun} have no per-event token counts (examples: {examples})"
