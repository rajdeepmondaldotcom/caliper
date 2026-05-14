#!/usr/bin/env bash
set -euo pipefail

ROOT="$(mktemp -d)"
OUT="$ROOT/out"
mkdir -p "$OUT"

export CALIPER_CACHE_DIR="$ROOT/cache"
export XDG_DATA_HOME="$ROOT/data"

printf '[budgets]\ndaily_cost_usd = 999999999\nweekly_cost_usd = 999999999\nmonthly_cost_usd = 999999999\n' > "$ROOT/.caliper.toml"
printf '%s\n' '{"timestamp":"2026-05-12T00:00:00Z","path":"/tmp/session.jsonl","session_id":"session","usage":{"input_tokens":1,"total_tokens":1},"model":"gpt-5.5","service_tier":"standard","tier_source":"logged","thread":{}}' > "$ROOT/event.json"

json_ok() {
  local name="$1"
  shift
  local file="$OUT/$name.json"
  "$@" > "$file"
  python -m json.tool "$file" >/dev/null
  local bytes
  bytes="$(wc -c < "$file" | tr -d ' ')"
  printf '%s ok json bytes=%s\n' "$name" "$bytes"
}

text_ok() {
  local name="$1"
  shift
  local file="$OUT/$name.txt"
  "$@" > "$file"
  local bytes
  bytes="$(wc -c < "$file" | tr -d ' ')"
  printf '%s ok text bytes=%s\n' "$name" "$bytes"
}

json_ok overview uv run caliper overview --output-format json
json_ok daily uv run caliper daily --lookback-days 1 --output-format json --row-limit 5
json_ok weekly uv run caliper weekly --lookback-days 14 --output-format json --row-limit 5
json_ok monthly uv run caliper monthly --lookback-days 45 --output-format json --row-limit 5
json_ok session uv run caliper session --lookback-days 1 --output-format json --row-limit 5
json_ok blocks uv run caliper blocks --lookback-days 1 --recent --row-limit 5 --output-format json
json_ok project uv run caliper project --lookback-days 1 --output-format json --row-limit 5
json_ok models uv run caliper models --lookback-days 1 --output-format json --row-limit 5
json_ok evidence uv run caliper evidence --lookback-days 1 --output-format json
json_ok limits uv run caliper limits --lookback-days 1 --output-format json --row-limit 5
json_ok insights uv run caliper insights --lookback-days 1 --output-format json --row-limit 5
json_ok tail uv run caliper tail --lookback-days 1 --output-format json --event-limit 5
json_ok statusline uv run caliper statusline --output-format json
json_ok forecast uv run caliper forecast --forecast-history-days 7 --output-format json
json_ok compare_total uv run caliper compare --comparison-window-a "last 1 days" --comparison-window-b "previous 1 days" --output-format json
json_ok compare_vendor uv run caliper compare --comparison-window-a "last 1 days" --comparison-window-b "previous 1 days" --comparison-grouping vendor --output-format json
json_ok whatif uv run caliper whatif --scenario-history-days 1 --hypothetical-service-tier fast --output-format json
json_ok advise uv run caliper advise --lookback-days 1 --output-format json
json_ok vendors uv run caliper vendors list --output-format json
json_ok taxonomy uv run caliper taxonomy show --output-format json
json_ok schema_export uv run caliper schema export --output-format json
text_ok schema_validate uv run caliper schema validate "$ROOT/event.json"
json_ok rates_show uv run caliper rates show --output-format json
json_ok rates_catalog uv run caliper rates catalog --output-format json
json_ok grafana uv run caliper export grafana
text_ok receipt_md uv run caliper export receipt --receipt-month 2026-05 --receipt-format markdown --receipt-row-limit 2
text_ok receipt_html uv run caliper export receipt --receipt-month 2026-05 --receipt-format html --receipt-row-limit 2
json_ok budgets uv run caliper budgets check --config "$ROOT/.caliper.toml" --output-format json
text_ok live uv run caliper live --refresh-max-ticks 1 --refresh-interval 0.5

if command -v curl >/dev/null 2>&1; then
  PORT="$(python - <<'PY'
import socket

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
print(sock.getsockname()[1])
sock.close()
PY
)"
  uv run caliper export prometheus --port "$PORT" > "$OUT/prometheus.log" 2>&1 &
  PROM_PID="$!"
  prometheus_ok=0
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 10 "http://127.0.0.1:$PORT/metrics" > "$OUT/metrics.txt" 2> "$OUT/curl.err"; then
      grep -q '^caliper_' "$OUT/metrics.txt"
      prometheus_ok=1
      break
    fi
    sleep 1
  done
  kill "$PROM_PID" >/dev/null 2>&1 || true
  wait "$PROM_PID" >/dev/null 2>&1 || true
  if [[ "$prometheus_ok" != 1 ]]; then
    cat "$OUT/prometheus.log"
    cat "$OUT/curl.err"
    exit 1
  fi
  printf 'prometheus ok text bytes=%s\n' "$(wc -c < "$OUT/metrics.txt" | tr -d ' ')"
fi

if [[ "${CALIPER_SMOKE_ALLOW_NETWORK:-0}" == "1" ]]; then
  uv run caliper rates refresh --allow-network --output "$OUT/rates-live.json" > "$OUT/rates-refresh.txt"
  python -m json.tool "$OUT/rates-live.json" >/dev/null
  printf 'rates_refresh ok json bytes=%s\n' "$(wc -c < "$OUT/rates-live.json" | tr -d ' ')"
fi

if git rev-parse HEAD >/dev/null 2>&1; then
  json_ok commit_head uv run caliper commit "$(git rev-parse HEAD)" --output-format json
fi
if git rev-parse HEAD~1 >/dev/null 2>&1; then
  json_ok pr_range uv run caliper pr --range "HEAD~1..HEAD" --git-no-network --output-format json
fi

printf 'release smoke ok root=%s\n' "$ROOT"
