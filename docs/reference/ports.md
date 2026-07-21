# Ports

The complete network matrix: every listener and every dial in a SessionLayer deployment, with the
configuration key that moves each one. Defaults are derived from the source; nothing here is
implied or optional-but-undocumented.

## Listeners

| Component | Default | Protocol | Who connects | Moved by |
|---|---|---|---|---|
| Control Plane REST API | `8080` | HTTP (terminate TLS in front) | Browsers via the Dashboard, admins, automation | `server.port` (Spring) |
| Control Plane gRPC | `9090` | gRPC over mutual TLS 1.3 | Gateways and Agents | `sessionlayer.mtls.server.port` |
| Gateway SSH front door | off (empty) | SSH | Stock `ssh`/`sftp`/`scp` clients | `ssh.listen_addr` — typically `0.0.0.0:22`, or a high port behind a Service/LB |
| Gateway agent transport | off (empty); dev `9444` | WebSocket over mutual TLS 1.3 | Agents dialing out; peer Gateways for the byte relay | `ssh.agent.listen_addr` |
| Gateway readiness | off (empty) | HTTP (`GET /readyz`) | Load balancer / orchestrator probes | `ha.drain.readyz_addr` |
| node `sshd` | `22` | SSH | The Gateway (agentless) or the local Agent (splice) | the node's own sshd config |
| Dashboard | `8080` (container) | HTTP (terminate TLS in front) | Browsers, via an https-terminating proxy | the proxy/Service in front |
| Postgres | `5432` | Postgres | Control Plane only | your database deployment |
| Object store (S3/MinIO) | `9000` (dev MinIO; console `9001`) | HTTPS (S3 API) | Gateway uploads; browsers replay/export via signed URLs | `sessionlayer.recording.worm.endpoint` |
| Vault (optional CA backend) | `8200` (dev) | HTTPS | Control Plane only | your Vault deployment |
| NATS (optional, HA signals) | `4222` (client), `8222` (monitoring, dev) | NATS | Gateways | `ha.coordination.url` |
| OTel collector (optional) | `4317` (OTLP gRPC); Prometheus exporter `9464` | gRPC / HTTP | All three components export; Prometheus scrapes | `OTEL_EXPORTER_OTLP_ENDPOINT`; collector config |

> **Note:** the Control Plane binds its gRPC plane on `9090` by default, while the Gateway's
> `cp_mtls_endpoint` and the Agent's `--cp-endpoint` default to port `9443`, which the deployment
> examples expose. Make them agree in your deployment: either set
> `sessionlayer.mtls.server.port=9443` (or map a Service port `9443` onto the container's `9090`),
> or point the Gateway and Agent endpoints at `9090` explicitly.

## Dials (who talks to whom)

| From | To | Port | Purpose | Configured by |
|---|---|---|---|---|
| User's `ssh` client | Gateway | `22` (as deployed) | The SSH session | the user's ssh config; [SSH access](../user-guide/ssh-access.md) |
| Gateway | Control Plane | `9443` (default endpoint) | Enroll/renew identity, authenticate credentials, authorize sessions, sign certificates, stream locks, presence, recording lifecycle | `cp_mtls_endpoint` |
| Agent | Control Plane | `9443` (default endpoint) | Join, renew the mTLS identity | `--cp-endpoint` |
| Agent | Gateway | `9444` (as deployed) | Outbound control channel + per-session dial-back — the node needs no inbound holes | `--gateway-endpoint` (a `wss://` URL) |
| Agent | node's local `sshd` | `127.0.0.1:22` | Splices each dialed-back session to sshd — loopback only, enforced | `--splice-addr` |
| Gateway | node `sshd` | `22` (per node) | Agentless direct dial | the node's registered address |
| Gateway (ingress) | Gateway (owner) | agent transport port | Direct peer byte relay for sessions landing on a non-owner Gateway (HA); bytes never cross the signal bus | `ha.peer_relay_advertise_addr` (empty derives from the agent transport) |
| Gateway | NATS | `4222` | Dial-back signaling in HA with the NATS backend — signals only | `ha.coordination.backend` = `nats`, `ha.coordination.url` |
| Gateway | Object store | `9000`/`443` | Uploads the encrypted recording directly with a short-lived credential — bytes never proxy through the Control Plane | presigned URL from the Control Plane |
| Control Plane | Postgres | `5432` | The single source of truth | `spring.r2dbc.*` / `spring.flyway.*` |
| Control Plane | Object store | `9000`/`443` | Presigns upload/replay/export URLs; retention | `sessionlayer.recording.worm.endpoint` |
| Control Plane | Vault | `8200` | SSH certificate signing with the `vault` CA backend | the CA configuration (see [Certificate authorities](../admin-guides/certificate-authorities.md)) |
| Control Plane | Your IdP | `443` | OIDC issuer metadata, JWKS, token endpoint | `sessionlayer.oidc.issuer` |
| Browser | Control Plane | `443` (via proxy) | The REST API, OIDC login, device-flow verification page | your proxy in front of `8080` |
| Browser | Object store | `443` | Recording replay/export via the signed URL (decrypted client-side with the customer recording key) | signed URL |
| All components | OTel collector | `4317` | Trace export (only when configured) | `OTEL_EXPORTER_OTLP_ENDPOINT` |

## Direction summary for firewalls

- **Nodes running an Agent need no inbound rules at all.** The Agent dials out to Gateways; sessions
  arrive over that outbound channel and splice to loopback `sshd`.
- **Agentless nodes** need inbound `22` from the Gateways — plus, if you rely on native SSH (rather
  than console/serial) as your platform-independent recovery path (see the
  [FAQ](../faq.md) and [Break-glass access](../admin-guides/break-glass.md)), from your
  admin/recovery network.
- **The Gateway** accepts SSH from users and the agent transport from Agents/peer Gateways; it dials
  the Control Plane, nodes, the object store, and (in HA with NATS) the signal bus.
- **The Control Plane** accepts REST (`8080`) and gRPC (`9090` default) only; it dials Postgres, the
  object store, Vault, and your IdP. Restrict its egress to exactly those (see
  [Production hardening](../security/hardening.md)).
- Sessions through the platform always transit a Gateway — users hold no platform credential that
  reaches a node directly. Whether operators keep a direct native-SSH path open besides is the
  recovery trade-off above.

## Next

- [Requirements](../installation/requirements.md)
- [Gateway configuration](config-gateway.md)
- [Control Plane configuration](config-control-plane.md)
- [High availability](../admin-guides/high-availability.md)
