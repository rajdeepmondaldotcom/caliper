"""Prometheus exporter. Opt-in via the `[prom]` extra.

Why a separate module? `prometheus_client` is an optional dependency. Importing
this module triggers the dependency check; the rest of caliper stays import-clean.
"""

from __future__ import annotations

import http.server
from collections.abc import Callable
from dataclasses import dataclass, field

try:
    from prometheus_client import CollectorRegistry, Gauge, generate_latest
except ImportError as exc:  # pragma: no cover - import guard tested via integration only
    raise ImportError(
        "prometheus-client is not installed. Install with: pip install 'caliper-ai[prom]'"
    ) from exc


PROM_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@dataclass(frozen=True)
class MetricsSnapshot:
    cost_usd: float
    burn_per_hour: float
    primary_window_percent: float
    secondary_window_percent: float
    events_total: int
    long_context_events_total: int
    tokens_total: dict[tuple[str, str, str], int] = field(default_factory=dict)
    # Pricing confidence for the window: exact | partial | estimated | unsupported.
    # Exposed as a label so a dashboard can tell trustworthy cost from estimated.
    pricing_status: str = "exact"


def build_metrics_text(snapshot: MetricsSnapshot) -> bytes:
    """Render a Prometheus text-format payload from a snapshot."""
    registry = CollectorRegistry()
    cost = Gauge(
        "caliper_cost_usd",
        "Effective USD cost in the current rolling window.",
        registry=registry,
    )
    cost.set(snapshot.cost_usd)

    burn = Gauge(
        "caliper_burn_per_hour",
        "Rate-limit burn rate in percent-points per hour for the active window.",
        registry=registry,
    )
    burn.set(snapshot.burn_per_hour)

    window_pct = Gauge(
        "caliper_window_used_percent",
        "Rate-limit window used percent (0..100).",
        ["window"],
        registry=registry,
    )
    window_pct.labels(window="primary").set(snapshot.primary_window_percent)
    window_pct.labels(window="secondary").set(snapshot.secondary_window_percent)

    tokens = Gauge(
        "caliper_tokens_total",
        "Token counts by model, tier, and kind (input|cached|output|reasoning).",
        ["model", "tier", "kind"],
        registry=registry,
    )
    for (model, tier, kind), count in snapshot.tokens_total.items():
        tokens.labels(model=model, tier=tier, kind=kind).set(count)

    events = Gauge(
        "caliper_events_total",
        "Token-count events observed in the current window.",
        registry=registry,
    )
    events.set(snapshot.events_total)

    long_ctx = Gauge(
        "caliper_long_context_events_total",
        "Long-context events (>=threshold input tokens) observed in the current window.",
        registry=registry,
    )
    long_ctx.set(snapshot.long_context_events_total)

    # Carry the pricing caveat into monitoring: cost above may be estimated.
    # Info-style gauge (always 1) whose `status` label names the confidence,
    # so an alert can fire when status != "exact".
    pricing_status = Gauge(
        "caliper_pricing_status",
        "Pricing confidence for caliper_cost_usd (status label: "
        "exact|partial|estimated|unsupported). Always 1; read the label.",
        ["status"],
        registry=registry,
    )
    pricing_status.labels(status=snapshot.pricing_status).set(1)

    return generate_latest(registry)


def make_handler(snapshot_fn: Callable[[], MetricsSnapshot]):
    """Build a BaseHTTPRequestHandler subclass that exposes /metrics."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 — HTTPServer naming convention
            if self.path != "/metrics":
                self.send_error(404, "Only /metrics is exported")
                return
            body = build_metrics_text(snapshot_fn())
            self.send_response(200)
            self.send_header("Content-Type", PROM_CONTENT_TYPE)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

        def log_message(self, fmt: str, *args: object) -> None:  # silence default logging
            return

    return Handler


def serve_forever(host: str, port: int, snapshot_fn: Callable[[], MetricsSnapshot]) -> None:
    """Bind and serve /metrics until interrupted. Default bind is 127.0.0.1."""
    server = http.server.ThreadingHTTPServer((host, port), make_handler(snapshot_fn))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return
    finally:
        server.server_close()
