# Glossary

The platform vocabulary, defined once. [Core concepts](../getting-started/concepts.md) teaches these
in context; every other page uses them consistently.

- **access model** — how a session's permission came to exist: `standing` (a durable rule), `jit`
  (an approved time-boxed request), or `breakglass` (the emergency path). Signed into every
  session's decision context and searchable in the audit stream.
- **Agent** — the per-node outbound connector. It dials out to Gateways, holds a renewable mTLS
  identity, and splices dialed-back sessions to the node's loopback `sshd`, so the node needs no
  inbound network holes.
- **agentless node** — a node with no Agent installed: the Gateway dials its registered address
  directly and verifies its host identity against enrolled material (a host certificate or a pinned
  key — never trust-on-first-use).
- **break-glass** — the always-available emergency access model, independent of your IdP: a
  registered FIDO2 key or a pre-issued offline code. Using it fires an alert immediately, forces
  strict recording, and requires a post-hoc review. A lock still beats it.
- **capability** — one policy-gated thing a session may do: `shell`, `exec`, `sftp`, `scp`. The
  vocabulary also reserves port forwarding and X11 (accepted in policy, but the Gateway does not
  admit those channels in this release) and agent forwarding (never admitted, by design). Rules and
  grants name the capabilities they allow.
- **compliance mode** — the stricter WORM flavor: the recording object is truly un-deletable until
  retention expires; even a governance delete is refused. Contrast with governance mode.
- **Control Plane** — the Java management component: the REST API, policy and identity storage
  (Postgres), the certificate authorities, the authorization engine, and the audit stream. It never
  touches session bytes.
- **correlation id** — the value that joins one access story across audit events, sessions,
  recordings, and traces: the JIT request id, the break-glass activation id, or the session id.
- **customer recording key** — the operator-held public/private key pair recordings are sealed to.
  The platform holds only the public half: SessionLayer can write recordings it cannot read.
- **data-plane RBAC** — the rules deciding who may SSH where, as what login, with which
  capabilities. Deny overrides allow; a source-IP condition can only narrow a decision.
- **decision context** — the signed statement the Control Plane returns on an allowed connection:
  identity, groups, node, capabilities, access model, grant expiry, idle timeout, policy epoch. The
  Gateway verifies the signature and re-checks the context on every channel open.
- **decision log** — the authorization decisions inside the audit stream: every `authz.decision`
  event, carrying the matched rule or lock and the full allow snapshot. Not a separate store —
  search the [audit events](audit-events.md) filtered to `action=authz.decision`.
- **deny wins** — the platform's ordering rule: a deny (a deny rule, a lock, a quarantine) beats
  every allow, grant, or break-glass override. Allows may fail open only in the sense of being
  refused; denies always take effect.
- **device flow** — the browser-based OIDC login for SSH (RFC 8628): the Gateway shows a code and
  URL, you approve in a browser, the session proceeds. The fallback when certificate, pin, and OTP
  authentication do not apply.
- **dial-back** — the outbound-agent connection pattern: the Gateway signals a connected Agent over
  its control channel, and the Agent dials back a fresh stream for that one session.
- **dial-back token** — the single-use token (`SLDB1` format) authorizing exactly one dial-back;
  short-TTL and bound to the session.
- **Gateway** — the Rust data-plane proxy every session passes through: it terminates the user's
  SSH connection, authenticates and authorizes via the Control Plane, connects to the node, bridges
  bytes, records, and enforces locks live. The only component that sees session plaintext.
- **generation counter** — a monotonic counter inside each Gateway/Agent mTLS identity, bumped on
  every renewal. A stale clone renewing with an old generation is detected and the identity is
  locked.
- **governance mode** — the default WORM flavor: retention protects recordings, but a specifically
  privileged, audited role may erase one (the escape hatch for legal erasure duties). Contrast with
  compliance mode.
- **grant expiry** — the moment a session's permission ends: the minimum of the matching rule or
  grant TTL, policy ceilings, and the identity's credential lifetime. Configurable behavior decides
  what happens to a live session at expiry; new privileged channels always stop.
- **hash chain** — each audit event and recording frame carries a hash of its predecessor, so
  truncation or tampering is detectable by re-walking the chain.
- **host CA** — the certificate authority that signs node host certificates, letting clients and
  Gateways verify hosts with no trust-on-first-use prompts.
- **idle timeout** — how long a session may sit inactive before teardown. The Gateway has a static
  bound; a per-identity policy value tightens it (never loosens) via the signed decision context.
- **inner leg** — the Gateway↔node half of a session (an SSH client connection or a spliced agent
  stream). The user-facing half is the outer leg.
- **JIT access** — just-in-time access: you request a target, principal, capabilities, and duration;
  a 0–3 level approval chain decides; the grant is time-boxed and revocable. Self-approval is
  impossible.
- **join token** — the single-use, short-TTL, node-scoped credential an Agent presents to enroll.
  Shown once at issuance; only its hash is stored. The Gateway's equivalent is its **enrollment
  token**, provisioned by the operator (config key `bootstrap.enrollment_token`).
- **lease** — a live session's slot against a concurrency limit. Leases are extended while the
  session runs, released at session end, and swept by a reaper if a Gateway dies without reporting.
- **lock** — the un-overridable deny primitive: it blocks new sessions matching its target and tears
  down live ones, pushed to every Gateway over a dedicated stream. Locks keep denying even if the
  database is lost.
- **node** — a Linux host you reach through SessionLayer, running its own stock `sshd`. Reached
  through an Agent (outbound) or agentlessly (direct dial).
- **node policy** — desired configuration for nodes: labels, connector kind, and declared host-trust
  references.
- **offline code** — a pre-issued, single-use break-glass code for when FIDO2 hardware is
  unavailable. Issued in batches; only hashes are stored.
- **OTP** — a one-time passcode: single-use, short-TTL, issued by an admin for one enrollment or
  recovery login.
- **outer leg** — the client↔Gateway half of a session: the connection your `ssh` command makes.
- **pin** — an authentication shortcut binding a public-key fingerprint to an identity (optionally a
  source CIDR and principals) for a bounded time, so repeat connections skip the browser.
- **platform RBAC** — who may administer SessionLayer itself: roles built from the closed
  platform-permission vocabulary, bound to users or groups, optionally scoped.
- **policy epoch** — a counter identifying the policy state a decision was made under; stamped into
  the decision context so stale decisions are distinguishable after policy changes.
- **presence** — the Control-Plane-recorded fact of which Gateway currently owns a node's agent
  control channel, heartbeated continuously. Sessions landing elsewhere are relayed to the owner;
  stale presence reads as "node offline" — fail closed.
- **principal** — the Linux login a session runs as on the node (for example `deploy`). Granted by
  policy, stamped into the session certificate.
- **quarantine** — an operator action isolating a node: expressed as a lock on the node, so it
  blocks new sessions and kills or drains existing ones, fail-closed.
- **recording** — the sealed asciicast of a session (terminal I/O, SFTP/SCP file metadata — never
  file content), encrypted to the customer recording key, hash-chained, and stored in the WORM
  bucket.
- **relay token** — the single-use token (`SLGW1` format) authorizing one Gateway-to-Gateway byte
  relay for one session.
- **selector** — a shape-validated matching object in rules and policies (identity selectors, node
  label selectors), validated before commit.
- **service account** — a first-class machine identity for the API: defined once, issued rotatable
  credentials, authenticated via `private_key_jwt`, mTLS, or (discouraged) a static secret.
- **session** — one recorded SSH connection through a Gateway: authenticated, authorized against
  policy, certificate-issued, bridged, recorded, and audited end to end.
- **session CA** — the certificate authority that signs the short-lived per-session certificate the
  Gateway presents to the node. Nodes trust it via one `TrustedUserCAKeys` line.
- **SLREC1** — the recording seal format: each recording is encrypted with a fresh data key sealed
  to the customer recording key (ECIES P-256), so only the key holder can decrypt.
- **standing access** — the access model backed by a durable data-plane rule: no request or
  approval, just policy that persists until changed.
- **Tier-0** — the platform's fully-trusted component class: the Gateway (the one process that
  sees session plaintext) and the certificate authorities. Zero trust relocates trust here rather
  than eliminating it; Tier-0 is why the [hardening checklist](../security/hardening.md) exists.
- **user CA** — the certificate authority that signs user SSH certificates, letting users
  authenticate to the Gateway with short-lived certificates instead of long-lived keys.
- **WORM** — write-once-read-many object storage (S3 object lock): recordings land in a bucket
  where they cannot be silently overwritten or deleted. Comes in governance and compliance modes.

## Next

- [Core concepts](../getting-started/concepts.md)
- [API reference](api.md)
- [Trust model](../security/trust-model.md)
