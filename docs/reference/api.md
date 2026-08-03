# API

The Control Plane exposes a contract-first REST API: the same surface the Dashboard uses. The
authoritative contract is `contracts/openapi/openapi.yaml` in the ControlPlane repository
(OpenAPI 3.1). Server interfaces and the Dashboard's typed client are both generated from it.
This page restates the contract by hand, and nothing compares the two — if you change an
operation, change both.

> **Note:** three implemented routes sit outside the contract.
> Two OIDC browser pages (`GET /v1/auth/verify`, `GET /v1/auth/callback`) and the OIDC back-channel
> logout webhook (`POST /v1/auth/backchannel-logout`) return non-JSON, protocol-mandated shapes a
> codegen contract doesn't model well. The first-admin claim call is no longer among them: the
> contract models it, and it is documented below like any other operation.

## Conventions

### Base URL and versioning

Every path is rooted at your Control Plane URL plus the URI major version: `https://cp.example.com/v1/...`.
The URI major version is `v1`. Within a major version all changes are additive: a new optional field or
path never breaks an existing client. Breaking changes would require a new URI major version; see
`contracts/VERSIONING.md` for the full policy, including the N-1 compatibility window the internal
protocols follow.

### Authentication

The API accepts three first-class authentication schemes. HTTP Basic is deliberately not one of them
(a discouraged escape hatch exists behind `sessionlayer.rest-security.basic-auth.*`, see
[Control Plane configuration](config-control-plane.md)).

| Scheme | How it works | Use it for |
|---|---|---|
| OIDC bearer | `Authorization: Bearer <JWT>`, an ID/JWT token validated by the Control Plane against your IdP | Humans and the Dashboard |
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
policies, sessions, recordings, and audit events: the endpoints whose tables below say
"cursor-paginated".

The bounded runtime listings return the full set in one response instead, in a resource-named
array with no cursor: `pins`, `locks`, `joinTokens`, `nodes`, `jitRequests`, and the break-glass
`credentials`, `offlineCodes`, and `activations`. So `GET /v1/nodes` yields `{"nodes": [...]}`.
Pipe it through `jq '.nodes[]'`, not `.items[]`.

### Idempotency

Mutating operations accept an optional `Idempotency-Key` header. A retry with the same key, method,
and path returns the original response without repeating the side effect; reusing a key with a
different request body is a `422`. Keys are retained for a bounded TTL
(`sessionlayer.idempotency.ttl`, default 24 hours). After that a reused key re-executes.

### Errors

Errors the API itself raises are RFC 9457 problem details with media type
`application/problem+json`:

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

> **Note:** `400` is the exception, on every endpoint. A request body that fails
> deserialization or schema validation is rejected by the framework before it
> reaches any handler, so it does not get a problem document. It returns
> `application/json` with the server's default error shape instead:
>
> ```json
> {"timestamp":"2026-07-29T20:58:22.713Z","path":"/v1/rules","status":400,
>  "error":"Bad Request","requestId":"9ae7469a-250"}
> ```
>
> This covers an unknown enum value, malformed JSON, and a missing required
> field alike. The status code and the `requestId` are reliable — correlate on
> that — but do not parse `title`/`detail` from a `400`; they are absent. Every
> error raised by the application, including `403`, `404`, `409` and `422`, is a
> genuine problem document.

### Optimistic concurrency

Config resources carry a read-only `version` counter. Every update (`PUT`) requires the current
`version` in the request body and fails with `409` when it is stale, so two admins can never silently
overwrite each other. Read the resource, edit the fields, and send the `version` you read.

### Config vs runtime resources

Config resources (rules, roles, role bindings, CAs, service accounts, node policies, capability
definitions, JIT/break-glass/session-limit policies) carry an `origin` provenance label (`api`, `ui`,
or `default`) plus the `version` counter, and validate input pre-commit: invalid configuration is a
`422`, never a stored bad row. Runtime resources (nodes, sessions, locks, JIT requests, join tokens,
credentials, recordings, audit events) reflect live state and carry neither.

### Closed vocabularies

Three enums appear throughout:

- Capabilities (what a session may do): `shell`, `exec`, `sftp`, `scp`, `port_forward_local`,
  `port_forward_remote`, `agent_forward`, `x11`. Each is enforced at the Gateway per channel,
  except `agent_forward`, which is never admitted, by design, no matter what a rule grants
  (see [RBAC](../admin-guides/rbac.md)).
- Platform permissions (what an admin may call): `rbac:read`, `rbac:write`, `node:enroll`,
  `node:quarantine`, `node:remove`, `gateway:enroll`, `gateway:remove`, `ca:manage`, `ca:rotate`,
  `request:approve`, `recording:replay`,
  `recording:export`, `recording:delete`, `recording:key-manage`, `audit:read`, `user:manage`,
  `settings:write`, `lock:read`, `lock:write`, `breakglass:manage`. Twenty names; anything else in a
  role is a `422`. The authoritative list is `PlatformPermissions.ALL` in the Control Plane source,
  mirrored exactly by the `platform_role.permissions` CHECK constraint. A docs CI check fails when
  this page, [RBAC](../admin-guides/rbac.md) or the [data model](data-model.md#enums) drifts from
  it.
- Access models: `standing`, `jit`, `breakglass`.

## Meta

Unauthenticated probes for load balancers, orchestrators, and version discovery. They disclose no
identity, node, or policy information.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/healthz` | Liveness/readiness probe | `200` healthy, `503` not ready |
| `GET /v1/version` | Component and protocol version metadata | Public |

`GET /v1/version` returns the component name, its SemVer build version, and the protocol version
ranges it speaks on the Control Plane–Gateway gRPC plane and the Agent–Gateway wire protocol,
useful when planning a mixed-version upgrade (see [Upgrades](../operations/upgrades.md)).

## Bootstrap

The one-time claim of the first-admin credential the Control Plane prints to its own log at cold
start. See [First-admin bootstrap](../admin-guides/authentication.md#first-admin-bootstrap).

| Operation | What it does | Notes |
|---|---|---|
| `POST /v1/bootstrap/claim` | Bind a `subject` as the first `platform-admin` | Public by scheme; the credential is the authenticator |

Send `credential` (the printed value) and `subject` (the identity to make admin). The response is a
plain `{"status": ...}` object rather than an RFC 9457 problem document, on every status code:
`provisioned`, `already_completed`, `not_available` (no credential is armed), or
`invalid_credential`. It is the one endpoint whose *success and application-level* responses
deliberately avoid problem details, and the contract records that as an intentional exception —
distinct from the framework-level `400` shape described under [Errors](#errors), which applies
everywhere.

The claim can succeed at most once per deployment. A concurrent second claim always observes
`already_completed`. The flip is a single conditional update, so there is no window in which two
callers both provision. Once any platform admin exists the endpoint self-disables and no credential
is armed again. Every attempt is audited, including one that presents a wrong credential.

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

An issued OTP returns `otpId`, the raw `otp` (exactly once: only its hash is stored; deliver it
out-of-band), and `expiresAt`. A pin binds a key `fingerprint` to `{identity, sourceCidr, principals}`
with a TTL; source IP is a deny-only reducer: it can narrow access, never grant it.

## Service-account credentials

Runtime credentials for a [service account](#service-accounts) definition.

| Operation | What it does | Notes |
|---|---|---|
| `POST /v1/service-accounts/{serviceAccountId}/credentials` | Issue a rotatable machine credential | `private_key_jwt` key/JWKS ref, mTLS cert fingerprint, or (discouraged) a generated secret returned once |
| `DELETE /v1/service-accounts/{serviceAccountId}/credentials/{credentialId}` | Revoke a credential | Takes effect immediately |

Credentials are stored hashed or by reference. The API never returns stored secret material.

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
| `GET /v1/join-tokens` | List unconsumed, unexpired join tokens | Metadata only, never the raw token |
| `POST /v1/join-tokens` | Issue a join token for a `nodeName` | Raw token returned exactly once |
| `DELETE /v1/join-tokens/{joinTokenId}` | Revoke an unconsumed token | Idempotent |

Issuance is a pure API operation, so an autoscaler or configuration management can re-provision an
Agent without a human. Revoking an already-consumed token has no effect on the identity it produced:
revoking an issued identity is a [lock](#locks).

## Gateway enrollment tokens

Single-use, short-TTL, name-scoped bootstrap credentials for Gateways, the counterpart to a node's
join token. See [Install the Gateway](../installation/gateway.md). All operations require
`gateway:enroll`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/gateway-enrollment-tokens` | List unconsumed, unexpired tokens | Metadata only, never the raw token |
| `POST /v1/gateway-enrollment-tokens` | Issue a token for a `gatewayName` | Raw token returned exactly once |
| `DELETE /v1/gateway-enrollment-tokens/{gatewayEnrollmentTokenId}` | Revoke an unconsumed token | Idempotent |

A token authorizes nothing beyond the enrollment handshake the Gateway already performs, for the
name it was minted against, once, before it expires. Only its SHA-256 hash is stored. Revoke marks
the token consumed rather than deleting the row, because the runtime role holds no `DELETE` on that
table and the enrollment path already refuses a consumed token. Suspending a live Gateway is a
[lock](#locks); retiring its identity is [`DELETE /v1/gateways/{gatewayId}`](#gateways).

`gateway:enroll` is a separate permission from `node:enroll` on purpose. Node enrollment is routine
enough for an autoscaler to hold unattended; a Gateway is the only component that sees session
plaintext, so admitting one is a heavier authority.

## Gateways

Enrolled Gateway identities: their names, certificate fingerprints, and retirement.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/gateways` | List enrolled Gateway identities | Cursor-paginated; requires `gateway:enroll` |
| `GET /v1/gateways/{gatewayId}` | Get one identity | Requires `gateway:enroll` |
| `DELETE /v1/gateways/{gatewayId}` | Retire an identity, freeing its name | Requires `gateway:remove` |

Reads are gated `gateway:enroll` rather than the generic `rbac:read`, matching `listNodes`: a roster
of Gateway names, certificate fingerprints, and which Gateway fronts which nodes is fleet-targeting
metadata and does not belong to every reader. Fingerprints are exposed, certificates and keys are
not.

`fingerprintSha256` is the currently pinned certificate and `prevFingerprintSha256` the immediately
previous one. The sign and renew tiers accept either, so diagnosing a Gateway has three outcomes and
not two:

| The Gateway presents | Meaning | Action |
|---|---|---|
| `fingerprintSha256` | current | none |
| `prevFingerprintSha256` | mid-renewal, still admitted | none |
| neither | refused; signing and renewal are denied | free the name and re-enroll |

Only the third is a problem. Reading a fingerprint mismatch as "re-enroll" without that split points
at a destructive action in the two cases where nothing is wrong.

`gateway:remove` is separate from `gateway:enroll` because retiring is destructive in a way
admitting is not. A Gateway still holding presence is refused unless the delete is forced, so this
cannot quietly cut off a Gateway that is serving traffic. The ordinary use is freeing a name after a
restore so the Gateway can re-enroll; see
[Disaster recovery](../operations/disaster-recovery.md).

## Nodes

Node lifecycle: agentless registration, listing, quarantine, and removal. Agent nodes join via
[join tokens](#join-tokens) instead of `POST /v1/nodes`.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/nodes` | List enrolled nodes with connectivity, status, health | `node:enroll`; removed nodes excluded by default |
| `POST /v1/nodes` | Register an agentless node | `node:enroll`; host identity material required, never TOFU |
| `GET /v1/nodes/{nodeId}` | Get one node | `node:enroll` |
| `DELETE /v1/nodes/{nodeId}` | Remove (deregister) a node | `node:remove`; revokes an agent node's credential |
| `POST /v1/nodes/{nodeId}/quarantine` | Quarantine a node | `node:quarantine`; expressed as a lock, deny wins |
| `DELETE /v1/nodes/{nodeId}/quarantine` | Release a node from quarantine | `node:quarantine` |

Registration takes the node's `name`, dial `address`, `labels`, and its host identity: a
host-CA-signed `hostCertificate` or an explicitly pinned `pinnedHostKey` (at least one). When
enrollment approval is required (`sessionlayer.node.enrollment-approval-required`), a new node starts
`pending` and is excluded from targeting until activated. Quarantine takes a `reason` and an
`existingSessions` policy: `kill` (default) tears live sessions down at once, `drain` lets them
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
the `approvalDeadline`, and (once fully approved) `grantExpiresAt`, when the grant clock started at
final approval. Approve/deny/revoke accept an optional body with a `reason`.

## Break-glass

Credential management and activation review for the emergency access path. All operations require
`breakglass:manage`. See [Break-glass access](../admin-guides/break-glass.md).

A credential's public metadata is `id`, `keyFingerprint` (the OpenSSH SHA256 fingerprint),
`skApplication`, `identity`, `allowedPrincipals`, `nodeIds`, `expiresAt`, `revokedAt`, `createdBy`
and `createdAt`. Whether the key was registered touch-required is not among them, and there is
nothing else to read it from: user presence is asserted by the authenticator at signing time, and
the Gateway cannot check the flag server-side (accepted risk BG-1). Touch-required is a
provisioning-time control. It cannot be audited after the fact, so a fleet you inherited has to be
re-provisioned rather than surveyed.

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

Data-plane RBAC: the typed allow/deny grants that decide who may SSH where. Reads require
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

Platform RBAC roles: named sets of the closed platform-permission vocabulary. Reads require
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
| `PUT /v1/role-bindings/{bindingId}` | Replace a binding's scope | Subject and role immutable, rebind by delete + create |
| `DELETE /v1/role-bindings/{bindingId}` | Delete a binding | Idempotent |

A binding's optional `scope` narrows where the role applies: used to scope `recording:replay`,
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
| `POST /v1/cas/{caId}/rotate` | Rotate the CA's key | Optional `backend`/`keyReference`/`algorithm` override the incoming key, each defaulting to the active CA's own; the old key stays trusted through the overlap window |
| `GET /v1/cas/{caKind}/public-key` | Export an SSH CA's public key | `caKind` is `user`/`session`/`host`; requires `node:enroll` |
| `GET /v1/cas/mtls/trust-anchor` | Export the internal mTLS CA certificate | Public trust anchor; requires `gateway:enroll` |

A configuration names the `caKind` (`user`/`session`/`host`), the `backend` (`local`, `aws_kms`,
`azure_keyvault`, `vault`), a `keyReference` (a reference; a value that looks like private material
is rejected), and the `algorithm` (`ecdsa-p256`, `ecdsa-p384`, `ecdsa-p521`; anything else, or an
algorithm the chosen backend cannot produce, is a `422` at validation).
`rotationState` (`incoming`/`active`/`outgoing`/`expired`) is managed by the rotation state machine
and read-only here.

The `backend` set is wider than what can sign. `local`, `aws_kms` and `azure_keyvault` resolve to a
signer; `vault` is refused at validation with a `422` saying the backend has no signer in this
build. The write path and the signer path ask the same question, so a backend the API accepts is one
that can issue. A row stored before that gate existed still cannot sign, and fails at the first
signature instead. Each key-service backend additionally constrains its `keyReference`, checked at
the same validation step: `azure_keyvault` requires a fully versioned Key Vault identifier, and
`aws_kms` a key ARN in the configured account, region and partition (never an alias, never a bare
key id). Either is a `422` on a Control Plane that has not configured that backend. See
[Certificate authorities](../admin-guides/certificate-authorities.md) for the two adoption
procedures and [Production hardening](../security/hardening.md) for the KEK that protects whatever
remains on `local`.

The `CaAlgorithm` enum in the contract is wider than what any backend can produce: it also carries
`ed25519`, `rsa-2048` and `rsa-4096`, matching the `ca_config.algorithm` CHECK exactly so a row an
upgraded deployment already holds can still be read back, and every backend other than `local`
produces only `ecdsa-p256` of the three ECDSA curves. This API refuses to create a CA on, or update one onto, any
of the three non-ECDSA algorithms, and none of them can be assembled into a signer. See
[Data model](data-model.md#enums) for why the two layers differ.

`GET /v1/cas/{caKind}/public-key` returns the active CA's public key in the two forms an operator
needs: `publicKeySpkiDer` (base64) and `opensshPublicKey`, the one-line form that goes straight into
a node's `TrustedUserCAKeys` or a client's `@cert-authority`, plus `algorithm`, `rotationState` and
`fingerprintSha256`. The projection is column-scoped and never touches the wrapped private key or
the backend unwrap path. `mtls` is not an accepted `caKind` and is a `400`, since that CA is not a
member of this collection. A `409` means the active CA of that kind carries an algorithm with no
OpenSSH key type: the export refuses rather than emit a line it cannot label honestly, because a
mislabeled `TrustedUserCAKeys` entry fails at session time, on every node at once, with nothing
pointing back to the export.

The internal mTLS CA is a fourth CA and is deliberately absent from this collection: it has no
`caId` to address and no update, delete, or rotate surface. `GET /v1/cas/mtls/trust-anchor` is its
only API surface, and it returns the certificate alone: `pem`, `fingerprintSha256`, `subject`, and
the validity window. It reads the certificate column and nothing adjacent to it, so no wrapped key
material can reach the response. It is gated by `gateway:enroll` rather than `ca:manage`, so
installing a Gateway does not require the authority to manage CA configuration.

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
`hostCaRef` host-trust references (references only; private material is rejected).

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
`offline_code`, the IdP-independent authentication paths).

## Operator settings

Deployment-wide settings. The table is a database-enforced singleton, so the shape is `GET`/`PUT` on
one resource with no collection and no id in the path.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/operator-settings` | Read the settings singleton | Requires `rbac:read` |
| `PUT /v1/operator-settings` | Update the writable fields | Requires `settings:write`; `version` required |
| `GET /v1/operator-settings/recording-customer-key` | Read the customer recording key | Public half and fingerprint; requires `rbac:read` |
| `PUT /v1/operator-settings/recording-customer-key` | Provision or rotate that key | Requires `recording:key-manage` |

The projection is narrower than the row, and the exclusions are deliberate. `kekReference` is
neither writable nor readable, the `bootstrap*` fields belong to the bootstrap flow, and
`defaultCaBackend` is read-only because it is consumed only when cold start provisions a CA kind
that has no row yet.

### The writable field set

`PUT /v1/operator-settings` replaces the whole resource, and the request schema is closed. These
eight names are the complete writable set; any other property in the body, `defaultCaBackend` and
`kekReference` included, is a `400` rather than a silent no-op:

| Field | Required? | Omitting it |
|---|---|---|
| `auditRetentionDays` | yes | `400` |
| `recordingRetentionDays` | yes | `400` |
| `defaultWormMode` | yes | `400` |
| `otpTtlSeconds` | yes | `400` |
| `defaultMaxSessionSeconds` | no | clears the cluster default, or `422` if pinned |
| `defaultIdleTimeoutSeconds` | no | clears the cluster default, or `422` if pinned |
| `defaultMaxConcurrentSessions` | no | clears the cluster default, or `422` if pinned |
| `version` | yes | `400`; a value that is not current is a `409` |

The customer recording key is not in that set. It lives on the sub-resource below, so no `PUT` to
the parent can change it, clear it, or un-provision it, whatever the body leaves out.

Three fields move in one direction only. `auditRetentionDays` and `recordingRetentionDays` accept an
increase or no change, and `defaultWormMode` accepts `governance` to `compliance`. The reverse of
each is a `422` at every permission level, because one call in that direction destroys or unprotects
evidence. Weakening any of them stays a database-owner operation, on purpose. Retention also has a
ceiling of 36525 days: a longer window overflows the object-lock retain-until stamp, and the ratchet
means this API could not take a typo back down.

The three session-limit defaults are writable only while no deployment property pins them. `GET`
returns `deploymentManagedFields` naming the pinned ones, and changing a pinned field is a `422`
naming the property that owns it. Without this a write would be silently reverted at the next
restart, which is worse than refusing it. Because omission clears a field, leaving a pinned one out
is a change too, and refused the same way: submit it unchanged. A read-modify-write of the whole
resource does that for you.

### The customer recording key

`PUT /v1/operator-settings/recording-customer-key` takes `publicKey` (string: base64 DER
SubjectPublicKeyInfo, at most 8 KiB decoded), `sealAlgorithm` (string), an optional `keyRef`
(string, a reference only), and `version` (integer). The `version` is the *parent* resource's: both
paths write the same singleton row and share its one counter, so read `.version` from
`GET /v1/operator-settings` and send it here. A value that is not current is a `409`.

Private key material, a PEM blob, a curve that does not match `sealAlgorithm`, and garbage are each
a `422`, checked before anything is stored. `ecies_p256` is the only `sealAlgorithm` accepted: the
Gateway seals with ECIES on P-256 and nothing else, so a key stored under another algorithm would
refuse every session at the first recording. The refusal happens here, where the error can still
name the cause.

A write when a key is already configured is a rotation, and needs two more fields:
`expectedFingerprintSha256` (string, the lowercase hex SHA-256 over the DER SubjectPublicKeyInfo of
the key being replaced, from `GET /v1/operator-settings/recording-customer-key`; a mismatch is a
`409`) and `acknowledgeExistingRecordingsUndecryptable` (boolean, and it must be `true`; absent or
`false` is a `422`). Both exist because every recording sealed under the outgoing key stays readable
only by the outgoing private key. On a first provisioning, where neither a key nor a recording
exists, both are refused with a `422`: a caller that thinks it is replacing a key when none exists
has lost track of the cluster's state.

There is no `DELETE`: un-provisioning the key would fail-close every future session. Audit records
fingerprints only, never key bytes. See
[Session recording](../admin-guides/session-recording.md).

## Session leases

Concurrency leases, the rows the per-identity session cap is counted from.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/session-leases` | List leases | Cursor-paginated; filters `identity`, `activeOnly`; requires `audit:read` |
| `GET /v1/session-leases/{sessionLeaseId}` | Get one lease | Requires `audit:read` |
| `POST /v1/session-leases/{sessionLeaseId}/release` | Release one lease | Requires `lock:write`; `reason` required and audited |

A lease counts while `countsTowardCap` is true, which is unreleased and unexpired. An expired lease
has already stopped counting, and the reaper's later `releasedAt` stamp only tidies the row. So a
ghost is not an expired lease: it is one that still counts with no live session behind it, found by
comparing this collection filtered by `identity` with `activeOnly=true` against
[`GET /v1/sessions`](#sessions) filtered the same way. A lease carrying no `expiresAt` is the
unbounded case.

This is the diagnostic half and the sharper of the two, because an identity blocked by a lease that
outlived its session is refused with the same generic policy denial as a real deny.

There is deliberately no bulk release and no release-by-identity. Releasing every lease for an
identity trades a bounded over-count, which denies a legitimate user, for an under-count that lets
them exceed the cap for as long as the real sessions run. The dangerous shape is not offered:
diagnose with the collection, then release the specific lease. Release is idempotent.

## Session-limit policies

Per-identity overrides for the three session-limit knobs: concurrent-session cap, max session
duration, and idle timeout. Reads require `rbac:read`, writes `settings:write`. See
[Session limits](../admin-guides/session-limits.md).

> **Warning:** with no policies and no cluster defaults configured, sessions are unlimited: no
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

> **Ordering note:** like every cursor-paginated collection (see above), `GET /v1/sessions`
> orders by the resource's internal `id` (a Gateway-minted identifier, not a creation
> timestamp), so page order is stable but not chronological. The admin Dashboard
> currently renders sessions in that same id order with no additional client-side sort; use
> the `startedAt`/`Started` column, not list position, to reason about recency. Sort
> client-side on `startedAt` if you need a strictly chronological view.

A session records the full decision snapshot: `identity`, `nodeId`/`nodeName`, `principal`, the
brokering Gateway, `accessModel`, `capabilities`, the matched rule or JIT/break-glass reference,
`policyEpoch`, `grantExpiry`, and start/end times with an `endReason`. Terminate reuses the lock
teardown path: because the lock selector has no per-session facet, the teardown is identity-scoped
(it also tears down that identity's other live sessions) and bounded by a short TTL
(`sessionlayer.session.terminate-lock-ttl`, default 5 minutes) so the identity can reconnect under
unchanged policy.

`endReason` is advisory diagnostics, not an enforced enum: the column carries no CHECK, and the
authoritative "why" for a lock or an expiry is the decision and lock audit chain. Seven values are
produced, by three different writers.

| `endReason` | Written when |
|---|---|
| `expired` | The grant expiry was reached mid-session. |
| `idle_timeout` | The idle bound elapsed. |
| `locked` | A lock matched and tore the session down. |
| `error` | The session ended abnormally, or its recording finalized as `failed`. |
| `closed` | The orderly end, and the default when nothing more specific applied. |
| `truncated` | The recording finalized short of the whole session. |
| `gateway_removed` | The session's Gateway identity was force-removed while it was still open. |

The first five come from the Gateway's teardown signal. `truncated` and the recording half of `error`
come from the recording-finalize path, which closes the owning session and derives the reason from
the recording's terminal status, so those two describe how the recording completed rather than why
the session stopped. `gateway_removed` is written directly by the Control Plane.

`closed` covers more than a client disconnect. A Gateway drain that reaches its deadline tears its
remaining sessions down with exactly this value, so a maintenance teardown is not distinguishable
from a normal one by `endReason` alone. Correlate on the Gateway and the timestamp when you need to
tell them apart.

## Recordings

Session-recording metadata, replay/export, retention controls. The API never returns recording
bytes: replay and export issue short-lived signed URLs to the still-encrypted object, which only the
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
`{"held": true|false, "reason": "..."}`, idempotent by desired state.

## Audit events

Search over the single correlated, append-only audit stream. Requires `audit:read`; results are
additionally filtered to the caller's RBAC scope. See [Audit](../admin-guides/audit.md) and
[Audit events](audit-events.md) for the event catalog.

| Operation | What it does | Notes |
|---|---|---|
| `GET /v1/audit-events` | Search the stream, newest first | Cursor-paginated; read-only |
| `GET /v1/audit-events/{auditEventId}` | Get one event | |

Search dimensions: `actor`, `subject`, `action` (for example `lock.create`), `outcome` (one of
`success`, `denied`, `failure`, `error`; the value for a denial is `denied`, never `deny`), `sessionId`,
`nodeId`, `nodeLabel` (repeatable `key=value`, ANDed), `sourceIp`, `capability`, `accessModel`, a
`from`/`to` time range (RFC 3339), and `correlationId`: the join key that reconstructs one full path
(approve → connect → run → replay). An unbounded search is limited to a recent default window and an
explicit range wider than the maximum is a `422` (`sessionlayer.audit.search.*`, defaults 90/366
days). A search never mutates the stream; the hash chain stays verifiable.

`outcome` and `action` are matched as literal strings, not validated against a vocabulary, so a
value outside the set is not an error: the filter matches nothing and the search returns an empty
page. In a live access-denial investigation that is indistinguishable from "no such decision",
which is why the four values are spelled out above.

An event carries `accessModel` in its response as well as in the filters, so a result can be read
without narrowing by a dimension you could not otherwise see. It also carries the chain columns
`seq`, `prevHash` and `recordHash`, but only for a caller whose `audit:read` binding is unscoped.
That restriction is the point: results are scope-filtered, and a chain walk over a filtered view
reads clean even when the rows it could not see contain the break, so exposing the fields to a
scoped reader would offer a verification that does not verify. What they support is a linkage check
(`prevHash` of each event against `recordHash` of its predecessor) and `seq` density. Recomputing
`recordHash` is not possible from the API: it is taken over the Control Plane's canonical event
encoding, which is not part of this contract.

## Next

- [Control Plane configuration](config-control-plane.md)
- [Audit events](audit-events.md)
- [Session limits](../admin-guides/session-limits.md)
- [RBAC](../admin-guides/rbac.md)
