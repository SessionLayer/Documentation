# Control Plane configuration

Every SessionLayer-specific Control Plane setting lives under the `sessionlayer.*` property
namespace. This page lists all of them — key, type, default, effect — derived from the source and
drift-checked in CI. Set them the standard Spring Boot ways: `application.properties`, a config
file, or environment variables via relaxed binding (`sessionlayer.mtls.server.port` becomes
`SESSIONLAYER_MTLS_SERVER_PORT`).

Durations accept ISO-8601 (`PT10M`, `P90D`) or the simple form (`10m`, `90d`). Database and
migration settings (`spring.r2dbc.*`, `spring.flyway.*`) are standard Spring Boot and covered in
[Install the Control Plane](../installation/control-plane.md).

## Gateway/Agent mTLS plane (`sessionlayer.mtls.*`)

The mutually-authenticated TLS 1.3 gRPC plane the Gateways and Agents talk to.

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.mtls.identity-cert-ttl` | duration | `PT24H` | TTL of the renewable Gateway mTLS identity certificate. Renew-ahead is the Gateway's loop; the Control Plane only issues. |
| `sessionlayer.mtls.enrollment-token-ttl` | duration | `PT10M` | TTL of the single-use Gateway enrollment token. |
| `sessionlayer.mtls.session-signing-token-ttl` | duration | `PT120S` | TTL of the single-use session-signing token minted on allow. |
| `sessionlayer.mtls.host-cert-ttl` | duration | `PT1H` | TTL of the Gateway's outer SSH host certificate (ProxyJump mode); the Gateway re-fetches before expiry. |
| `sessionlayer.mtls.cert-backdate` | duration | `PT2M` | Backdates issued certificates' not-before for clock skew. |
| `sessionlayer.mtls.rpc-timeout` | duration | `PT15S` | Server-side deadline on every mTLS RPC handler — a hung database surfaces as `DEADLINE_EXCEEDED`, not a hung call. |

### gRPC server binding (`sessionlayer.mtls.server.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.mtls.server.enabled` | boolean | `true` | Whether to start the mTLS gRPC server. |
| `sessionlayer.mtls.server.port` | int | `9090` | The gRPC listen port (`0` = ephemeral, used by tests). Deployment examples expose it as `9443`. |
| `sessionlayer.mtls.server.bind-address` | string | `0.0.0.0` | The bind address. The channel is authenticated, so peer identity — not the bind address — is the security boundary. |
| `sessionlayer.mtls.server.hostnames` | list | `localhost,controlplane` | SANs stamped into the Control Plane's gRPC server certificate; Gateways and Agents verify against these. |
| `sessionlayer.mtls.server.max-inbound-message-size` | int (bytes) | `65536` | Max inbound message size. The plane carries only small control messages, so this is deliberately tight. |
| `sessionlayer.mtls.server.max-inbound-metadata-size` | int (bytes) | `16384` | Max inbound header/metadata size. |
| `sessionlayer.mtls.server.max-concurrent-calls-per-connection` | int | `128` | Cap on in-flight calls per connection. |
| `sessionlayer.mtls.server.handler-threads` | int | max(4, 2 × cores) | Bounded handler-executor thread count. |
| `sessionlayer.mtls.server.permit-keep-alive-time` | duration | `PT30S` | Rejects client keepalive pings faster than this (ping-flood guard). |
| `sessionlayer.mtls.server.max-connection-age` | duration | `PT30M` | Recycles a connection after this age. |
| `sessionlayer.mtls.server.max-connection-age-grace` | duration | `PT30S` | Grace for in-flight RPCs when a connection ages out. |
| `sessionlayer.mtls.server.max-connection-idle` | duration | `PT5M` | Closes a connection idle this long. |
| `sessionlayer.mtls.server.drain-timeout` | duration | `PT10S` | Drain deadline on shutdown before a forced close. |

## Agent join (`sessionlayer.agent-join.*`)

The Agent enrollment and renewable-identity plane. See [Install the Agent](../installation/agent.md)
for the join methods themselves.

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.agent-join.identity-cert-ttl` | duration | `PT24H` | TTL of the renewable Agent mTLS identity certificate. |
| `sessionlayer.agent-join.cert-backdate` | duration | `PT2M` | Not-before backdating for clock skew. |
| `sessionlayer.agent-join.join-token-ttl` | duration | `PT10M` | Default single-use join-token TTL. |
| `sessionlayer.agent-join.join-token-max-ttl` | duration | `PT1H` | Ceiling a per-request join-token TTL override is clamped to. |

### OIDC join verification (`sessionlayer.agent-join.oidc.*`)

Verifies a workload OIDC token (Kubernetes ServiceAccount, CI runner, cloud workload identity) with
a positive algorithm allow-list — no shared secret.

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.agent-join.oidc.enabled` | boolean | `false` | Whether the OIDC join method is accepted. |
| `sessionlayer.agent-join.oidc.issuer` | string | — | The workload issuer URL the token's `iss` must equal. |
| `sessionlayer.agent-join.oidc.jwks-uri` | string | — | The issuer's JWKS URI (public signing keys). |
| `sessionlayer.agent-join.oidc.audience` | string | — | The audience the token's `aud` must contain. |
| `sessionlayer.agent-join.oidc.allowed-algs` | list | `RS256,ES256` | Positive JWS algorithm allow-list (`alg:none` and anything unlisted is rejected). |
| `sessionlayer.agent-join.oidc.clock-skew` | duration | `PT60S` | Tolerance for `exp`/`iat`/`nbf`. |
| `sessionlayer.agent-join.oidc.node-claim` | string | `sub` | The verified claim whose value must equal the requested node name. |

### mTLS join verification (`sessionlayer.agent-join.mtls.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.agent-join.mtls.enabled` | boolean | `false` | Whether the operator-mTLS join method is accepted. |
| `sessionlayer.agent-join.mtls.operator-ca-pem` | string (PEM) | — | The operator CA trust anchor(s) an operator certificate must chain to. |

## Authentication surface (`sessionlayer.auth.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.auth.otp-entropy-bytes` | int | `16` | OTP entropy in bytes (16 = 128 bits). |
| `sessionlayer.auth.otp-verify.max` | int | `5` | Fixed-window rate limit on OTP verification: attempts per window. |
| `sessionlayer.auth.otp-verify.window` | duration | `PT1M` | The OTP-verify rate-limit window. |
| `sessionlayer.auth.token-endpoint.max` | int | `30` | Rate limit on the machine token endpoint: requests per window. |
| `sessionlayer.auth.token-endpoint.window` | duration | `PT1M` | The token-endpoint rate-limit window. |
| `sessionlayer.auth.device-poll.max` | int | `60` | Rate limit on device-flow polling: polls per window. |
| `sessionlayer.auth.device-poll.window` | duration | `PT1M` | The device-poll rate-limit window. |
| `sessionlayer.auth.maintenance.enabled` | boolean | `true` | Runs the scheduled cleanup of expired auth artifacts. |
| `sessionlayer.auth.maintenance.cron` | cron | `0 7 * * * *` | Schedule of the auth maintenance sweep (Spring 6-field cron). |

## Authorization (`sessionlayer.authz.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.authz.decision-ttl` | duration | `PT45S` | How long a Gateway may serve per-channel checks from a cached decision context before re-authorizing. The Gateway additionally enforces its own ceiling. |
| `sessionlayer.authz.max-grant-ttl` | duration | `PT1H` | Ceiling applied when computing a grant's expiry (`min` of the rule/JIT TTL and this). |
| `sessionlayer.authz.context-signer-cert-ttl` | duration | `PT24H` | Validity of the decision-context signer leaf, re-minted from the internal mTLS CA at startup. Gateways pin the CA, not the leaf. |

## Lock feed (`sessionlayer.locks.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.locks.heartbeat-interval` | duration | `PT10S` | Liveness beat on the lock-push stream. A Gateway that misses beats marks the feed unhealthy and forces per-channel re-validation. |
| `sessionlayer.locks.stream-buffer-capacity` | int | `512` | Per-connection bounded buffer of pending lock events. On overflow the stream fails so the Gateway reconnects and resyncs — never a silently dropped deny. |

## Session limits (`sessionlayer.session-limits.*`)

Cluster defaults for the three session-limit knobs, plus the lease machinery. Per-identity overrides
live in [session-limit policies](api.md).

> **Warning:** all three defaults are unset out of the box — sessions are unlimited until you set
> them or create a session-limit policy. Production deployments should set at least
> `sessionlayer.session-limits.default-max-concurrent`.

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.session-limits.default-max-concurrent` | int | unset (unlimited) | Cluster-default concurrent-session cap per identity. Set ⇒ reconciled into operator settings at bootstrap and authoritative on each boot. |
| `sessionlayer.session-limits.default-max-session-seconds` | int | unset (none) | Cluster-default max session duration, folded into the grant expiry. |
| `sessionlayer.session-limits.default-idle-timeout-seconds` | int | unset (none) | Cluster-default idle timeout, signed into the decision context; the Gateway applies it tighten-only against its own idle bound. |
| `sessionlayer.session-limits.lease-extension` | duration | `PT15M` (floor `PT60S`) | Server-authoritative window a lease extension re-stamps a live session's lease to. Below-floor values are clamped with a warning. |
| `sessionlayer.session-limits.reaper.enabled` | boolean | `true` | Runs the leaked-lease sweep. |
| `sessionlayer.session-limits.reaper.interval` | duration | `PT1H` | Cadence of the leaked-lease sweep. |
| `sessionlayer.session-limits.reaper.grace` | duration | = lease-extension | How far past a lease's expiry the sweep waits before releasing it. Floored to the lease-extension window so a Gateway's self-heal always outruns the reaper. |
| `sessionlayer.session-limits.gauge-refresh` | duration | `PT1M` | Refresh cadence of the fleet-wide live-lease gauge (see [Metrics](metrics.md)). |

## First-admin bootstrap (`sessionlayer.bootstrap.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.bootstrap.enabled` | boolean | `true` | Runs first-admin bootstrap at startup. Self-disables once a platform admin exists. |
| `sessionlayer.bootstrap.admin-subject` | string | — | An OIDC subject to provision as the initial platform admin. Unset ⇒ a printed-once bootstrap credential is generated instead. |
| `sessionlayer.bootstrap.admin-subject-kind` | string | `user` | The subject kind for the admin subject: `user` or `group`. |

## Break-glass (`sessionlayer.breakglass.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.breakglass.grant-ttl` | duration | `PT1H` | Break-glass grant TTL — emergency access is short by design. |
| `sessionlayer.breakglass.token-ttl` | duration | `PT2M` | Validity of the single-use break-glass token between credential resolution and the authorization call. |
| `sessionlayer.breakglass.offline-code-count` | int | `10` | Default batch size for offline-code issuance. |
| `sessionlayer.breakglass.offline-code-ttl` | duration | `P90D` | Default offline-code lifetime. |
| `sessionlayer.breakglass.offline-code-entropy-bytes` | int | `16` | Offline-code entropy in bytes (16 = 128 bits). |
| `sessionlayer.breakglass.review-sla` | duration | `PT72H` | Advisory deadline for the mandatory post-hoc activation review. An unreviewed activation stays a standing signal — it never auto-clears. |

## API behavior

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.idempotency.ttl` | duration | `PT24H` | How long a recorded `Idempotency-Key` response is replayable; after it a reused key re-executes. |
| `sessionlayer.session.terminate-lock-ttl` | duration | `PT5M` | Lifetime of the identity-scoped lock a session terminate pushes — long enough to reach a briefly disconnected Gateway, short enough that the identity can reconnect afterwards. |

## High availability (`sessionlayer.ha.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.ha.presence-staleness` | duration | `PT30S` | How long a node-owner's last-seen may age before the owner is treated as dead (three missed 10-second Gateway heartbeats). Governs both presence takeover and the routing gate — a stale owner reads as "node offline", failing closed. |

## JIT access (`sessionlayer.jit.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.jit.approval-window` | duration | `PT30M` | How long a request may sit pending before it expires unapproved. |
| `sessionlayer.jit.max-grant-ttl` | duration | `PT8H` | Cluster ceiling on a JIT grant's TTL (`min` of the policy's TTL and this). The grant clock starts at final approval. |
| `sessionlayer.jit.revoke-lock-ttl` | duration | `PT120S` | Bounded lifetime of the strict lock a revoke emits — its only job is tearing down the live session; the revoked state itself blocks re-authorization. |
| `sessionlayer.jit.lookup-timeout` | duration | `PT0.15S` | Bounds the usable-grant lookup Authorize now runs on every connect. A timeout degrades to "no usable grant" (never widens access) instead of a fleet-wide fail-closed deny if the JIT-request table is degraded. |
| `sessionlayer.jit.expiry.enabled` | boolean | `true` | Runs the scheduled sweep that expires overdue requests. |
| `sessionlayer.jit.expiry.interval` | duration | `PT5M` | Cadence of the expiry sweep. |

## Machine tokens (`sessionlayer.machine.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.machine.issuer` | string | `sessionlayer://cp` | The `iss` stamped into (and required on) machine tokens. |
| `sessionlayer.machine.audience` | string | `sessionlayer-cp-api` | The `aud` stamped into machine tokens. |
| `sessionlayer.machine.token-ttl` | duration | `PT5M` | Machine-token lifetime. |
| `sessionlayer.machine.clock-skew` | duration | `PT30S` | Tolerance for token expiry validation. |
| `sessionlayer.machine.max-assertion-age` | duration | `PT5M` | Max age of a presented `private_key_jwt` client assertion. |

## Node lifecycle (`sessionlayer.node.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.node.enrollment-approval-required` | boolean | `false` | When on, a newly registered agentless node starts `pending` and is excluded from targeting until an operator activates it. |

## OIDC relying party (`sessionlayer.oidc.*`)

The user-facing OIDC login (Dashboard and SSH device flow). See
[Authentication](../admin-guides/authentication.md).

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.oidc.enabled` | boolean | `false` | Whether the OIDC relying party is configured. |
| `sessionlayer.oidc.issuer` | string | — | The IdP issuer URL the ID token's `iss` must carry. |
| `sessionlayer.oidc.client-id` | string | — | This Control Plane's OIDC client id (the required `aud`). |
| `sessionlayer.oidc.client-secret` | string | — | The client secret, if the IdP requires one at the token endpoint. |
| `sessionlayer.oidc.redirect-uri` | string | — | The public auth-code callback URL. Its origin is also the single source of the device-flow verification URL — never a request `Host` header. |
| `sessionlayer.oidc.scopes` | list | `openid,profile,email` | Requested scopes. |
| `sessionlayer.oidc.alg-allow-list` | list | `RS256,ES256` | Positive JWS algorithm allow-list (`alg:none` rejected). |
| `sessionlayer.oidc.clock-skew` | duration | `PT60S` | Tolerance for `exp`/`iat`/`nbf`. |
| `sessionlayer.oidc.jwks-cache-ttl` | duration | `PT5M` | JWKS cache TTL (key rotation picked up within this window). |
| `sessionlayer.oidc.groups-claim` | string | `groups` | The claim mapped server-side to RBAC groups — never client-chosen. |
| `sessionlayer.oidc.identity-claim` | string | `email` | The claim used as the resolved identity (falls back to `sub`). |
| `sessionlayer.oidc.state-hmac-key` | string (base64) | per-boot random | HMAC key deriving the PKCE verifier and nonce from `state`. Set a shared value across HA instances so a login begun on one instance completes on another. |

### Device flow (`sessionlayer.oidc.device.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.oidc.device.poll-interval` | duration | `PT5S` | Poll interval advertised to the client. |
| `sessionlayer.oidc.device.expiry` | duration | `PT10M` | How long a device flow stays pending before expiring. |
| `sessionlayer.oidc.device.enforce-source-match` | boolean | `false` | When on, an approving-browser vs SSH source mismatch denies the flow. Off, the mismatch is flagged and audited — legitimate users often approve from a different network. |

## Recordings (`sessionlayer.recording.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.recording.signed-url-ttl` | duration | `PT5M` | Lifetime of the single-object replay/export signed URL. Bytes never proxy through the Control Plane. |
| `sessionlayer.recording.retention.enabled` | boolean | `true` | Runs the scheduled retention prune. |
| `sessionlayer.recording.retention.cron` | cron | `0 0 * * * *` | Schedule of the retention prune (hourly). |

### WORM object store (`sessionlayer.recording.worm.*`)

Defaults match the development MinIO; production overrides these to the real object store and
injects credentials from the environment.

> **Warning:** the default `access-key`/`secret-key` are dev-only MinIO placeholders. In production
> leave `sessionlayer.recording.worm.access-key` blank to use the AWS default credential chain (IAM
> role), and point `sessionlayer.recording.worm.endpoint` at an object-lock-enabled bucket.

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.recording.worm.endpoint` | string (URL) | `http://localhost:9000` | S3 endpoint override (MinIO). |
| `sessionlayer.recording.worm.region` | string | `us-east-1` | AWS region (MinIO ignores it; the SDK requires one). |
| `sessionlayer.recording.worm.bucket` | string | `sessionlayer-recordings` | The WORM bucket encrypted recordings are written to (object lock on). |
| `sessionlayer.recording.worm.access-key` | string | `sessionlayer` (dev) | Static access key. Blank ⇒ the AWS default credential provider chain. |
| `sessionlayer.recording.worm.secret-key` | string | dev placeholder | Static secret key (dev/MinIO only). |
| `sessionlayer.recording.worm.path-style-access` | boolean | `true` | Path-style addressing (required by MinIO; harmless for S3). |
| `sessionlayer.recording.worm.credential-ttl` | duration | `PT120S` | TTL of the presigned single-object upload credential — it need only cover the PUT, never the session. |

## REST security (`sessionlayer.rest-security.*`)

> **Warning:** HTTP Basic is not a first-class scheme. Enabling it is a discouraged escape hatch —
> it emits a startup warning and should sit behind mTLS plus the CIDR allow-list. Prefer the three
> first-class schemes (see the [API reference](api.md)).

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.rest-security.basic-auth.enabled` | boolean | `false` | Enables the HTTP Basic escape hatch. |
| `sessionlayer.rest-security.basic-auth.allowed-cidrs` | list | empty | Source CIDRs the escape hatch is reachable from (deny-only gate). |
| `sessionlayer.rest-security.basic-auth.username` | string | — | The single operator username. |
| `sessionlayer.rest-security.basic-auth.password-hash` | string | — | BCrypt hash of the operator password — never a raw password. |

## Audit (`sessionlayer.audit.*`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.audit.search.default-window` | duration | `P90D` | Time window applied to an audit search with no explicit lower bound (keeps partition pruning effective). |
| `sessionlayer.audit.search.max-window` | duration | `P366D` | Widest explicit search range accepted; wider is a `422`. |
| `sessionlayer.audit.partition-maintenance.enabled` | boolean | `true` | Runs the scheduled audit-partition maintenance. |
| `sessionlayer.audit.partition-maintenance.cron` | cron | `0 0 3 1 * *` | Schedule of partition maintenance (monthly). |

## CA key encryption and cold start

| Key | Type | Default | Effect |
|---|---|---|---|
| `sessionlayer.ca.local.kek-base64` | string (base64) | — | The key-encryption key wrapping local-backend CA private keys. Production must set it (32 bytes, base64). |
| `sessionlayer.ca.local.kek-reference` | string | — | An operator-visible label for the KEK in use. |
| `sessionlayer.ca.local.allow-dev-kek` | boolean | `false` | Allows starting with the built-in dev KEK. Refused otherwise — fail closed. |
| `sessionlayer.coldstart.enabled` | boolean | `true` | Provisions operator settings and the three SSH CAs at startup, exactly once, idempotently. |
| `sessionlayer.coldstart.timeout-seconds` | long | `60` | Bound on cold-start provisioning; a stuck provisioner crashes the boot rather than hanging it. |

> **Warning:** `sessionlayer.ca.local.allow-dev-kek=true` is for development and tests only. With
> the dev KEK anyone holding the database can unwrap your CA keys. Production sets a real
> `sessionlayer.ca.local.kek-base64` — see [Production hardening](../security/hardening.md).

## Next

- [Gateway configuration](config-gateway.md)
- [Agent configuration](config-agent.md)
- [Install the Control Plane](../installation/control-plane.md)
- [Production hardening](../security/hardening.md)
