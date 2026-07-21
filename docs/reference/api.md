# API

The Control Plane exposes a contract-first REST API — the same surface the Dashboard uses. The
authoritative contract is `contracts/openapi/openapi.yaml` in the ControlPlane-API repository
(OpenAPI 3.1); this page is drift-checked against it in CI, both directions. Server interfaces and
the Dashboard's typed client are generated from that contract, so what you read here is what the
server implements.

## Conventions

### Base URL and versioning

Every path is rooted at your Control Plane URL plus the URI major version: `https://cp.example.com/v1/...`.
The URI major version is `v1`. Within a major version all changes are additive — a new optional field or
path never breaks an existing client. Breaking changes would require a new URI major version; see
`contracts/VERSIONING.md` for the full policy, including the N-1 compatibility window the internal
protocols follow.

### Authentication

The API accepts three first-class authentication schemes. HTTP Basic is deliberately not one of them
(a discouraged escape hatch exists behind `sessionlayer.rest-security.basic-auth.*` — see
[Control Plane configuration](config-control-plane.md)).

| Scheme | How it works | Use it for |
|---|---|---|
| OIDC bearer | `Authorization: Bearer <JWT>` — an ID/JWT token validated by the Control Plane against your IdP | Humans and the Dashboard |
| Client credentials | OAuth 2.0 client-credentials at `POST /v1/oauth2/token`, preferring a `private_key_jwt` assertion or an mTLS client certificate over a static secret | Machine consumers (automation, CI) |
| Mutual TLS | A client certificate on the TLS connection | Machine consumers and internal callers |

Every request then passes platform RBAC: the operation's required permission (from the closed
vocabulary below) must be granted to the caller through a role binding. Three operations sit outside
the bearer/mTLS gate by design: the meta probes (public), the device-flow poll (the device code is
the credential), and the token endpoint (the client authenticates itself there).

### Pagination

The config and audit collections are cursor-paginated. Pass `limit` (1–200, default 50; the server
clamps to its maximum) and follow the response's `nextCursor` by passing it back as `cursor`.
Cursors are opaque and forward-only; an unrecognized cursor is a `400`. A page envelope looks like:

```json
{
  "items": [],
  "nextCursor": "b3BhcXVl"
}
```

A `null` or absent `nextCursor` means you have the last page. This applies to rules, roles, role
bindings, CAs, service accounts, node policies, capability definitions, JIT/break-glass/session-limit
policies, sessions, recordings, and audit events — the endpoints whose tables below say
"cursor-paginated".

The bounded runtime listings return the full set in one response instead, in a resource-named
array with no cursor: `pins`, `locks`, `joinTokens`, `nodes`, `jitRequests`, and the break-glass
`credentials`, `offlineCodes`, and `activations`. So `GET /v1/nodes` yields `{"nodes": [...]}` —
pipe it through `jq '.nodes[]'`, not `.items[]`.

### Idempotency

Mutating operations accept an optional `Idempotency-Key` header. A retry with the same key, method,
and path returns the original response without repeating the side effect; reusing a key with a
different request body is a `422`. Keys are retained for a bounded TTL
(`sessionlayer.idempotency.ttl`, default 24 hours) — after that a reused key re-executes.

### Errors

Errors are RFC 9457 problem details with media type `application/problem+json`:

```json
{
  "type": "about:blank",
  "title": "Forbidden",
  "status": 403,
  "detail": "Missing permission rbac:write."
}
```

Status codes follow a consistent pattern: `400` malformed input, `403` missing permission, `404` not
found, `409` conflict (duplicate, stale version, or a refused state transition), `422` semantically
invalid configuration rejected before commit.

### Optimistic concurrency

Config resources carry a read-only `version` counter. Every update (`PUT`) requires the current
`version` in the request body and fails with `409` when it is stale, so two admins can never silently
overwrite each other. Read the resource, edit the fields, and send the `version` you read.

### Config vs runtime resources

Config resources (rules, roles, role bindings, CAs, service accounts, node policies, capability
definitions, JIT/break-glass/session-limit policies) carry an `origin` provenance label (`api`, `ui`,
or `default`) plus the `version` counter, and validate input pre-commit — invalid configuration is a
`422`, never a stored bad row. Runtime resources (nodes, sessions, locks, JIT requests, join tokens,
credentials, recordings, audit events) reflect live state and carry neither.

### Closed vocabularies

Three enums appear throughout:

- **Capabilities** (what a session may do): `shell`, `exec`, `sftp`, `scp`, `port_forward_local`,
  `port_forward_remote`, `agent_forward`, `x11`.
- **Platform permissions** (what an admin may call): `rbac:read`, `rbac:write`, `node:enroll`,
  `node:quarantine`, `node:remove`, `ca:manage`, `ca:rotate`, `request:approve`, `recording:replay`,
  `recording:export`, `recording:delete`, `audit:read`, `user:manage`, `settings:write`, `lock:read`,
  `lock:write`, `breakglass:manage`.
- **Access models**: `standing`, `jit`, `breakglass`.

## Meta

Unauthenticated probes for load balancers, orchestrators, and version discovery. They disclose no
identity, node, or policy information.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/healthz` | Liveness/readiness probe | `200` healthy, `503` not ready |
| `GET /v1/version` | Component and protocol version metadata | Public |

`GET /v1/version` returns the component name, its SemVer build version, and the protocol version
ranges it speaks on the Control Plane–Gateway gRPC plane and the Agent–Gateway wire protocol —
useful when planning a mixed-version upgrade (see [Upgrades](../operations/upgrades.md)).

## Machine tokens

The OAuth 2.0 client-credentials endpoint for machine consumers.

| Operation | What it does | Notes |
|---|---|---|
| `POST /v1/oauth2/token` | Exchange a client credential for a short-lived bearer token | Client authenticates itself; not behind the API gate |

Send `grant_type=client_credentials` with either a `client_assertion` (a signed RFC 7523 JWT,
`client_assertion_type` set to `urn:ietf:params:oauth:client-assertion-type:jwt-bearer`) or an mTLS
client certificate. A static `client_secret` is accepted but discouraged. The response carries
`access_token`, `token_type`, and `expires_in`; the token resolves to a first-class RBAC principal
defined by a [service account](#service-accounts).

## OTPs and pins

Admin-issued SSH authentication shortcuts (see [Authentication](../admin-guides/authentication.md)).

| Operation | What it does | Notes |
|---|---|---|
| `POST /v1/otp` | Issue a single-use, short-TTL OTP bound to an identity | `user:manage`; raw OTP returned once |
| `GET /v1/pins` | List pins for an identity | Requires the `identity` query parameter |
| `POST /v1/pins` | Pin a public-key fingerprint to an identity | TTL capped at the authorization TTL |
| `DELETE /v1/pins/{pinId}` | Revoke a pin | Idempotent |

An issued OTP returns `otpId`, the raw `otp` (exactly once — only its hash is stored; deliver it
out-of-band), and `expiresAt`. A pin binds a key `fingerprint` to `{identity, sourceCidr, principals}`
with a TTL; source IP is a deny-only reducer — it can narrow access, never grant it.

## Service-account credentials

Runtime credentials for a [service account](#service-accounts) definition.

| Operation | What it does | Notes |
|---|---|---|
| `POST /v1/service-accounts/{serviceAccountId}/credentials` | Issue a rotatable machine credential | `private_key_jwt` key/JWKS ref, mTLS cert fingerprint, or (discouraged) a generated secret returned once |
| `DELETE /v1/service-accounts/{serviceAccountId}/credentials/{credentialId}` | Revoke a credential | Takes effect immediately |

Credentials are stored hashed or by reference — the API never returns stored secret material.

## Device flow

The OIDC device-authorization flow (RFC 8628) that backs SSH logins when certificate, pin, and OTP
authentication do not apply. `POST /v1/auth/device` is called by a Gateway over mTLS;
`POST /v1/auth/device/poll` authenticates by the device code itself and is rate-limited.

| Operation | What it does | Notes |
|---|---|---|
| `POST /v1/auth/device` | Begin a device flow bound to the SSH source context | mTLS (Gateway) |
| `POST /v1/auth/device/poll` | Poll a device flow for completion | Public; the device code is the credential |

Polling returns `pending`, then `authorized` with the resolved identity (plus a
`sourceContextMatch` flag comparing the approving browser to the SSH source), or `denied`/`expired`.

## Locks

The incident-response deny primitive. A lock blocks new sessions and tears down matching live ones on
every Gateway; deny always wins over any allow, grant, or break-glass. See
[Locks](../admin-guides/locks.md).

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/locks` | List active (unexpired) locks | `lock:read` |
| `POST /v1/locks` | Create and push a lock | `lock:write`; fleet-wide requires explicit `all: true` |
| `DELETE /v1/locks/{lockId}` | Release a lock | `lock:write`; never resurrects a torn-down session |

A lock's `target` selects any combination of `identities`, `groups`, `nodeIds`, `principals`, and
`nodeLabels`, or `all: true` for fleet-wide; an empty or unrecognized target is rejected at ingest.
`mode` is `strict` (tear down matching live sessions and block new ones) or `best_effort` (block new
issuance only). An optional `ttlSeconds` auto-expires the lock.

## Join tokens

Single-use, short-TTL, node-scoped enrollment credentials for Agent nodes. See
[Nodes](../admin-guides/nodes.md). All operations require `node:enroll`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/join-tokens` | List unconsumed, unexpired join tokens | Metadata only — never the raw token |
| `POST /v1/join-tokens` | Issue a join token for a `nodeName` | Raw token returned exactly once |
| `DELETE /v1/join-tokens/{joinTokenId}` | Revoke an unconsumed token | Idempotent |

Issuance is a pure API operation, so an autoscaler or configuration management can re-provision an
Agent without a human. Revoking an already-consumed token has no effect on the identity it produced —
revoking an issued identity is a [lock](#locks).

## Nodes

Node lifecycle: agentless registration, listing, quarantine, and removal. Agent nodes join via
[join tokens](#join-tokens) instead of `POST /v1/nodes`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/nodes` | List enrolled nodes with connectivity, status, health | `node:enroll`; removed nodes excluded by default |
| `POST /v1/nodes` | Register an agentless node | `node:enroll`; host identity material required — never TOFU |
| `GET /v1/nodes/{nodeId}` | Get one node | `node:enroll` |
| `DELETE /v1/nodes/{nodeId}` | Remove (deregister) a node | `node:remove`; revokes an agent node's credential |
| `POST /v1/nodes/{nodeId}/quarantine` | Quarantine a node | `node:quarantine`; expressed as a lock, deny wins |
| `DELETE /v1/nodes/{nodeId}/quarantine` | Release a node from quarantine | `node:quarantine` |

Registration takes the node's `name`, dial `address`, `labels`, and its host identity — a
host-CA-signed `hostCertificate` or an explicitly pinned `pinnedHostKey` (at least one). When
enrollment approval is required (`sessionlayer.node.enrollment-approval-required`), a new node starts
`pending` and is excluded from targeting until activated. Quarantine takes a `reason` and an
`existingSessions` policy — `kill` (default) tears live sessions down at once, `drain` lets them
finish but refuses new channels. Removal is soft (status `removed`, history preserved) and, for an
agent node, flips its identity off `active` and pushes a covering lock so a stale clone stays
unusable.

## JIT requests

Just-in-time access requests and the approval chain. Submitting is open to any authenticated
principal; approve/deny/revoke require `request:approve`. See [JIT access](../admin-guides/jit-access.md).

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/jit-requests` | List JIT requests | Filter by `state`, `requester` |
| `POST /v1/jit-requests` | Submit a request for access to a node | Requester is the authenticated caller, never a body field |
| `GET /v1/jit-requests/{jitRequestId}` | Get one request | |
| `POST /v1/jit-requests/{jitRequestId}/approve` | Approve the next level | Self-approval impossible; each approver acts at most once |
| `POST /v1/jit-requests/{jitRequestId}/deny` | Deny a pending request (terminal) | The denier can never be the requester |
| `POST /v1/jit-requests/{jitRequestId}/revoke` | Revoke an approved/active grant | Also tears down live sessions via a lock |

A submission names the `targetNodeId`, the `principal` (Linux login), requested `capabilities`, and a
`reason`. The matching JIT policy's approval chain is snapshotted onto the request; a zero-level
chain auto-approves (a lock still denies on use). The resource tracks `state`, per-level `approvals`,
the `approvalDeadline`, and — once fully approved — `grantExpiresAt`, when the grant clock started at
final approval. Approve/deny/revoke accept an optional body with a `reason`.

## Break-glass

Credential management and activation review for the emergency access path. All operations require
`breakglass:manage`. See [Break-glass access](../admin-guides/break-glass.md).

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/breakglass/credentials` | List registered FIDO2 credentials | Public metadata only |
| `POST /v1/breakglass/credentials` | Register a FIDO2 `sk-ecdsa` public key | Public material + fingerprint stored; an admin vouches for the key |
| `DELETE /v1/breakglass/credentials/{credentialId}` | Revoke a credential | Soft, idempotent |
| `GET /v1/breakglass/offline-codes` | List offline-code metadata | Never the raw codes |
| `POST /v1/breakglass/offline-codes` | Issue a batch of single-use offline codes | Raw codes returned exactly once |
| `GET /v1/breakglass/activations` | List activations | Filter by `reviewStatus` (`pending`/`reviewed`) |
| `POST /v1/breakglass/activations/{activationId}/review` | Record the mandatory post-hoc review | An unreviewed activation is a standing signal |

A registered credential binds a `publicKey` to an `identity`, `allowedPrincipals`, optional `nodeIds`
scope, and an expiry. Offline-code issuance takes an `identity`, `allowedPrincipals`, optional
`nodeIds`/`sourceCidr`, a `count`, and a TTL. An activation records who used break-glass, from where,
against what, the fired alert reference, and its review status.

## Rules

Data-plane RBAC — the typed allow/deny grants that decide who may SSH where. Reads require
`rbac:read`, writes `rbac:write`. See [RBAC](../admin-guides/rbac.md).

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/rules` | List rules | Cursor-paginated |
| `POST /v1/rules` | Create a rule | `422` on invalid config, pre-commit |
| `GET /v1/rules/{ruleId}` | Get one rule | |
| `PUT /v1/rules/{ruleId}` | Update a rule | `name` immutable; `version` required |
| `DELETE /v1/rules/{ruleId}` | Delete a rule | Idempotent |

A rule has an `identitySelector` and `nodeLabelSelector` (shape-validated selector objects), an
optional `sourceIpCondition` (deny-only), the granted `principals`, a `ttlSeconds` bound, the granted
`capabilities`, and an `effect` of `allow` or `deny`. Deny overrides allow. A deny that must persist
is a rule; "deny now and keep it" during an incident is a [lock](#locks).

## Roles

Platform RBAC roles — named sets of the closed platform-permission vocabulary. Reads require
`rbac:read`, writes `rbac:write`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/roles` | List roles | Cursor-paginated |
| `POST /v1/roles` | Create a role | Out-of-vocabulary permission is a `422` |
| `GET /v1/roles/{roleId}` | Get one role | |
| `PUT /v1/roles/{roleId}` | Update permissions/description | `name` immutable; `version` required |
| `DELETE /v1/roles/{roleId}` | Delete a role and cascade its bindings | Idempotent |

## Role bindings

Bind a subject (user or group) to a role, optionally scoped. Reads require `rbac:read`, writes
`rbac:write`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/role-bindings` | List role bindings | Cursor-paginated |
| `POST /v1/role-bindings` | Bind a subject to a role | Duplicate `(role, subjectKind, subject)` is a `409` |
| `GET /v1/role-bindings/{bindingId}` | Get one binding | |
| `PUT /v1/role-bindings/{bindingId}` | Replace a binding's scope | Subject and role immutable — rebind by delete + create |
| `DELETE /v1/role-bindings/{bindingId}` | Delete a binding | Idempotent |

A binding's optional `scope` narrows where the role applies — used to scope `recording:replay`,
`recording:export`, and `audit:read` grants by node label, user, or time.

## Certificate authorities

CA configuration and rotation for the three SSH CAs (user, session, host). Requires `ca:manage`;
rotation requires `ca:rotate`. The API never exposes private key material. See
[Certificate authorities](../admin-guides/certificate-authorities.md).

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/cas` | List CA configurations | Public/config material only |
| `POST /v1/cas` | Register a CA configuration | Algorithm/backend mismatch is a `422` |
| `GET /v1/cas/{caId}` | Get one CA configuration | |
| `PUT /v1/cas/{caId}` | Update backend/keyReference/algorithm | `name`, `caKind` immutable; `version` required |
| `DELETE /v1/cas/{caId}` | Delete a CA configuration | Deleting the sole `active` CA of a kind is a `409` |
| `POST /v1/cas/{caId}/rotate` | Rotate the CA's key | Old key stays trusted through the overlap window |

A configuration names the `caKind` (`user`/`session`/`host`), the `backend` (`local`, `aws_kms`,
`azure_keyvault`, `vault`), a `keyReference` (a reference — a value that looks like private material
is rejected), and the `algorithm` (`ecdsa-p256`, `ecdsa-p384`, `ed25519`, `rsa-2048`, `rsa-4096`;
`ed25519` is unavailable on `azure_keyvault`). `rotationState` (`incoming`/`active`/`outgoing`/`expired`)
is managed by the rotation state machine and read-only here.

## Service accounts

Machine-consumer definitions. Requires `user:manage`. Issued runtime credentials live under
[service-account credentials](#service-account-credentials); this resource never returns a secret.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/service-accounts` | List service accounts | Cursor-paginated |
| `POST /v1/service-accounts` | Create a definition | Bad `keyReference`/`tokenTtlSeconds` is a `422` |
| `GET /v1/service-accounts/{serviceAccountId}` | Get one definition | |
| `PUT /v1/service-accounts/{serviceAccountId}` | Update mutable fields | `name` immutable; `version` required |
| `DELETE /v1/service-accounts/{serviceAccountId}` | Delete a definition | Issued credentials revoked separately |

A definition sets the `authMethod` (`private_key_jwt`, `mtls`, or discouraged `client_secret`), a
`keyReference`, and the issued-token TTL (`tokenTtlSeconds`).

## Node policies

Desired node shape: labels, connector kind, and declared host-trust references. Requires
`settings:write`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/node-policies` | List node policies | Cursor-paginated |
| `POST /v1/node-policies` | Create a node policy | `422` on a bad connector kind or trust ref |
| `GET /v1/node-policies/{nodePolicyId}` | Get one policy | |
| `PUT /v1/node-policies/{nodePolicyId}` | Update mutable fields | `name` immutable; `version` required |
| `DELETE /v1/node-policies/{nodePolicyId}` | Delete a policy | Idempotent |

Fields: `desiredLabels` (a label map), `connectorKind` (`agent` or `agentless`), and `hostPinRef` /
`hostCaRef` host-trust references (references only — private material is rejected).

## Capability definitions

The catalog of requestable capabilities. Requires `settings:write`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/capability-defs` | List the capability catalog | Cursor-paginated |
| `POST /v1/capability-defs` | Add a capability | Outside the closed set is a `422`; duplicate is a `409` |
| `GET /v1/capability-defs/{capabilityDefId}` | Get one definition | |
| `PUT /v1/capability-defs/{capabilityDefId}` | Update the description | `name` immutable; `version` required |
| `DELETE /v1/capability-defs/{capabilityDefId}` | Delete a definition | Idempotent |

## JIT policies

What may be requested just-in-time, with what ceiling, and who must approve. Requires
`settings:write`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/jit-policies` | List JIT policies | Cursor-paginated |
| `POST /v1/jit-policies` | Create a JIT policy | Chain longer than 3 levels is a `422` |
| `GET /v1/jit-policies/{jitPolicyId}` | Get one policy | |
| `PUT /v1/jit-policies/{jitPolicyId}` | Update mutable fields | `name` immutable; `version` required |
| `DELETE /v1/jit-policies/{jitPolicyId}` | Delete a policy | Idempotent |

A policy defines the requestable `targetSelector`, the grantable `capabilities`, `maxTtlSeconds`, and
an `approvalChain` of 0–3 levels (each level naming who may approve).

## Break-glass policies

How break-glass behaves when used. Requires `breakglass:manage`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/breakglass-policies` | List break-glass policies | Cursor-paginated |
| `POST /v1/breakglass-policies` | Create a policy | Empty `alertTarget` or bad `authPath` is a `422` |
| `GET /v1/breakglass-policies/{breakglassPolicyId}` | Get one policy | |
| `PUT /v1/breakglass-policies/{breakglassPolicyId}` | Update mutable fields | `name` immutable; `version` required |
| `DELETE /v1/breakglass-policies/{breakglassPolicyId}` | Delete a policy | Idempotent |

Fields: `recordingStrict` (strict recording is always forced for break-glass sessions),
`alertTarget` (where the on-use alert fires), `reviewRequired`, and `authPath` (`fido2` or
`offline_code` — the IdP-independent authentication paths).

## Session-limit policies

Per-identity overrides for the three session-limit knobs: concurrent-session cap, max session
duration, and idle timeout. Reads require `rbac:read`, writes `settings:write`. See
[Session limits](../admin-guides/session-limits.md).

> **Warning:** with no policies and no cluster defaults configured, sessions are unlimited — no
> concurrency cap, no duration ceiling, no idle timeout. Set cluster defaults via
> `sessionlayer.session-limits.*` (see [Control Plane configuration](config-control-plane.md)) and
> use these policies for per-identity tightening.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/session-limit-policies` | List session-limit policies | Cursor-paginated |
| `POST /v1/session-limit-policies` | Create a policy | All three limits absent, or a non-positive limit, is a `422` |
| `GET /v1/session-limit-policies/{sessionLimitPolicyId}` | Get one policy | |
| `PUT /v1/session-limit-policies/{sessionLimitPolicyId}` | Update mutable fields | `name` immutable; `version` required |
| `DELETE /v1/session-limit-policies/{sessionLimitPolicyId}` | Delete a policy | Enforcement falls back to remaining policies / cluster defaults |

A policy matches identities via an `identitySelector` and sets any of `maxConcurrentSessions`,
`maxSessionSeconds`, `idleTimeoutSeconds` (each ≥ 1). When several policies match one identity, the
most restrictive value wins per knob. Every stored value is enforced: the cap and duration at
authorization time, the idle timeout at the Gateway via the signed decision context.

## Sessions

Runtime SSH-session visibility and teardown. List/get require `audit:read`; terminate requires
`lock:write`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/sessions` | List sessions with their decision snapshot | Filters: `identity`, `nodeId`, `accessModel`, `activeOnly` |
| `GET /v1/sessions/{sessionId}` | Get one session | |
| `POST /v1/sessions/{sessionId}/terminate` | Tear down a live session | Pushes a short-TTL, identity-scoped lock; `202` |

A session records the full decision snapshot: `identity`, `nodeId`/`nodeName`, `principal`, the
brokering Gateway, `accessModel`, `capabilities`, the matched rule or JIT/break-glass reference,
`policyEpoch`, `grantExpiry`, and start/end times with an `endReason`. Terminate reuses the lock
teardown path — because the lock selector has no per-session facet, the teardown is identity-scoped
(it also tears down that identity's other live sessions) and bounded by a short TTL
(`sessionlayer.session.terminate-lock-ttl`, default 5 minutes) so the identity can reconnect under
unchanged policy.

## Recordings

Session-recording metadata, replay/export, retention controls. The API never returns recording
bytes — replay and export issue short-lived signed URLs to the still-encrypted object, which only the
customer recording key can decrypt. See [Session recording](../admin-guides/session-recording.md).

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/recordings` | List recording metadata | `recording:replay`; filters: `sessionId`, `identity`, `nodeId` |
| `GET /v1/recordings/{recordingId}` | Get one recording's metadata | `recording:replay` |
| `DELETE /v1/recordings/{recordingId}` | Governance-delete the encrypted object | `recording:delete`; refused (`409`) in compliance mode or under legal hold |
| `POST /v1/recordings/{recordingId}/replay` | Issue a short-lived replay signed URL | `recording:replay`, scopable; itself audited |
| `POST /v1/recordings/{recordingId}/export` | Issue a short-lived export signed URL | `recording:export`, scopable; itself audited |
| `PUT /v1/recordings/{recordingId}/legal-hold` | Place or release a legal hold | `recording:delete`; a held recording is exempt from pruning and deletion |

Recording metadata includes the `sessionId`, `identity`, `nodeId`, `format`, `status`, `wormMode`
(governance vs compliance), `sizeBytes`, the `hashChainHead`, the customer `encryptionKeyRef`,
`legalHold`, `retentionUntil`, and `prunedAt`. The signed URL response carries `url`, `method`, and
`expiresAt` (`sessionlayer.recording.signed-url-ttl`, default 5 minutes). The legal-hold body is
`{"held": true|false, "reason": "..."}` — idempotent by desired state.

## Audit events

Search over the single correlated, append-only audit stream. Requires `audit:read`; results are
additionally filtered to the caller's RBAC scope. See [Audit](../admin-guides/audit.md) and
[Audit events](audit-events.md) for the event catalog.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/audit-events` | Search the stream, newest first | Cursor-paginated; read-only |
| `GET /v1/audit-events/{auditEventId}` | Get one event | |

Search dimensions: `actor`, `subject`, `action` (for example `lock.create`), `outcome`, `sessionId`,
`nodeId`, `nodeLabel` (repeatable `key=value`, ANDed), `sourceIp`, `capability`, `accessModel`, a
`from`/`to` time range (RFC 3339), and `correlationId` — the join key that reconstructs one full path
(approve → connect → run → replay). An unbounded search is limited to a recent default window and an
explicit range wider than the maximum is a `422` (`sessionlayer.audit.search.*`, defaults 90/366
days). A search never mutates the stream; the hash chain stays verifiable.

## Next

- [Control Plane configuration](config-control-plane.md)
- [Audit events](audit-events.md)
- [Session limits](../admin-guides/session-limits.md)
- [RBAC](../admin-guides/rbac.md)
