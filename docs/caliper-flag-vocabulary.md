# Caliper Flag Vocabulary

Caliper's CLI flags should read like an observability tool, not a clone of a
vendor-specific usage script. The rule is:

- lead with explicit Caliper-owned names;
- keep older short names as compatibility aliases where they already exist;
- avoid reserved shorthand aliases such as `--json`, `--mode`, `-O`,
  `--locale`, and color toggles;
- make flags name the decision they control, not the implementation detail.

## Primary Names

| Area | Primary Caliper flag | Compatibility alias |
| --- | --- | --- |
| Report window start | `--window-start` | `--since`, `-s` |
| Report window end | `--window-end` | `--until`, `-u` |
| Rolling report window | `--lookback-days` | `--days` |
| Grouping timezone | `--grouping-timezone` | `--timezone`, `-z` |
| Output format | `--output-format` | `--format`, `-f` |
| Output file | `--output-file` | `--output` |
| Codex sessions path | `--codex-session-root` | `--session-root` |
| Codex state DB path | `--codex-state-db` | `--state-db` |
| Codex config path | `--codex-config-file` | `--codex-config` |
| Caliper config path | `--caliper-config-file` | `--config` |
| Pricing mode | `--pricing-estimation-mode` | `--pricing-mode` |
| Pricing source | `--pricing-catalog-source` | `--pricing-source` |
| Pricing cache TTL | `--pricing-catalog-cache-ttl-hours` | `--pricing-cache-ttl-hours` |
| Local rate card | `--rate-card-file` | `--rates-file` |
| Vendor cost behavior | `--vendor-cost-mode` | `--cost-mode`, `-m` |
| Offline pricing | `--pricing-offline-only` | `--offline` |
| Allow pricing network | `--allow-pricing-network` | `--no-offline` |
| Service tier override | `--codex-service-tier` | `--service-tier` |
| Assumed missing tier | `--assumed-service-tier` | `--unknown-service-tier` |
| Tier overrides file | `--service-tier-overrides-file` | `--tier-overrides` |
| Fallback model | `--fallback-model` | `--default-model` |
| Sensitive prompt output | `--include-sensitive-prompts` | `--show-prompts` |
| Vendor filter | `--include-vendor` | `--vendor` |

## Report Controls

| Work | Primary Caliper flag | Compatibility alias |
| --- | --- | --- |
| Row limit | `--row-limit` | `--top`, `--top-threads` |
| Table width | `--table-width` | `--width` |
| Compact output | `--compact-output` | `--compact` |
| Sort order | `--sort-order` | `--order`, `-o` |
| Week start | `--week-start-day` | `--start-of-week`, `-w` |
| Project filter | `--project-filter` | `--project`, `-p` |
| Project-instance split | `--split-by-project-instance` | `--instances`, `-i` |
| Model breakdown rows | `--include-model-breakdown` | `--breakdown`, `-b` |

## Command-Specific Names

| Command | Primary Caliper flag | Compatibility alias |
| --- | --- | --- |
| `session` | `--session-id` | `--id`, `-i` |
| `blocks` | `--only-active-block` | `--active`, `-a` |
| `blocks` | `--recent-blocks` | `--recent`, `-r` |
| `blocks` | `--block-token-limit` | `--token-limit`, `-t` |
| `blocks` | `--block-duration-hours` | `--session-length`, `-n` |
| `models` | `--group-by` | `--by` |
| `tail` | `--event-limit` | `--n` |
| `tail` | `--tail-grouping` | `--by` |
| `rates refresh` | `--allow-live-pricing-network` | `--allow-network` |
| `rates catalog` | `--model-name-query` | `--query`, `-q` |
| `rates catalog` | `--pricing-provider` | `--provider`, `-p` |
| `rates catalog` | `--refresh-live-pricing-catalog` | `--allow-network` |
| `forecast` | `--forecast-history-days` | `--days` |
| `forecast` | `--monthly-credit-cap` | `--cap` |
| `compare` | `--comparison-window-a` | `--a` |
| `compare` | `--comparison-window-b` | `--b` |
| `compare` | `--comparison-grouping` | `--by` |
| `pr` | `--git-range` | `--range` |
| `pr` | `--local-git-only` | `--git-no-network` |
| `whatif` | `--scenario-history-days` | `--days` |
| `whatif` | `--hypothetical-service-tier` | `--tier` |
| `whatif` | `--hypothetical-model` | `--model` |
| `advise` | `--strict-confidence` | `--strict` |
| `advise` | `--explain-rule` | `--explain` |
| `export prometheus` | `--metrics-bind-host` | `--host` |
| `export prometheus` | `--metrics-port` | `--port` |
| `export grafana` | `--dashboard-title` | `--title` |
| `export receipt` | `--receipt-month` | `--month` |
| `export receipt` | `--receipt-format` | `--format`, `-f` |
| `export receipt` | `--receipt-row-limit` | `--top` |
| `export receipt` | `--include-sensitive-receipt-data` | `--show-sensitive` |
| `statusline` | `--watch-interval` | `--watch` |
| `statusline` | `--watch-max-ticks` | `--max-ticks` |
| `live` | `--refresh-interval` | `--interval`, `-i` |
| `live` | `--refresh-max-ticks` | `--max-ticks` |

## Reserved Option Names

Caliper intentionally does not add these ambiguous aliases:

- `--json` / `-j`
- `--mode`
- `-O`
- `--locale`
- `--color` / `--no-color`

Use `--output-format json` or `--output-format compat-json`,
`--vendor-cost-mode`, and `--pricing-offline-only` instead.
