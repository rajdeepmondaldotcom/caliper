from __future__ import annotations

import datetime as dt
import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from caliper.config import build_options
from caliper.parser import load_usage

from .conftest import make_state_db, token_event, turn_context, write_session


@given(st.text(alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd")), min_size=1))
@settings(
    max_examples=75,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_prompt_text_never_reaches_usage_event_repr(tmp_path, marker_part: str) -> None:
    marker = f"PRIVATE_MARKER_{marker_part}_END"
    session_root = tmp_path / "sessions"
    now = dt.datetime.now(tz=dt.UTC)
    session_path = write_session(
        session_root,
        "rollout-2026-05-12T00-00-00-private.jsonl",
        [
            {"type": "event_msg", "payload": {"type": "user_message", "message": marker}},
            turn_context(model="gpt-5.5", service_tier="standard"),
            token_event(now, {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110}),
        ],
    )
    state_db = tmp_path / "state.sqlite"
    if state_db.exists():
        state_db.unlink()
    make_state_db(state_db, session_path)
    options = build_options(
        days=1,
        until=(now + dt.timedelta(seconds=1)).isoformat(),
        session_root=session_root,
        state_db=state_db,
        codex_config=tmp_path / "missing.toml",
        vendors=["openai-codex"],
    )

    result = load_usage(options)

    assert result.events
    serialized = "\n".join(
        repr(event) + json.dumps(event.__dict__, default=str) for event in result.events
    )
    assert marker not in serialized
