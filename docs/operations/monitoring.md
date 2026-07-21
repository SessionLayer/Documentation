# Monitoring

This guide gives you the two SLOs SessionLayer commits to, the signals each
component emits, and the alerts worth paging on — including the shipped,
ready-to-import alert rules and dashboard. The design principle behind all of
it: the Tier-0 Gateway exposes **no new inbound listener** for metrics; its
telemetry is pushed out as OpenTelemetry spans and gauges, and Prometheus
metrics are derived from those by a collector.

## The two SLOs

| SLO | Target | Why this number |
|---|---|---|
| Session-establishment latency (NFR-4) | **p95 ≤ 250 ms**, excluding human OIDC time | the machine path — authorize, sign, connect — should be invisible next to typing a command |
| Session-CA signing availability (NFR-3) | **99.9 %**, measured on real sign requests | the session CA gates every *new* session (existing ones continue); it is an availability peer of your database, and it fails closed |

Both are measured from meters the Control Plane emits
(Micrometer → `/actuator/prometheus`):

- `sessionlayer_session_establishment_seconds_*` — histogram, tagged
  `outcome` (`allow`/`deny`/`error`/`cancelled`) and `access_model`.
- `sessionlayer_cert_sign_seconds_*` — histogram, tagged `kind` and
  `outcome`.
- `sessionlayer_ca_signer_total` — counter, tagged `kind`, `source`
  (`request`/`probe`), `outcome` — availability is computed over
  `source="request"` only, so the health-probe baseline can't mask real
  degradation.

> **Note:** keep *deny* out of your error panels. A deny is policy working;
> `outcome="error"` is the platform failing closed. The shipped dashboard
> separates them, and conflating them buries the 3am signal in policy noise.

## Shipped assets

Both product repositories ship ready-to-use observability assets:

| Asset | Where (repo path) | What it does |
|---|---|---|
| CP SLO alert rules | `ControlPlane-API/deploy/observability/prometheus-slo-rules.yaml` | pages on both SLO breaches, CA-signer fail-closed spikes, Authorize error-rate > 10 %, and no-traffic |
| Grafana dashboard | `ControlPlane-API/deploy/observability/grafana-slo-dashboard.json` | RED for establishment + CA signer + Gateway span-metrics + saturation panels |
| Span-metrics collector config | `Gateway/deploy/observability/otel-collector-spanmetrics.yaml` | turns Gateway/Agent spans into `calls_total` + `duration_milliseconds_bucket` Prometheus series |
| Gateway RED alert rules | `Gateway/deploy/observability/prometheus-gateway-red-rules.yaml` | session error-ratio, host-verify failure spike, node-connect p95, dial-back errors |

## The Gateway's signals: spans, span-metrics, two gauges

The Gateway and Agent emit OpenTelemetry **spans** (OTLP push, enabled by
setting `OTEL_EXPORTER_OTLP_ENDPOINT`), carrying IDs, enums, and durations —
never session content. One trace follows a session end to end: the Gateway
starts the root span, the Control Plane's authorize and cert-sign spans join
it, and Agent spans (`agent.dial_back`, `agent.splice`) correlate by
`sessionlayer.session_id` — which is also the join key into the
[audit stream](../admin-guides/audit.md) and the recording.

The shipped collector config derives RED metrics from those spans, keyed by
`span_name` (`gateway.session`, `outer_leg.auth`, `node.connect`,
`host_verify`, `bridge_setup`) and `status_code`. Fail-closed closes —
including Control-Plane-down at authentication — mark their spans as errors,
so the span-derived error rate reflects real outages; ordinary auth-scan
rejections deliberately do not, preserving the signal.

Two native gauges ride the same outbound OTLP pipeline (no listener):

- `sessionlayer.gateway.live_sessions` — current live sessions.
- `sessionlayer.gateway.lock_feed_healthy` — 0/1: is the pushed deny-list
  stream healthy?

## What to page on

Beyond the shipped rules, three signals deserve explicit pages:

**Lock feed stale.** `sessionlayer.gateway.lock_feed_healthy == 0` for more
than a couple of minutes. While unhealthy, that Gateway is deliberately
refusing what it cannot verify (deny wins) — new sessions degrade and
break-glass channels are refused, so this is a user-facing incident even
though it is "correct" behavior. It self-heals on reconnect;
persistent 0 means the CP gRPC path is down.

**Break-glass used.** Every activation raises a high-priority alert through
the configured alert target and lands as an ERROR-level log plus audit
events. Page on it from your log pipeline or
[SIEM forward](../admin-guides/audit.md) (there is deliberately no
Gateway-side metric for it) — a break-glass use at 3am should wake a human
even when it's legitimate.

**Fail-closed fast burn.** The shipped `CaSignerFailClosedSpike` rule pages
within minutes when real sign requests start failing closed — a total signer
outage stops all *new* sessions, and the 30-minute availability window is too
slow to notice it alone. Its Authorize-side sibling
(`SessionEstablishmentErrorSpike`) catches the same class at the decision
layer.

Also watch (warn, not page): the [session-limit meters](../admin-guides/session-limits.md)
(`sessionlayer.session.lease.reaped` nonzero in steady state; remember
`sessionlayer.session.lease.live` is fleet-wide — aggregate `max`, never
`sum`), presence heartbeat failures on large fleets
([High availability](../admin-guides/high-availability.md)), and the
host-verify failure spike rule — which is either a re-keyed node you forgot
to re-enroll, or someone impersonating a node; both deserve a look
([Nodes](../admin-guides/nodes.md)).

## The Agent

The Agent is outbound-only and exposes no inbound endpoint at all, by
design. Its signals are its **exit codes** (3 = clone detected, 4 =
repair needed, 2 = self-verification refused — all should page; see the
[Agent runbook](agent-runbook.md)), its `SECURITY`/`REPAIR-NEEDED` log
lines, and its OTel spans when export is enabled.

## Honest limits

The enumerated next increment — per-RPC RED on the Control Plane's gRPC
surface, Gateway channel-open/relay/spool saturation gauges, Agent
dial-back/renew counters, and native `lockfeed.subscribers` /
`breakglass.activation_total` meters on the CP — is **not shipped**. The
fail-closed events those would count are present in the structured logs
today; ship the logs to your collector and derive from there until native
emission lands.

## Next

- [Gateway runbook](gateway-runbook.md) — turning an alert into a diagnosis.
- [Agent runbook](agent-runbook.md) — the exit-code contract.
- [Metrics](../reference/metrics.md) — the full meter/span reference.
- [Production hardening](../security/hardening.md) — the SIEM forward these
  pages assume.
