#!/usr/bin/env bash
set -euo pipefail

ROOT="$(mktemp -d)"
VENV="$ROOT/venv"
OUT="$ROOT/out"
SESSION_ROOT="$ROOT/sessions"
STATE_DB="$ROOT/state.sqlite"
CONFIG="$ROOT/config.toml"
PACKAGE="${CALIPER_SMOKE_PACKAGE:-caliper-ai}"
VERSION_SPEC=""

export CALIPER_CACHE_DIR="$ROOT/cache"
export XDG_DATA_HOME="$ROOT/data"
export CLAUDE_CONFIG_DIR="$ROOT/claude-empty"
export CALIPER_CURSOR_HOME="$ROOT/cursor-empty"
export CALIPER_AIDER_ROOT="$ROOT/aider-empty"

if [[ -n "${CALIPER_SMOKE_VERSION:-}" ]]; then
  VERSION_SPEC="==${CALIPER_SMOKE_VERSION}"
fi

mkdir -p "$OUT"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install "${PACKAGE}${VERSION_SPEC}" >/dev/null

cat > "$CONFIG" <<'TOML'
[budgets]
daily_cost_usd = 25
weekly_cost_usd = 100
monthly_cost_usd = 500
TOML

"$VENV/bin/python" - <<PY
import datetime as dt
import json
import sqlite3
from pathlib import Path

root = Path("$SESSION_ROOT") / "2026" / "05" / "12"
root.mkdir(parents=True, exist_ok=True)
session = root / "rollout-2026-05-12T00-00-00-live-smoke.jsonl"
now = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
events = [
    {
        "type": "turn_context",
        "timestamp": now,
        "payload": {
            "cwd": "/tmp/caliper-live-smoke",
            "model": "gpt-5.5",
            "service_tier": "standard",
        },
    },
    {
        "type": "event_msg",
        "timestamp": now,
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {
                    "input_tokens": 1000,
                    "cached_input_tokens": 500,
                    "output_tokens": 100,
                    "reasoning_output_tokens": 25,
                    "total_tokens": 1100,
                }
            },
            "rate_limits": {
                "plan_type": "pro",
                "limit_id": "codex",
                "primary": {"used_percent": 25.0},
                "secondary": {"used_percent": 75.0},
            },
        },
    },
]
session.write_text("\\n".join(json.dumps(event) for event in events) + "\\n")

with sqlite3.connect("$STATE_DB") as conn:
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
        "insert into threads values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            str(session),
            "Live release smoke",
            "first message",
            "/tmp/caliper-live-smoke",
            "main",
            "https://github.com/example/caliper-live-smoke",
            "gpt-5.5",
            "medium",
            1715000000,
            1715000010,
        ),
    )
PY

json_ok() {
  local name="$1"
  shift
  "$@" > "$OUT/$name.json"
  "$VENV/bin/python" -m json.tool "$OUT/$name.json" >/dev/null
  printf '%s ok\n' "$name"
}

text_ok() {
  local name="$1"
  shift
  "$@" > "$OUT/$name.txt"
  test -s "$OUT/$name.txt"
  printf '%s ok\n' "$name"
}

text_allow_health_exit() {
  local name="$1"
  shift
  set +e
  "$@" > "$OUT/$name.txt"
  local code="$?"
  set -e
  if [[ "$code" -gt 2 ]]; then
    return "$code"
  fi
  test -s "$OUT/$name.txt"
  printf '%s ok exit=%s\n' "$name" "$code"
}

COMMON=(
  --session-root "$SESSION_ROOT"
  --state-db "$STATE_DB"
  --codex-config "$CONFIG"
)

text_ok version "$VENV/bin/caliper" --version
json_ok overview "$VENV/bin/caliper" overview "${COMMON[@]}" --format json
json_ok daily "$VENV/bin/caliper" daily "${COMMON[@]}" --days 1 --format json
json_ok models "$VENV/bin/caliper" models "${COMMON[@]}" --days 1 --format json
json_ok evidence "$VENV/bin/caliper" evidence "${COMMON[@]}" --days 1 --format json
json_ok insights "$VENV/bin/caliper" insights "${COMMON[@]}" --days 1 --format json
json_ok shape "$VENV/bin/caliper" shape "${COMMON[@]}" --days 1 --format json
json_ok advise "$VENV/bin/caliper" advise "${COMMON[@]}" --days 1 --format json
json_ok statusline "$VENV/bin/caliper" statusline "${COMMON[@]}" --days 1 --format json
json_ok rates_catalog "$VENV/bin/caliper" rates catalog --format json
text_ok statusline_compact "$VENV/bin/caliper" statusline "${COMMON[@]}" --days 1 --compact
text_ok shape_help "$VENV/bin/caliper" shape --help
text_ok dashboard_help "$VENV/bin/caliper" dashboard --help
text_ok dashboard "$VENV/bin/caliper" dashboard "${COMMON[@]}" --days 1 --no-deltas --output "$OUT/dashboard.html"
test -s "$OUT/dashboard.html"
python - "$OUT/dashboard.html" <<'PY'
from pathlib import Path
import sys

html = Path(sys.argv[1]).read_text(encoding="utf-8")
assert html.count("<script>") == 1, "expected exactly one inline dashboard script"
assert html.count("</script>") == 1, "expected exactly one inline dashboard script close"
for needle in ("://", "<link", " src=", "fetch(", "XMLHttpRequest", "import("):
    assert needle not in html, f"dashboard privacy gate found {needle!r}"
PY
text_allow_health_exit doctor "$VENV/bin/caliper" doctor "${COMMON[@]}"
text_ok tui_help "$VENV/bin/caliper" tui --help

printf 'live release smoke ok root=%s package=%s%s\n' "$ROOT" "$PACKAGE" "$VERSION_SPEC"
