from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path


def write_session(root: Path, name: str, events: list[dict]) -> Path:
    path = root / "2026" / "05" / "12" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
    return path


def token_event(timestamp: dt.datetime, usage: dict, *, plan_type: str = "pro") -> dict:
    return {
        "type": "event_msg",
        "timestamp": timestamp.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "payload": {
            "type": "token_count",
            "info": {"last_token_usage": usage},
            "rate_limits": {
                "plan_type": plan_type,
                "credits": None,
                "primary": {"used_percent": 25.0},
                "secondary": {"used_percent": 75.0},
            },
        },
    }


def total_token_event(timestamp: dt.datetime, total_usage: dict, *, plan_type: str = "pro") -> dict:
    return {
        "type": "event_msg",
        "timestamp": timestamp.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": total_usage, "model_context_window": 258400},
            "rate_limits": {
                "plan_type": plan_type,
                "credits": None,
                "primary": {"used_percent": 25.0, "window_minutes": 300, "resets_at": 1},
                "secondary": {"used_percent": 75.0, "window_minutes": 10080, "resets_at": 2},
            },
        },
    }


def rate_limit_only_event(timestamp: dt.datetime, *, plan_type: str = "pro") -> dict:
    return {
        "type": "event_msg",
        "timestamp": timestamp.astimezone(dt.UTC).isoformat().replace("+00:00", "Z"),
        "payload": {
            "type": "token_count",
            "info": None,
            "rate_limits": {
                "plan_type": plan_type,
                "credits": None,
                "primary": {"used_percent": 34.0, "window_minutes": 300, "resets_at": 1},
                "secondary": {"used_percent": 91.0, "window_minutes": 10080, "resets_at": 2},
                "rate_limit_reached_type": None,
            },
        },
    }


def user_message(message: str) -> dict:
    return {
        "type": "event_msg",
        "timestamp": "2026-05-12T00:00:00Z",
        "payload": {"type": "user_message", "message": message},
    }


def turn_context(*, model: str = "gpt-5.5", service_tier: str = "fast") -> dict:
    return {
        "type": "turn_context",
        "timestamp": "2026-05-12T00:00:00Z",
        "payload": {
            "model": model,
            "service_tier": service_tier,
            "collaboration_mode": {"settings": {"reasoning_effort": "xhigh"}},
        },
    }


def make_state_db(path: Path, rollout_path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            create table threads (
                rollout_path text,
                title text,
                first_user_message text,
                cwd text,
                git_branch text,
                git_origin_url text,
                model text,
                reasoning_effort text,
                created_at integer,
                updated_at integer
            )
            """
        )
        conn.execute(
            """
            insert into threads values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(rollout_path),
                "Synthetic private prompt that should be redacted after a sensible limit",
                "first message",
                "/tmp/project-alpha",
                "main",
                "https://github.com/example/project-alpha",
                "gpt-5.5",
                "xhigh",
                1_715_000_000,
                1_715_000_010,
            ),
        )
