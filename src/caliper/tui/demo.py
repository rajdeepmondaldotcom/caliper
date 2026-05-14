"""Deterministic synthetic data for ``caliper tui --demo``.

We do not hand-build ``UsageEvent`` instances (``Usage`` is frozen with
``init=False`` and the right construction path is through the parser).
Instead, demo mode writes a tiny seeded JSONL session into a temp
directory and feeds the existing ``load_usage`` pipeline so the UI
sees the same shapes as real data.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import tempfile
from dataclasses import replace
from pathlib import Path

from caliper.models import RuntimeOptions

_DEMO_MODELS = ("gpt-5.5", "gpt-5-codex", "claude-sonnet-4-6")
_DEMO_PROJECTS = ("caliper-ai", "pr/auth-redo", "spike/parser")


def materialize_demo(template: RuntimeOptions, seed: int = 0xCA11BE12) -> RuntimeOptions:
    """Write deterministic JSONL into a temp dir and return scoped options."""
    rng = random.Random(seed)
    root = Path(tempfile.mkdtemp(prefix="caliper-demo-"))
    now = dt.datetime.now(tz=dt.UTC).replace(microsecond=0)
    for day in range(30):
        when = now - dt.timedelta(days=day, hours=rng.randint(0, 8))
        model = rng.choice(_DEMO_MODELS)
        project = rng.choice(_DEMO_PROJECTS)
        session_dir = root / f"{when:%Y}" / f"{when:%m}" / f"{when:%d}"
        session_dir.mkdir(parents=True, exist_ok=True)
        safe = project.replace("/", "-")
        path = session_dir / f"rollout-{when:%Y-%m-%dT%H-%M-%S}-{safe}.jsonl"
        events = [
            {
                "type": "turn_context",
                "timestamp": _iso(when),
                "payload": {"model": model, "cwd": f"/work/{project}"},
            },
            _token_event(
                when,
                {
                    "input_tokens": rng.randint(2_000, 20_000),
                    "cached_input_tokens": rng.randint(0, 4_000),
                    "output_tokens": rng.randint(200, 4_000),
                    "reasoning_output_tokens": rng.randint(0, 800),
                    "total_tokens": 0,
                },
            ),
        ]
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n")
    return replace(template, session_root=root)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def _token_event(when: dt.datetime, usage: dict) -> dict:
    return {
        "type": "event_msg",
        "timestamp": _iso(when),
        "payload": {
            "type": "token_count",
            "info": {"last_token_usage": usage},
            "rate_limits": {
                "plan_type": "pro",
                "limit_id": "codex",
                "limit_name": None,
                "primary": {"used_percent": 12.0, "window_minutes": 300},
                "secondary": {"used_percent": 34.0, "window_minutes": 10_080},
            },
        },
    }
