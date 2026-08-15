# Monitoring

The Tier-0 Gateway exposes no new inbound listener for metrics: its
telemetry pushes out as OpenTelemetry spans and gauges, and Prometheus
metrics are derived from those by a collector. This page gives you the two
SLOs SessionLayer commits to, the signals each component emits, and the
alerts worth paging on, including the shipped, ready-to-import alert rules
and dashboard.

## The two SLOs

| SLO | Target | Why this number |
|---|---|---|
| Session-establishment latency | p95 at or under 250 ms, excluding human OIDC time | the machine path, authorize, sign, connect, should be invisible next to typing a command |
| Session-CA signing availability | 99.9%, measured on real sign requests | the session CA gates every new session (existing ones continue); it is an availability peer of your database, and it fails closed |

Both are measured from meters the Control Plane emits (Micrometer to
`/actuator/prometheus`, which requires the `metrics:read` permission; see
[Metrics](../reference/metrics.md) for the scrape config):

- `sessionlayer_session_establishment_seconds_*`, a histogram tagged
  `outcome` (`allow`/`deny`/`error`/`cancelled`) and `access_model`.
- `sessionlayer_cert_sign_seconds_*`, a histogram tagged `kind` and
  `outcome`.
- `sessionlayer_ca_signer_total`, a counter tagged `kind`, `source`
  (`request`/`probe`), and `outcome`. Availability is computed over
  `source="request"` only, so the health-probe baseline cannot mask real
  degradation.

> **Note:** keep deny out of your error panels. A deny is policy working;
> `outcome="error"` is the platform failing closed. The shipped dashboard
> separates them, and conflating them buries the 3am signal in policy noise.

## Shipped assets

Both product repositories ship ready-to-use observability assets:

| Asset | Where (repo path) | What it does |
|---|---|---|
| CP SLO alert rules | `ControlPlane/deploy/observability/prometheus-slo-rules.yaml` | pages on both SLO breaches (`SessionEstablishmentP95SloBreach`, `CaSignerAvailabilitySloBreach`), cert-sign latency (`CertSignP95SloBreach`), CA-signer fail-closed spikes (`CaSignerFailClosedSpike`), Authorize error rate over 10% (`SessionEstablishmentErrorSpike`), and no traffic (`NoAuthorizeTraffic`) |
| Grafana dashboard | `ControlPlane/deploy/observability/grafana-slo-dashboard.json` | RED for establishment and CA signer, Gateway session rate/error-ratio and host-verify failures, and the R2DBC pool saturation panel |
| Span-metrics collector config | `Gateway/deploy/observability/otel-collector-spanmetrics.yaml` | turns Gateway/Agent spans into `calls_total` and `duration_milliseconds_bucket` Prometheus series |
| Gateway RED alert rules | `Gateway/deploy/observability/prometheus-gateway-red-rules.yaml` | session error ratio (`GatewaySessionErrorRatioHigh`), host-verify failure spike (`GatewayHostVerifyFailureSpike`), node-connect p95 (`GatewayNodeConnectP95High`), dial-back errors (`AgentDialBackErrorSpike`), and no traffic (`GatewayNoSessionTraffic`) |
| Agent exit-code alert rules | `Agent/deploy/observability/prometheus-agent-alert-rules.yaml` | pages on exit 3, possible clone (`AgentPossibleCloneDetected`), and exit 4, repair needed (`AgentIdentityRepairNeeded`); warns on a sustained exit-1 loop (`AgentCrashLoopingOnTransientExit`); needs `kube-state-metrics` scraping the namespace |

## The Gateway's signals: spans, span-metrics, two gauges

The Gateway and Agent emit OpenTelemetry spans (OTLP push, enabled by
setting `OTEL_EXPORTER_OTLP_ENDPOINT`), carrying IDs, enums, and durations,
never session content. One trace follows a session end to end: the Gateway
starts the root span, the Control Plane's authorize and cert-sign spans
join it, and Agent spans (`agent.dial_back`, `agent.splice`) correlate by
`sessionlayer.session_id`, which is also the join key into the
[audit stream](../admin-guides/audit.md) and the recording.

The shipped collector config derives RED metrics from those spans, keyed by
`span_name` (`gateway.session`, `gateway.outer_leg.auth`,
`gateway.node.connect`, `gateway.host_verify`, `gateway.bridge_setup`) and
`status_code`. Those names are carried verbatim as the `span_name` label
value, so a selector that drops the `gateway.` prefix matches nothing and the
panel built on it stays empty. Fail-closed closes,
including Control-Plane-down at authentication, mark their spans as errors,
so the span-derived error rate reflects real outages; ordinary auth-scan
rejections deliberately do not, preserving the signal.

Two native gauges ride the same outbound OTLP pipeline, with no listener:

- `sessionlayer.gateway.live_sessions`: current live sessions.
- `sessionlayer.gateway.lock_feed_healthy`: 0 or 1, whether the pushed
  deny-list stream is healthy.

## What to page on

Beyond the shipped rules, three signals deserve explicit pages.

Lock feed stale: `sessionlayer.gateway.lock_feed_healthy == 0` for more than
a couple of minutes. While unhealthy, that Gateway is deliberately refusing
what it cannot verify (deny wins): new sessions degrade and break-glass
channels are refused, so this is a user-facing incident even though it is
correct behavior. It self-heals on reconnect; persistent 0 means the CP
gRPC path is down.

Break-glass used: every activation raises a high-priority alert through the
configured alert target and lands as an ERROR-level log plus audit events.
Page on it from your log pipeline or [SIEM forward](../admin-guides/audit.md)
(there is deliberately no Gateway-side metric for it): a break-glass use at
3am should wake a human even when it is legitimate.

Fail-closed fast burn: the shipped `CaSignerFailClosedSpike` rule pages
within minutes when real sign requests start failing closed. A total signer
outage stops all new sessions, and the 30-minute availability window is too
slow to notice it alone. Its Authorize-side sibling
(`SessionEstablishmentErrorSpike`) catches the same class at the decision
layer.

Also watch, as a warn rather than a page: the
[session-limit meters](../admin-guides/session-limits.md)
(`sessionlayer.session.lease.reaped` nonzero in steady state; remember
`sessionlayer.session.lease.live` is fleet-wide, so aggregate with `max`,
never `sum`); the host-verify failure spike rule, which is either a
re-keyed node you forgot to re-enroll or someone impersonating a node
([Nodes](../admin-guides/nodes.md)); and the CP's R2DBC pool utilization
and pending-count panel on the shipped dashboard, which has no alert rule
of its own yet. JVM and file-descriptor metrics are exposed by the
actuator too, but are not on the shipped dashboard.

The HA plane, peer relay and presence, is log-only rather than
metric-derived, the same pattern as break-glass above:
`event=peer_relay_serving`, `event=peer_relay_closed`,
`outcome=node_unreachable reason=...`, and the `presence ...`
ownership-transition lines (standby, heartbeat-failed, release) have no
counter today, so alert on them from your log pipeline, not a metric
([High availability](../admin-guides/high-availability.md)). The
span-derived RED layer above covers session establishment and
`gateway.node.connect`; it is specifically the peer-relay and presence plane
that stops at the log line.

## The Agent

The Agent is outbound-only and exposes no inbound endpoint at all, by
design. Its signals are its exit codes (3 means clone detected, 4 means
repair needed, 2 means self-verification refused, all of which should page,
see the [Agent runbook](agent-runbook.md)), its `SECURITY`/`REPAIR-NEEDED`
log lines, and its OTel spans when export is enabled.

Ship the Agent exit-code alert rules (above) with every fleet. They cover
exit 3, exit 4, and a sustained exit-1 loop. Exit 2 has no shipped rule, so
add one: copy the `AgentPossibleCloneDetected` rule, match `== 2`, and page
on it. That code is the verify-before-run refusal, which means the Agent
declined to run a binary it could not verify. On a
DaemonSet, kubelet accepts only `restartPolicy: Always`, so the container
keeps looping no matter what it exits with, and codes 3 and 4 are otherwise
invisible outside `kubectl describe pod`'s last-terminated state. Alerting
on the exit code, not the restart, is the only way to see them; the rules
need `kube-state-metrics` scraping the namespace to do it.

## Not yet instrumented

The enumerated next increment, per-RPC RED on the Control Plane's gRPC
surface, Gateway channel-open/relay/spool saturation gauges, Agent
dial-back/renew counters, and native `lockfeed.subscribers` /
`breakglass.activation_total` meters on the CP, is not shipped. The
fail-closed events those would count are present in the structured logs
today; ship the logs to your collector and derive from there until native
emission lands.

## Next

- [Gateway runbook](gateway-runbook.md): turning an alert into a diagnosis.
- [Agent runbook](agent-runbook.md): the exit-code contract.
- [Metrics](../reference/metrics.md): the full meter/span reference.
- [Production hardening](../security/hardening.md): the SIEM forward these
  pages assume.
