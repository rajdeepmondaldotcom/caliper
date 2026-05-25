from __future__ import annotations

import datetime as dt
import math
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


VALID_DASHBOARD_THEMES = ("dark", "light", "print")
VALID_DASHBOARD_RHYTHMS = ("receipt", "terminal")
VALID_DASHBOARD_DENSITIES = ("comfortable", "compact")
VALID_DASHBOARD_PRIVACY = ("off", "print-only", "always")


@dataclass(frozen=True)
class DashboardConfig:
    """User-tweakable defaults for ``caliper dashboard``.

    Lives under a ``[dashboard]`` section in the Caliper config file
    (``~/.config/caliper/config.toml`` or a project-local ``.caliper.toml``).
    CLI flags always win — these values populate the defaults the user
    sees when no flag is passed.

    The ``output_dir`` + ``filename_template`` pair governs where a
    generated dashboard is saved when ``--output`` is omitted. The
    template can include any of the following placeholders:

    * ``{timestamp}`` — formatted using ``timestamp_format`` (strftime).
    * ``{privacy}`` — ``off``, ``print-only``, or ``always``.
    * ``{theme}``, ``{rhythm}``, ``{density}`` — the same values as the
      corresponding flags.
    """

    theme: str = "dark"
    rhythm: str = "receipt"
    density: str = "comfortable"
    # Default: original format — real names everywhere. Privacy redaction
    # is opt-in via the ``--privacy`` flag (print-only | always) or the
    # corresponding key in ``[dashboard]``.
    privacy: str = "off"
    show_paths: bool = False
    output_dir: str = "~/Downloads"
    # ``{privacy_suffix}`` is "" when privacy is off and ``-privacy-<mode>``
    # otherwise — keeps the default filename clean while still tagging
    # redacted exports for traceability. Plain ``{privacy}`` is also
    # accepted for users who want the explicit tag.
    filename_template: str = "caliper-dashboard-{timestamp}{privacy_suffix}.html"
    timestamp_format: str = "%Y-%m-%d-%H-%M"
    open_after: bool = True
    default_days: int = 14
    # Interactive playground: when True the generated HTML embeds both
    # rhythms + a floating toggle panel + a "Save snapshot" button so the
    # recipient can flip between Receipt/Terminal and Dark/Light/Safe Share
    # without re-running the CLI.
    interactive: bool = True


def _coerce_choice(value: object, choices: tuple[str, ...], default: str) -> str:
    """Return ``value`` if it's a valid choice, else ``default``.

    Config-file typos shouldn't crash the CLI — silently fall back so the
    user sees the dashboard render with sensible defaults and can edit
    the file later.
    """
    if not isinstance(value, str):
        return default
    candidate = value.strip().lower()
    return candidate if candidate in choices else default


def load_dashboard_config(loaded: dict) -> DashboardConfig:
    """Project a previously loaded TOML dict's ``[dashboard]`` section.

    Falls back to :class:`DashboardConfig` defaults for any missing or
    invalid field.
    """
    section = loaded.get("dashboard") or {}
    defaults = DashboardConfig()
    return DashboardConfig(
        theme=_coerce_choice(section.get("theme"), VALID_DASHBOARD_THEMES, defaults.theme),
        rhythm=_coerce_choice(section.get("rhythm"), VALID_DASHBOARD_RHYTHMS, defaults.rhythm),
        density=_coerce_choice(section.get("density"), VALID_DASHBOARD_DENSITIES, defaults.density),
        privacy=_coerce_choice(section.get("privacy"), VALID_DASHBOARD_PRIVACY, defaults.privacy),
        show_paths=bool(section.get("show_paths", defaults.show_paths)),
        output_dir=str(section.get("output_dir", defaults.output_dir)),
        filename_template=str(section.get("filename_template", defaults.filename_template)),
        timestamp_format=str(section.get("timestamp_format", defaults.timestamp_format)),
        open_after=bool(section.get("open_after", defaults.open_after)),
        default_days=int(section.get("default_days", defaults.default_days)),
        interactive=bool(section.get("interactive", defaults.interactive)),
    )


def derive_dashboard_output_path(
    cfg: DashboardConfig,
    *,
    now: dt.datetime | None = None,
    theme: str | None = None,
    rhythm: str | None = None,
    density: str | None = None,
    privacy: str | None = None,
) -> Path:
    """Render the ``output_dir / filename_template`` pair into a concrete path.

    Used when the user runs ``caliper dashboard`` with no ``--output`` flag.
    The ``timestamp_format`` is applied to ``now`` (defaulting to the local
    wall clock). Any keyword argument that's ``None`` falls back to the
    corresponding config value, so the caller can pass through the
    already-resolved CLI choices without repeating the merge logic.
    """
    moment = now or dt.datetime.now()
    resolved_privacy = privacy or cfg.privacy
    placeholders = {
        "timestamp": moment.strftime(cfg.timestamp_format),
        "theme": theme or cfg.theme,
        "rhythm": rhythm or cfg.rhythm,
        "density": density or cfg.density,
        "privacy": resolved_privacy,
        # Auto-tag suffix: empty when privacy is the default ``off`` mode,
        # so the filename stays clean. ``-privacy-<mode>`` when redacted so
        # the recipient knows what they're holding.
        "privacy_suffix": ("" if resolved_privacy == "off" else f"-privacy-{resolved_privacy}"),
    }
    # The template is user-controlled — surface a friendly error instead of
    # propagating the raw KeyError when an unknown placeholder is used.
    try:
        name = cfg.filename_template.format(**placeholders)
    except KeyError as exc:
        raise ValueError(
            f"Unknown placeholder {exc.args[0]!r} in filename_template; "
            f"known placeholders: {sorted(placeholders)}"
        ) from exc
    return (Path(cfg.output_dir).expanduser() / name).resolve()


DASHBOARD_CONFIG_TEMPLATE = """\
# Caliper dashboard defaults. CLI flags always override these values.
# Run `caliper dashboard --init-defaults` to regenerate this section.

[dashboard]
# Visual layout
theme = "dark"                # dark | light | print
rhythm = "receipt"            # receipt | terminal
density = "comfortable"       # comfortable | compact

# Privacy / redaction (opt-in)
# off         — original format: real project names, session labels, paths
# print-only  — show real names on screen, swap to indexed placeholders
#               (Project 1, Session 2, [path]) when printing
# always      — indexed placeholders everywhere
#
# Default is "off". Switch with the CLI flag --privacy <mode> or by
# editing this line.
privacy = "off"
show_paths = false            # show full filesystem paths in the projects table

# File output (used when --output is not passed on the CLI)
output_dir = "~/Downloads"
# Placeholders: {timestamp}, {theme}, {rhythm}, {density}, {privacy},
# {privacy_suffix}. {privacy_suffix} is "" when privacy=off and
# "-privacy-<mode>" otherwise — keeps default filenames clean.
filename_template = "caliper-dashboard-{timestamp}{privacy_suffix}.html"
timestamp_format = "%Y-%m-%d-%H-%M"
open_after = true             # auto-open the generated file in a browser

# Interactive playground: embed both rhythms + a floating toggle panel +
# a "Save snapshot" button. Off-by-default for CI/CD, on-by-default for
# humans. The toggle lets the recipient flip between Receipt/Terminal and
# Dark/Light/Safe Share without re-running this CLI.
interactive = true

# Data window
default_days = 14
"""


def write_dashboard_defaults(*, path: Path | None = None, force: bool = False) -> Path:
    """Write a starter ``[dashboard]`` section to the user config.

    If ``path`` is omitted the user-level :data:`USER_CONFIG` is used.
    Refuses to overwrite an existing ``[dashboard]`` section unless
    ``force=True`` — that way existing TUI / pricing sections aren't
    blown away by accident.

    Returns the file path that was written.
    """
    target = (path or USER_CONFIG).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(DASHBOARD_CONFIG_TEMPLATE)
        return target

    existing = target.read_text()
    if "[dashboard]" in existing and not force:
        raise FileExistsError(
            f"{target} already contains a [dashboard] section. "
            f"Pass --force to overwrite, or edit the file by hand."
        )
    if "[dashboard]" in existing and force:
        # Crude but reliable: keep everything before the [dashboard] header
        # and append the fresh template. The TOML parser doesn't tolerate
        # duplicate sections, so this also fixes any prior corruption.
        head = existing.split("[dashboard]", 1)[0].rstrip() + "\n\n"
        target.write_text(head + DASHBOARD_CONFIG_TEMPLATE)
        return target
    # No [dashboard] section yet — append.
    sep = "" if existing.endswith("\n") else "\n"
    target.write_text(existing + sep + "\n" + DASHBOARD_CONFIG_TEMPLATE)
    return target


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
    parse_workers: int | str | None = None,
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
    # Floor the column width so a tiny value (e.g. --width 1) can't render one
    # character per line. Rich needs a usable minimum to lay out tables.
    if width_value is not None and width_value < 40:
        width_value = 40
    no_parse_cache_value = cfg_bool(loaded, "no_parse_cache", no_parse_cache, False)
    project_raw = cfg(loaded, "project", project, None)
    project_value = str(project_raw).strip() if project_raw else None
    parse_workers_value = _parse_workers(loaded, parse_workers)

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
        parse_workers=parse_workers_value,
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
        # A lone future --since (with --until defaulting to now) is the common
        # case; point at the real problem instead of an --until the user never
        # set.
        if since and until is None and start > default_end:
            raise ValueError(f"--window-start {since} is in the future; there is no data after now")
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
        # `nan`/`inf` slip past a bare `<= 0` check and raise OverflowError or
        # ValueError deep in timedelta; reject them up front with a clean error.
        if not math.isfinite(days) or days <= 0:
            raise ValueError("--lookback-days must be a finite number greater than 0")
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


def _parse_workers(loaded: dict, value: int | str | None) -> int:
    raw: object
    env_value = os.environ.get("CALIPER_PARSE_WORKERS", "").strip()
    if value not in (None, ""):
        raw = value
    elif env_value:
        raw = env_value
    elif "parse_workers" in loaded:
        raw = loaded["parse_workers"]
    else:
        raw = "auto"
    return resolve_parse_workers(raw)


def resolve_parse_workers(value: object) -> int:
    if value is None:
        return _available_worker_count()
    raw = str(value).strip().lower()
    if raw in {"", "auto"}:
        return _available_worker_count()
    try:
        workers = int(raw)
    except ValueError as exc:
        raise ValueError("parse_workers must be 'auto' or an integer greater than 0") from exc
    if workers <= 0:
        raise ValueError("parse_workers must be greater than 0")
    return workers


def _available_worker_count() -> int:
    process_cpu_count = getattr(os, "process_cpu_count", None)
    count = process_cpu_count() if process_cpu_count is not None else os.cpu_count()
    return max(1, int(count or 1))


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
