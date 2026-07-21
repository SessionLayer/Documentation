# Audit events

Everything security-relevant lands in one correlated, append-only audit stream — SSH-session events
and web/admin events side by side, hash-chained for tamper evidence, searchable through the
[API](api.md) and the Dashboard. This page catalogs the event record, the search dimensions, and
every event kind the Control Plane emits, derived from source.

## The event record

| Field | What it holds |
|---|---|
| `id` | The event's UUID (time-ordered). |
| `occurredAt` | When the action happened (RFC 3339). |
| `actor` | The acting identity — a user, a service account, a Gateway id, or `system`. |
| `subject` | What the action targeted (an identity, a resource id, a permission). |
| `action` | The event kind, from the catalog below (for example `lock.create`). |
| `outcome` | The per-action result — `success`, `denied`, `failure`, or an action-specific value. |
| `correlationId` | The join key reconstructing one full path: approve → connect → run → replay. For a session it is the JIT request id, the break-glass activation id, or the session id. |
| `sessionId` / `nodeId` | The session and node the event belongs to, where applicable. |
| `nodeLabels` | Snapshot of the node's labels at event time (so label searches match history, not current state). |
| `sourceIp` | The client source IP, where applicable. |
| `accessModel` | `standing`, `jit`, or `breakglass`, where applicable. |
| `capabilities` | The session's granted capability set, where applicable. |
| `detail` | A small, secret-free key/value map of action-specific context; config changes carry before/after state. |

Two more columns exist for integrity, not searching: each row carries the previous row's hash and
its own record hash, forming a verifiable chain. The stream is append-only — a database trigger
rejects updates and deletes, and searching never mutates it.

## Searching and alerting

You can filter on every dimension an operator plausibly pivots on: `actor`, `subject`, `action`,
`outcome`, `sessionId`, `nodeId`, node label (`key=value`, repeatable, ANDed), `sourceIp`,
`capability`, `accessModel`, a time range, and `correlationId`. See the
[API reference](api.md) for the exact query parameters and [Audit](../admin-guides/audit.md) for
worked searches. Search results are filtered to the caller's RBAC scope.

For alerting, forward the stream to your SIEM through the pluggable forwarder seam (below) and key
alerts on `action` + `outcome`. Two events are designed as high-priority signals:

> **Warning:** alert on `breakglass.authenticated` (someone used the emergency path — the alert
> fires on use, not after review) and `agent.identity.clone_detected` (two processes presented the
> same Agent identity; the platform auto-locks it and does not auto-clear).

`gateway.renew.generation_mismatch` and `agent.renew.generation_mismatch` are the same
clone-detection signal at renewal time, and an unreviewed break-glass activation remains visible via
`reviewStatus=pending` on the activations API.

## Event catalog

### Enrollment and component identity

| Action | Emitted when |
|---|---|
| `gateway.enroll` | A Gateway enrolled with a bootstrap token and received its mTLS identity. |
| `gateway.renew` | A Gateway renewed its identity certificate. |
| `gateway.renew.generation_mismatch` | A Gateway renewal presented a stale generation counter — clone signal. |
| `gateway.server_cert.issue` | The Gateway's agent-facing TLS server certificate was issued. |
| `gateway.host_cert.sign` | The Gateway's outer SSH host certificate was signed (ProxyJump mode). |
| `agent.enroll` | An Agent joined and received its mTLS identity. |
| `agent.renew` | An Agent renewed its identity certificate. |
| `agent.renew.generation_mismatch` | An Agent renewal presented a stale generation counter — clone signal. |
| `agent.identity.clone_detected` | Clone detection fired and the identity was auto-locked. |
| `agent.revoke` | An Agent credential was revoked (node removal). |
| `join_token.issue` | A join token was issued. |
| `join_token.revoke` | An unconsumed join token was revoked. |
| `bootstrap.provision` | The config-named first admin was provisioned at startup. |
| `bootstrap.claim` | The printed-once bootstrap credential was claimed. |

### Authentication

| Action | Emitted when |
|---|---|
| `oidc.login` | A browser OIDC login completed (Dashboard or device-flow approval). |
| `device.begin` | An SSH device flow started. |
| `device.approve` | A user approved a device flow at the verification page. |
| `otp.issue` | An admin issued a single-use OTP. |
| `otp.verify` | An OTP was presented at SSH authentication. |
| `pin.create` | An admin pinned a key fingerprint to an identity. |
| `pin.resolve` | A pinned key authenticated an SSH connection. |
| `pin.revoke` | A pin was revoked. |
| `usercert.resolve` | A user SSH certificate was presented and resolved. |
| `machine.token.issue` | A machine consumer exchanged a credential for a bearer token. |
| `machine.credential.issue` | A service-account credential was issued. |
| `machine.credential.revoke` | A service-account credential was revoked. |

### Authorization and sessions

| Action | Emitted when |
|---|---|
| `authz.decision` | A connect-time data-plane decision was made (`success` on allow, `denied` on deny). Allow events carry the full snapshot: node, labels, capabilities, access model, source IP, correlation id. |
| `platform.authz` | A platform-RBAC permission check ran (`success`/`denied`; the permission is the subject). |
| `session.sign` | A session certificate was signed for an allowed connection. |
| `session.end` | A session ended (with its end reason in the detail). |
| `session.terminate` | An operator terminated a session. |

### JIT access

| Action | Emitted when |
|---|---|
| `jit.requested` | A request was submitted (`denied` outcome when no policy matches). |
| `jit.pending` | The request entered the approval chain. |
| `jit.approve` | One approval level was recorded (`denied` outcome on a refused approval attempt, for example self-approval). |
| `jit.approved` | All levels approved — the grant clock started. |
| `jit.denied` | The request was denied (terminal). |
| `jit.expired` | The request expired unapproved. |
| `jit.activated` | The grant was first used to connect. |
| `jit.revoked` | An active grant was revoked (a teardown lock is also pushed). |

### Break-glass

| Action | Emitted when |
|---|---|
| `breakglass.credential.register` | A FIDO2 break-glass key was registered. |
| `breakglass.credential.revoke` | A break-glass credential was revoked. |
| `breakglass.offline_code.issue` | A batch of offline codes was issued. |
| `breakglass.resolve` | A break-glass credential was presented at SSH authentication. |
| `breakglass.authenticated` | Break-glass authentication succeeded — the high-priority alert event. |
| `breakglass.activation` | The activation record was created on connect (strict recording forced). |
| `breakglass.review` | The mandatory post-hoc review was recorded. |

### Locks and nodes

| Action | Emitted when |
|---|---|
| `lock.create` | A lock was created and pushed to every Gateway. |
| `lock.release` | A lock was released. |
| `node.register` | An agentless node was registered. |
| `node.activate` | A pending node was activated. |
| `node.quarantine` | A node was quarantined (a lock, deny wins). |
| `node.quarantine.release` | A quarantine was lifted. |
| `node.remove` | A node was deregistered (agent credential revoked). |

### Recordings

| Action | Emitted when |
|---|---|
| `recording.begin` | A Gateway registered a session recording. |
| `recording.upload` | An upload credential was issued at session end. |
| `recording.finalize` | The recording was finalized (hash-chain head sealed). |
| `recording.replay` | An admin was issued a replay signed URL — access to recordings is itself audited. |
| `recording.export` | An admin was issued an export signed URL. |
| `recording.legal_hold` | A legal hold was placed or released. |
| `recording.delete` | A governance delete erased the encrypted object. |
| `recording.prune` | Retention pruned an expired recording. |

### Configuration changes

Every config write is audited with before/after state in the detail. The pattern is
`<resource>.create`, `<resource>.update`, `<resource>.delete` for: `rule`, `role`, `role_binding`,
`ca` (plus `ca.rotate`), `service_account`, `node_policy`, `capability_def`, `jit_policy`,
`breakglass_policy`, and `session-limit-policy` (note: that last prefix is hyphenated, unlike the
underscored config prefixes).

### Audit access

Reading the audit stream is itself an event: `audit.search` and `audit.get`, with the query
dimensions in the detail.

## Where events go

Two pluggable seams control audit storage and shipping (see
[Audit](../admin-guides/audit.md) for operations):

- **The store** is the primary of record — append and read only. The default backend is Postgres
  with the hash chain; the seam exists so a deployment can swap in another tamper-evident store.
- **The forwarder** ships each committed event off-box (SIEM, S3, syslog, webhook). Forwarding is
  best-effort by design: a forward failure is logged loudly but never rolls back the audited action.
  The reference implementation emits a structured log line; production deployments plug in a real
  connector.

## Next

- [Audit](../admin-guides/audit.md)
- [API reference](api.md)
- [Session recording](../admin-guides/session-recording.md)
- [Metrics](metrics.md)
