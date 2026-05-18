from __future__ import annotations

import datetime as dt
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from caliper.models import RuntimeOptions
from caliper.pricing import normalize_service_tier
from caliper.pricing_catalog import ALLOWED_PRICING_SOURCES, DEFAULT_TTL_HOURS
from caliper.timeutil import (
    WEEK_DAYS,
    is_date_only,
    load_timezone,
    local_timezone,
    parse_datetime,
)

USER_CONFIG = Path.home() / ".config" / "caliper" / "config.toml"
LOCAL_CONFIG = Path(".caliper.toml")


def default_codex_home() -> Path:
    raw = os.environ.get("CODEX_HOME", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".codex"


def default_session_root() -> Path:
    return default_codex_home() / "sessions"


def default_state_db() -> Path:
    return default_codex_home() / "state_5.sqlite"


def default_codex_config() -> Path:
    return default_codex_home() / "config.toml"


def load_config(explicit_path: Path | str | None = None) -> dict:
    paths: list[Path] = [USER_CONFIG, LOCAL_CONFIG]
    if explicit_path:
        # Coerce defensively: Typer callback paths can arrive as plain strings
        # despite the Path annotation, depending on how Click registers the
        # underlying click type. Keep this boundary safe.
        paths.append(explicit_path if isinstance(explicit_path, Path) else Path(explicit_path))
    loaded: dict = {}
    for path in paths:
        if path is None:
            continue
        expanded = path.expanduser()
        if not expanded.exists():
            continue
        try:
            loaded |= tomllib.loads(expanded.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Could not load config {expanded}: {exc}") from exc
    return loaded


VALID_TUI_THEMES = ("slate", "parchment", "colorblind", "monochrome")


@dataclass(frozen=True)
class TuiConfig:
    """User-tweakable knobs for the Textual TUI.

    Persisted under a ``[tui]`` section in ``caliper.toml``. Default
    values match the "first sensible experience" — slate theme, privacy
    on, demo wizard on first run, native filesystem watcher on.
    """

    theme: str = "slate"
    redact: bool = True
    show_demo_on_first_run: bool = True
    no_watchdog: bool = False

    def with_theme(self, theme: str) -> TuiConfig:
        if theme not in VALID_TUI_THEMES:
            raise ValueError(f"unknown tui theme {theme!r}; expected one of {VALID_TUI_THEMES}")
        return replace(self, theme=theme)


def load_tui_config(loaded: dict) -> TuiConfig:
    """Read a previously loaded TOML dict and project its ``[tui]`` section."""
    section = loaded.get("tui") or {}
    defaults = TuiConfig()
    theme_raw = str(section.get("theme", defaults.theme)).strip().lower()
    theme = theme_raw if theme_raw in VALID_TUI_THEMES else defaults.theme
    return TuiConfig(
        theme=theme,
        redact=bool(section.get("redact", defaults.redact)),
        show_demo_on_first_run=bool(
            section.get("show_demo_on_first_run", defaults.show_demo_on_first_run)
        ),
        no_watchdog=bool(section.get("no_watchdog", defaults.no_watchdog)),
    )


def serialize_tui_config(config: TuiConfig) -> dict:
    """Inverse of :func:`load_tui_config` for the ``[tui]`` section."""
    return {
        "theme": config.theme,
        "redact": config.redact,
        "show_demo_on_first_run": config.show_demo_on_first_run,
        "no_watchdog": config.no_watchdog,
    }


def cfg(config: dict, key: str, value, default):
    if value != default:
        return value
    return config.get(key, default)


def cfg_path(config: dict, key: str, value: Path | None, default: Path) -> Path:
    if value is not None:
        return Path(value).expanduser()
    return Path(config.get(key, default)).expanduser()


def cfg_optional_path(config: dict, key: str, value: Path | None) -> Path | None:
    if value is not None:
        return Path(value).expanduser()
    configured = config.get(key)
    return Path(configured).expanduser() if configured else None


def cfg_bool(config: dict, key: str, value: bool, default: bool) -> bool:
    if value != default:
        return bool(value)
    return bool(config.get(key, default))


def validate_choice(name: str, value: str, allowed: set[str]) -> str:
    if value not in allowed:
        choices = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {choices}")
    return value


def build_options(
    *,
    since: str | None = None,
    until: str | None = None,
    days: float | None = None,
    timezone: str = "local",
    session_root: Path | None = None,
    state_db: Path | None = None,
    codex_config: Path | None = None,
    config: Path | None = None,
    pricing_mode: str = "model",
    pricing_source: str = "auto",
    pricing_cache_ttl_hours: int = DEFAULT_TTL_HOURS,
    service_tier: str = "auto",
    unknown_service_tier: str = "current-config",
    tier_overrides: Path | None = None,
    rates_file: Path | None = None,
    no_dedupe: bool = False,
    no_parse_cache: bool = False,
    default_model: str = "gpt-5.5",
    show_prompts: bool = False,
    show_paths: bool = False,
    offline: bool = True,
    compact: bool = False,
    width: int | None = None,
    top_threads: int = 0,
    rate_limit_sample_limit: int = 100,
    include_all_rate_limit_samples: bool = False,
    order: str = "asc",
    start_of_week: str = "sunday",
    project: str | None = None,
    instances: bool = False,
    breakdown: bool = False,
    cost_mode: str = "auto",
    vendors: list[str] | tuple[str, ...] | None = None,
) -> RuntimeOptions:
    loaded = load_config(config)
    timezone_value = str(cfg(loaded, "timezone", timezone, "local"))
    tz = load_timezone(timezone_value)
    start, end = _time_window(loaded, since=since, until=until, days=days, timezone=tz)
    pricing_mode_value = validate_choice(
        "--pricing-mode",
        str(cfg(loaded, "pricing_mode", pricing_mode, "model")),
        {"flat", "model"},
    )
    pricing_source_value = validate_choice(
        "--pricing-source",
        str(cfg(loaded, "pricing_source", pricing_source, "auto")).strip().lower(),
        ALLOWED_PRICING_SOURCES,
    )
    pricing_cache_ttl_hours_value = _positive_int(
        cfg(
            loaded,
            "pricing_cache_ttl_hours",
            pricing_cache_ttl_hours,
            DEFAULT_TTL_HOURS,
        ),
        "--pricing-cache-ttl-hours",
    )
    order_value = validate_choice(
        "--order",
        str(cfg(loaded, "order", order, "asc")),
        {"asc", "desc"},
    )
    start_of_week_value = validate_choice(
        "--start-of-week",
        str(cfg(loaded, "start_of_week", start_of_week, "sunday")).lower(),
        set(WEEK_DAYS),
    )
    cost_mode_value = validate_choice(
        "--cost-mode",
        str(cfg(loaded, "cost_mode", cost_mode, "auto")),
        {"auto", "calculate", "display"},
    )
    service_tier_value = _service_tier(loaded, service_tier)
    unknown_service_tier_value = _unknown_service_tier(loaded, unknown_service_tier)
    top_threads_value = _nonnegative_int(
        cfg(loaded, "top_threads", top_threads, 0),
        "--top-threads",
    )
    rate_limit_sample_limit_value = _nonnegative_int(
        cfg(loaded, "rate_limit_sample_limit", rate_limit_sample_limit, 100),
        "--rate-limit-sample-limit",
    )
    width_value = _positive_optional_int(cfg(loaded, "width", width, None), "--width")
    no_parse_cache_value = cfg_bool(loaded, "no_parse_cache", no_parse_cache, False)
    project_raw = cfg(loaded, "project", project, None)
    project_value = str(project_raw).strip() if project_raw else None

    return RuntimeOptions(
        session_root=cfg_path(loaded, "session_root", session_root, default_session_root()),
        state_db=cfg_path(loaded, "state_db", state_db, default_state_db()),
        config_path=cfg_path(loaded, "codex_config", codex_config, default_codex_config()),
        start=start,
        end=end,
        timezone=timezone_value,
        pricing_mode=pricing_mode_value,
        pricing_source=pricing_source_value,
        pricing_cache_ttl_hours=pricing_cache_ttl_hours_value,
        service_tier=service_tier_value,
        unknown_service_tier=unknown_service_tier_value,
        tier_overrides=cfg_optional_path(loaded, "tier_overrides", tier_overrides),
        rates_file=cfg_optional_path(loaded, "rates_file", rates_file),
        dedupe=True,
        parse_cache=not no_parse_cache_value,
        default_model=str(cfg(loaded, "default_model", default_model, "gpt-5.5")),
        show_prompts=cfg_bool(loaded, "show_prompts", show_prompts, False),
        show_paths=cfg_bool(loaded, "show_paths", show_paths, False),
        offline=cfg_bool(loaded, "offline", offline, True),
        compact=cfg_bool(loaded, "compact", compact, False),
        width=width_value,
        top_threads=top_threads_value,
        rate_limit_sample_limit=rate_limit_sample_limit_value,
        include_all_rate_limit_samples=cfg_bool(
            loaded,
            "include_all_rate_limit_samples",
            include_all_rate_limit_samples,
            False,
        ),
        order=order_value,
        start_of_week=start_of_week_value,
        project=project_value,
        instances=cfg_bool(loaded, "instances", instances, False),
        breakdown=cfg_bool(loaded, "breakdown", breakdown, False),
        cost_mode=cost_mode_value,
        vendors=_vendors(loaded, vendors),
    )


def _time_window(
    loaded: dict,
    *,
    since: str | None,
    until: str | None,
    days: float | None,
    timezone: dt.tzinfo,
) -> tuple[dt.datetime, dt.datetime]:
    default_end = dt.datetime.now(tz=local_timezone()).astimezone(timezone)
    end = parse_datetime(until, default_end, default_tz=timezone)
    if is_date_only(until):
        end += dt.timedelta(days=1)
    start = _start_time(loaded, since=since, days=days, end=end, timezone=timezone)
    if start >= end:
        raise ValueError("--window-start must be before --window-end")
    return start, end


def _start_time(
    loaded: dict,
    *,
    since: str | None,
    days: float | None,
    end: dt.datetime,
    timezone: dt.tzinfo,
) -> dt.datetime:
    if since:
        return _parse_since(since, end=end, timezone=timezone)
    if days is not None:
        if days <= 0:
            raise ValueError("--lookback-days must be greater than 0")
        return end - dt.timedelta(days=days)
    default_days = float(loaded.get("default_days", 30))
    if default_days <= 0:
        raise ValueError("default_days must be greater than 0")
    return end - dt.timedelta(days=default_days)


def _parse_since(
    since: str,
    *,
    end: dt.datetime,
    timezone: dt.tzinfo,
) -> dt.datetime:
    """Resolve `--since` accepting both ISO timestamps and natural-language windows.

    Tries the natural-language window parser first when the input starts with
    a letter (e.g. "last 7 days", "yesterday", "this week"). Falls back to
    the strict ISO/date parser so existing scripts keep working.
    """
    raw = since.strip()
    if raw and raw[0].isalpha():
        from caliper.intervals import parse_interval

        now = end if end.tzinfo else end.replace(tzinfo=timezone)
        try:
            return parse_interval(raw, now).start.astimezone(timezone)
        except ValueError as exc:
            raise ValueError(
                f"--since does not match an ISO date or a known window expression: {raw!r}"
            ) from exc
    return parse_datetime(since, default_tz=timezone)


def _service_tier(loaded: dict, value: str) -> str:
    tier = str(cfg(loaded, "service_tier", value, "auto"))
    if tier != "auto":
        tier = normalize_service_tier(tier)
    return validate_choice("--service-tier", tier, {"auto", "fast", "standard"})


def _unknown_service_tier(loaded: dict, value: str) -> str:
    tier = str(cfg(loaded, "unknown_service_tier", value, "current-config"))
    if tier != "current-config":
        tier = normalize_service_tier(tier)
    return validate_choice(
        "--unknown-service-tier",
        tier,
        {"current-config", "fast", "standard"},
    )


def _positive_int(value, name: str) -> int:
    coerced = int(value)
    if coerced <= 0:
        raise ValueError(f"{name} must be greater than 0")
    return coerced


def _nonnegative_int(value, name: str) -> int:
    coerced = int(value)
    if coerced < 0:
        raise ValueError(f"{name} must be greater than or equal to 0")
    return coerced


def _positive_optional_int(value, name: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, name)


def _vendors(loaded: dict, values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    configured = loaded.get("vendors")
    if values is not None and tuple(values) != ("all",):
        raw = tuple(values)
    elif isinstance(configured, str):
        raw = tuple(item.strip() for item in configured.split(","))
    elif isinstance(configured, list):
        raw = tuple(str(item).strip() for item in configured)
    else:
        raw = ("all",)
    cleaned = tuple(item for item in raw if item)
    selected = cleaned or ("all",)
    from caliper.vendors import VENDORS

    unknown = sorted(set(selected) - {"all"} - set(VENDORS))
    if unknown:
        choices = ", ".join(["all", *sorted(VENDORS)])
        raise ValueError(f"--vendor must be one of: {choices}")
    return selected
