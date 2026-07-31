# Metrics

SessionLayer's telemetry carries correlation, never content: IDs, enums, counts, durations, and
outcomes. It never carries session plaintext, keys, tokens, or codes. This page lists every meter
and span the components emit, derived from the observability contract and the source.

The split by component:

- The Control Plane exposes Micrometer meters at `/actuator/prometheus` and can export OTLP traces.
- The Gateway and Agent emit OTLP traces only. The [Tier-0](glossary.md) data plane deliberately
  carries no metrics pipeline; their rate/error/duration metrics are derived centrally from spans by
  an OpenTelemetry Collector (below).

## Enabling export

| Component | Metrics | Traces |
|---|---|---|
| Control Plane | `/actuator/prometheus` (exposed by default alongside `health`, `info`, `metrics`) | OTLP, off by default; enable by setting both `management.otlp.tracing.export.enabled=true` and `management.otlp.tracing.endpoint` (service name via `management.opentelemetry.resource-attributes.service.name`, default `sessionlayer-controlplane`; sampling via `management.tracing.sampling.probability`) |
| Gateway | none (span-derived) | OTLP, on only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set; service name `sessionlayer-gateway` (`OTEL_SERVICE_NAME` overrides) |
| Agent | none (span-derived) | Same convention; service name `sessionlayer-agent` |

## Names as exported

The names below are the in-code ones, and Prometheus renames them on the way out. Control Plane
meters lose their dots to underscores and gain the unit and type suffixes Prometheus expects, so a
timer scrapes as `_seconds_count`, `_seconds_sum` and `_seconds_bucket` and a counter as `_total`:
`sessionlayer.ca.signer` is `sessionlayer_ca_signer_total` at `/actuator/prometheus`, and
`sessionlayer.cert.sign` is `sessionlayer_cert_sign_seconds_bucket`. Gauges take neither suffix.

Span names are not renamed, because they never become metric names. The collector emits
`calls_total` and `duration_milliseconds_bucket` and carries the span name as a `span_name` label
value, dots intact, as in
`calls_total{service_name="sessionlayer-gateway",span_name="gateway.host_verify"}`. Span attributes
do become label names and do lose their dots, so `sessionlayer.outcome` queries as
`sessionlayer_outcome`.

## Control Plane meters

All tags are closed enums. `session_id`, `correlation_id`, `node_id`, and identities are
high-cardinality, so they never appear as tags; they live on the trace instead. The
`correlation_id` on a trace is your pivot into the [audit stream](audit-events.md).

| Meter | Type | Tags | What it measures |
|---|---|---|---|
| `sessionlayer.session.establishment` | timer | `outcome` (`allow`/`deny`/`error`/`cancelled`), `access_model` | Control-Plane-side session-establishment latency: the machine work of the authorize path (decision + session write + token mint). Human login time is deliberately excluded. The 250 ms p95 SLO (NFR-4) is pre-configured as a histogram SLO boundary. |
| `sessionlayer.cert.sign` | timer | `kind`, `outcome` | Certificate-signing latency (session inner certificate, gateway host certificate): the second machine leg of establishment. 100 ms SLO boundary. |
| `sessionlayer.ca.signer` | counter | `kind`, `source` (`request`/`probe`), `outcome` (`available`/`unavailable`/`error`) | Session-CA signing availability (NFR-3). Compute the 99.9% availability over `source="request"`; the periodic probe baseline would otherwise mask partial degradation. |
| `sessionlayer.session.limit` | counter | `outcome` (`denied`), `access_model` | Session-limit denials at authorization. A spike means identities are hitting their concurrency cap. |
| `sessionlayer.session.lease.reaped` | counter | none | Leaked concurrency leases released by the reaper sweep. Non-zero means Gateways are failing to report session end; investigate before trusting the concurrency count. |
| `sessionlayer.session.lease.live` | gauge | none | Fleet-wide live (unreleased, unexpired) concurrency leases. |
| `sessionlayer.session.lease.live.refresh.failed` | counter | none | Failed refreshes of the live-lease gauge. The gauge is stale until the next success. |
| `sessionlayer.session.lifecycle` | counter | `rpc` (`notify_session_end`/`extend_session_lease`), `outcome` (`released`/`not_released`/`extended`/`refused`/`error`) | Session-lifecycle RPC outcomes. Lease-partition and reaped-live-lease signatures show up here. |

> **Note:** `sessionlayer.session.lease.live` is a fleet-wide count and every Control Plane instance
> reports the same value. On a scaled-out deployment aggregate it with `max` (or last), never `sum`:
> summing double-counts. It reads 0 until the first refresh (about one
> `sessionlayer.session-limits.gauge-refresh` interval after boot).

## Spans

One distributed trace ties a session together: the Gateway is the trace root (a stock `ssh` client
cannot send `traceparent`), and it propagates W3C trace context to the Control Plane on every gRPC
call, so the Control Plane spans join the same trace.

| Span | Owner | Parent |
|---|---|---|
| `gateway.session` | Gateway | root (minted at outer SSH accept) |
| `gateway.outer_leg.auth` | Gateway | `gateway.session` |
| `cp.authorize` | Control Plane | `gateway.session` (via gRPC metadata) |
| `cp.cert_sign` | Control Plane | `gateway.session` (via gRPC metadata) |
| `gateway.node.connect` | Gateway | `gateway.session` |
| `gateway.host_verify` | Gateway | `gateway.session` |
| `gateway.bridge_setup` | Gateway | `gateway.session` |
| `agent.enroll` | Agent | own trace (identity lifecycle) |
| `agent.renew` | Agent | own trace (identity lifecycle) |
| `agent.dial_back` | Agent | own trace, correlated by session id |
| `agent.splice` | Agent | own trace, correlated by session id |

Agent data-path spans do not share the Gateway's trace id. The Agent–Gateway wire protocol is
frozen and carries no trace context. They stamp the same session id attribute, so one query by
session id still returns every leg.

Standard span attributes, set where known: `sessionlayer.session_id`,
`sessionlayer.correlation_id` (after authorization returns), `sessionlayer.node_id`,
`sessionlayer.access_model`, and `sessionlayer.outcome` on decision spans. Span status is set to
error on failure with the error category, never secret content.

## Gateway and Agent RED metrics from spans

The reference OpenTelemetry Collector configuration
(`Gateway/deploy/observability/otel-collector-spanmetrics.yaml`) derives rate/errors/duration for
every span above with the `spanmetrics` connector and serves them to Prometheus on `:9464`:

- Dimensions: `sessionlayer.outcome` and `sessionlayer.access_model` only (closed enums).
- Histogram buckets straddle the 250 ms establishment budget (5 ms–5 s), so the data-path legs are
  queryable against the SLO.
- `service.name` is kept as a label, so Gateway and Agent split cleanly.

See [Monitoring](../operations/monitoring.md) for the SLOs, alert suggestions, and dashboard
guidance built on these.

## The no-content guarantee

No span, attribute, event, metric, or log may carry SSH session plaintext, key material, OTPs,
bearer/session/join tokens, device codes, PINs, passwords, or recording bytes. This is enforced by
tests in all three components that render telemetry output and grep it for known secret markers.

## Next

- [Monitoring](../operations/monitoring.md)
- [Audit events](audit-events.md)
- [Control Plane configuration](config-control-plane.md)
- [Ports](ports.md)
