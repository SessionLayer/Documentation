# Trust model

This page tells you exactly what you are trusting when you deploy
SessionLayer, what the platform can and cannot see, what it promises never to
do — and every documented accepted risk, in plain language. It is written for
the security reviewer who has to sign off on the deployment; nothing here is
marketing.

## The honest core: this is an intercepting proxy

SessionLayer records sessions because the Gateway **terminates and
re-originates SSH** — it decrypts your session, taps it, and re-encrypts it
to the node. A pure pass-through jump host sees only ciphertext and can never
give you recording, command logs, or file-transfer audit; SessionLayer can,
precisely because it is a man-in-the-middle you installed on purpose.

Is that still "zero trust"? Zero trust here describes the **access-decision
model**: no implicit network trust, every session re-verified, every
credential short-lived. It does not mean "trust nothing" — the Gateway and
the CAs are a fully-trusted **Tier-0** component. What the platform does is
*relocate* trust: from long-lived SSH keys scattered across hundreds of nodes
and laptops, into one audited, hardened, short-lived-certificate control
point. If your threat model rejects any plaintext-visible intermediary, use
end-to-end SSH and accept the loss of recording and audit — that trade-off is
real, and this page states it rather than papering over it.

## What each component can see

| Component | Public surface | Sees SSH plaintext? | Holds long-lived secrets? |
|---|---|---|---|
| Control Plane | HTTPS: API, Dashboard-facing endpoints, OIDC pages | **No — never** | CA key *references* (production keys live in KMS/Vault); no session keys |
| Gateway | SSH (users), WSS (agents) | **Yes — the only component that does** | its own renewable mTLS identity; per-session keys that never persist |
| Agent | none (outbound only) | No (it splices ciphertext) | its renewable mTLS identity |

The load-bearing invariant is **"only the Gateway sees session plaintext"** —
not "the Control Plane is private" (it isn't; it serves your users' browsers).
Consequences, each pinned by a test in the sign-off suite:

- The Control Plane never receives an inner-leg private key: the Gateway
  generates the per-session keypair and sends only the public key for
  signing (with Vault, the sign-only endpoint — never one that returns keys).
- Recordings are sealed to the **customer recording key** before upload. The
  Control Plane holds only your public key; replay decrypts in your browser.
  A compromised Control Plane, a malicious platform admin, or SessionLayer
  itself can read recording *metadata* — never content or keystrokes.
- Session bytes never traverse the coordination bus in HA, and telemetry
  spans carry IDs and durations, never content.

## The promises (deliberate non-behaviors)

Eight things the platform **must not** do, re-verified in the production
sign-off (seven by direct negative tests; the eighth — the GitOps
reconciler touching runtime state — is held by that component's deliberate
non-existence):

1. No long-lived SSH key is ever a standing access path — all access rides
   short-lived certificates; a bare key offered as standing auth is refused.
2. No host or node identity is **ever** trusted on first use **in the
   platform's own verification** — node enrollment requires a host anchor, an
   unknown host key aborts the session in both connectivity models, and Agent
   and Gateway enrollment are anchored too, never TOFU. The honest boundary:
   how *your users' SSH clients* verify the Gateway's own front-door host key
   is client configuration, which no server can force — distribute the
   Gateway's host-key material and require strict checking in managed client
   configs (see the Gateway-verification section of
   [SSH access](../user-guide/ssh-access.md); the ProxyJump risk below is the
   same boundary).
3. The Control Plane never observes session plaintext.
4. A deny, lock, or authorization decision never fails open. Allow may fail
   open in narrow, documented ways; **deny always fails closed, and deny
   wins** — including when the Control Plane is down, when the lock feed is
   degraded, and in break-glass mode.
5. Session bytes never ride the coordination bus.
6. No GitOps reconciler mutates runtime state (locks, sessions, grants) —
   GitOps is not shipped at all; see [the FAQ](../faq.md).
7. The Control Plane never issues an inner-leg private key.
8. Source IP is never positive evidence of identity — everywhere it appears,
   it can only *reduce* access.

Number 4 is the safety spine and worth restating operationally: locks live on
an actively *pushed* deny-list that every Gateway holds locally, so
revocation keeps working under total datastore loss; a Gateway that cannot
confirm its deny-list refuses what it cannot verify.

## Accepted risks, in plain language

Every risk below is documented in the product repositories' audit records and
was re-justified — not waved through — in the final adversarial reviews. The
big ones first, each with your operational lever.

### Break-glass user presence is enforced by the key, not the server (BG-1)

The Gateway's SSH stack verifies *possession* of a break-glass FIDO2 key but
cannot assert the touch (user-presence) flag server-side — the library
provides no seam for it. A break-glass key provisioned **without**
touch-required could therefore be exercised silently by malware on the
operator's machine. *Your lever:* provision break-glass keys touch-required,
always — this is a hard [deployment precondition](hardening.md), and the
compensating controls (alert on every use, forced strict recording,
mandatory review, lock supremacy, time-boxing) all stand regardless.
(Original severity high; accepted with the precondition.)

### Device-flow phishing has an inherent residual

An attacker can initiate an OIDC device flow and social-engineer a victim
into approving it — a property of the device grant itself, industry-wide.
SessionLayer's posture: device flow is fallback-only (certificates and keys
are primary), the verification page is a full PKCE relying party, the
approving browser's source context is correlated and audited, and strict
approver-IP enforcement exists but defaults off (exact matching over-denies
NAT/mobile users). *Your lever:* enable enforcement where your population
allows; train the code-matching habit.

### Tamper evidence is hash-chain + WORM, not an external anchor

Audit events and recordings are hash-chained and land in object-locked
storage — any mutation, removal, or reorder is detectable. But the audit
chain head lives in the same Postgres as the data, so an attacker with full
database superuser control who also defeats the append-only trigger could
rewrite history *and* its chain. The externally-anchored Merkle root that
would defeat even that is **deliberately deferred and not shipped** — do not
design your compliance story around it. The same stance appears in the
supply-chain verifier: release transparency is proven by Rekor's signed
timestamp, not by a Merkle inclusion proof. *Your levers:* compliance-mode
WORM, the off-box SIEM forward (your copy of the chain, outside the blast
radius), a restricted database role, and the node-local `sshd` second trail.

### A sustained partition can under-count session slots (AR-GW-LEASE-PARTITION)

If a Gateway loses the Control Plane for longer than ~22.5 minutes (shipped
defaults) while sessions run on, the [session-limit](../admin-guides/session-limits.md)
accounting can transiently under-count those slots until the sessions really
end. No over-admission occurs *during* the partition (new sessions fail
closed), the hard cap holds whenever the Control Plane is reachable, and
each occurrence is visible in the reaper/lifecycle meters. Inherent: a
partitioned Gateway cannot hold fleet-wide accounting, and the alternative —
counting unreachable Gateways' leases as live forever — turns every
partition into a permanent capacity leak.

### ProxyJump's no-TOFU guarantee depends on client configuration

On the ProxyJump path the Gateway presents a host-CA certificate, but SSH
servers must also advertise their plain host key — a client **without** the
`@cert-authority` line, running with lax host-key checking, would silently
trust-on-first-use the Gateway's own key. The server cannot force client-side
verification; no SSH server can. *Your lever:* distribute the
`@cert-authority` line and require `StrictHostKeyChecking yes` in managed
client configs — and pre-provision the Gateway's own front-door host key the
same way, per the Gateway-verification section of
[SSH access](../user-guide/ssh-access.md) (promise 2 above scopes what "no
TOFU" does and does not cover client-side).

### Compliance-mode erasure is crypto-shred, and only you can do it

A compliance-WORM recording cannot be deleted by anyone — including the
platform — before its retention period expires (retention is yours to set;
keep it at or above your regime's floor). Within that window, GDPR-style
erasure for such a recording reduces to destroying your
customer recording key material, which is in your hands, not SessionLayer's.
This is the same property that makes recordings unreadable to the platform;
you cannot have one without the other. If your regime requires erasure of
individual recordings, run governance mode.

### Recording content boundaries

Keystroke capture means **secrets typed at prompts are captured** — sealed to
your key, unreadable to the platform, but present in the recording you can
decrypt. Treat recording replay authority accordingly. Also: legacy
`scp`-over-exec transfers land their raw bytes in the terminal capture
(modern SFTP-based transfers are content-free, names/sizes/hashes only), and
a replay/export signed URL, though single-object, ciphertext-only, and
5-minutes short, cannot be revoked within its lifetime.

### Tier-0 hardening has enumerated residuals

The Gateway/Agent sandbox (privilege drop, seccomp, Landlock, coredumps off)
carries documented edges: kernels without Landlock degrade loudly instead of
refusing to boot (network-egress confinement needs Linux ≥ 6.7, notably on
arm64); opt-in OTLP telemetry threads start before Landlock's domain in one
path (backstopped by the NetworkPolicy and seccomp); `ioctl` and `clone3`
cannot be fully narrowed by seccomp (bounded — no tty fd is exposed, and
namespace escapes are killed). Swap is a separate exposure: disable or
encrypt it on Gateway hosts. *Your lever:* the
[hardening checklist](hardening.md) — the OS/container layer exists
precisely to catch what the in-process layer cannot.

## The full residual inventory

The remaining accepted risks on the books — lower severity, engineering-level
— kept here so nothing is discoverable only by reading source. IDs refer to
the audit records in the product repositories (Gateway entries live in that
repository's `audit/closed/` directory — its convention files accepted
findings there).

| ID | Sev | Plain meaning |
|---|---|---|
| `F-db-password-1` (CP) | med | the restricted `cp_runtime` DB password is set once at first migration from a placeholder, ships with a dev default, and has no in-app rotation — set a real one before first boot and rotate via `ALTER ROLE` ([hardening](hardening.md)); blast radius is capped by the role's grants |
| `F-per-boot-signing-keys` (CP) | med | machine-token and OIDC-state keys are per-instance — in HA, set the shared state HMAC key and expect machine tokens to be instance-local ([High availability](../admin-guides/high-availability.md)) |
| `F-rotation-drain-window-1` (CP) | med | CA rotation does not verify your fleet's trust distribution finished before the old key drains — sequence your config management ([Certificate authorities](../admin-guides/certificate-authorities.md)) |
| `F-audit-default-recovery-1` (CP) | med | if audit partition create-ahead lapses for months, recovering rows from the DEFAULT partition is a documented manual DBA procedure; inserts never fail meanwhile |
| `F-s17-reads-behind-write-1` (CP) | med | some config families (CAs, node/JIT/capability policies, service accounts, break-glass) have no read-only permission — reading them requires the management permission |
| `F-signed-url-revocation-1` (CP) | med | replay/export URLs are un-revocable within their 5-minute TTL (ciphertext-only, single-object) |
| `F-authz-policy-scale-1` (CP) | low | authorization loads the full rule/lock set per decision — O(rules) per connect, fine at realistic fleet sizes |
| `F-authz-cap-granular-deny-1` (CP) | low | there is no per-capability *deny* primitive; capabilities are withheld by omission (default-deny per capability) |
| `F-authz-session-id-1` (CP) | low | the Gateway-allocated session id is the session row's primary key; a collision fails the insert (fail-closed) |
| `F-lock-ingest-validation-1` (CP) | low | a hypothetical malformed lock target stored outside the API would match *everything* (fail-closed over-blocking; API ingest rejects such targets) |
| `F-platform-explicit-deny-1` (CP) | low | platform RBAC is additive-only — no deny bindings; remove bindings or use a lock |
| `F-bootstrap-credential-ttl` (CP) | low | the printed-once first-admin credential has no clock expiry — it self-disables on claim or once any admin exists; claim it promptly |
| `F-rate-limit-fixed-window` (CP) | low | auth rate limiting is fixed-window — a boundary-straddling burst can pass ~2× the limit momentarily |
| `F-rest-mtls-revocation` (CP) | low | REST mTLS accepts a revoked-but-unexpired internal client cert (no CRL/OCSP); leaves are short-TTL and authorization still requires an explicit binding |
| `F-agent-mtlsjoin-revocation-1` (CP) | low | mTLS agent join does not check your operator PKI's CRL/OCSP at bootstrap; the resulting platform credential is lockable regardless |
| `F-oidc-discovery-hardening` (CP) | low | OIDC discovery/JWKS timeouts are fixed literals and a changed `jwks_uri` needs a restart |
| `F-outerauth-device-groups` (CP) | low | an identity resolved via device flow carries no OIDC group claims into that authorization — group-only rules may not match a device-flow session; identity-named rules are unaffected |
| `F-serial-allocator-1` (CP) | low | certificate serials have no unique/monotonic allocator (no KRL story); revocation is by lock + short TTL, not serial |
| `F-startup-block-budget` (CP) | low | worst-case first boot (CA cold start + bootstrap + partitions) needs ~150 s — size your startupProbe accordingly ([hardening](hardening.md)) |
| `F-r2dbc-pool-1` (CP) | low | DB pool sizing is unset; a connect storm throttles fail-closed at the RPC deadline |
| `F-s17-idempotency-concurrency-1` (CP) | low | two *exactly* concurrent requests with the same Idempotency-Key can both execute (retries after a response are safe) |
| `F-s17-integrity-map-1` (CP) | low | any DB integrity violation on config writes surfaces as a 409 name-conflict, occasionally mislabeling the cause |
| `F-s17-config-affordances-1` (CP) | low | no dry-run, bulk apply, revision history, or list filtering on the config API |
| `F-retention-claim-delete-residual-1` (CP) | low | if an object-store delete fails after the row is claimed, a pruned-marked row can briefly coexist with the (encrypted) object — logged for reconciliation |
| `F-recording-delete-sod-1` (CP) | low | legal-hold custody and governance delete share one permission (`recording:delete`) — no separation of duties between them |
| `F-recording-list-scope-1` (CP) | low | a *scoped-only* auditor cannot list/discover recordings (fail-closed; they can still replay a specific in-scope one) |
| `F-replay-export-parity-1` (CP) | low | replay and export both amount to a full-object ciphertext download; the permissions differ in name, not power |
| `F-usercert-ecdsa-only` (CP) | info | outer-leg user-certificate verification supports ECDSA user CAs only |
| `F-source-ip-trusted-1` (CP) | info | the resolved identity/groups/source IP in an authorization request are asserted by the mTLS-authenticated Gateway — part of the Tier-0 trust, not an independent check |
| `F-oidc-spec-deviations` (CP) | info | five documented, deliberate OIDC/OAuth deviations (e.g. `at_hash` unvalidated because the access token is discarded) |
| `F-eku-enforcement-1`, `F-access-accepted-risk-1` (CP) | info | consolidated reviewer-confirmation notes (EKU enforcement confirmed; S13 design decisions recorded so they aren't re-flagged) |
| `F-recorder-frame-count-1` (GW) | low | the recording cipher binds each frame's index but not the total count — trailing-frame truncation of a *stolen ciphertext* decrypts cleanly; the CP-held whole-object digest and WORM catch it on the record of truth |
| `F-gw-breakglass-secret-zeroize-1` (GW) | med | break-glass offline codes and tokens transit the Gateway heap in non-zeroized copies (unlike recorder and inner-key material, which is scrubbed); coredumps-off and no-swap are the compensating controls |
| `F-snapshot-empty-retention-1` (GW) | med | a datastore substitution that serves a successfully-read but *empty* lock snapshot on reconnect would shrink a Gateway's deny-set — the feed's epoch signal is advisory, not authoritative |
| `F-dep-1` (GW) | med (practically low) | the `rsa` crate remains in the lockfile as an uncompiled optional dependency (RUSTSEC-2023-0071 scanner noise; never built into the binary) |
| `F-otp-transit-1` (GW) | low | OTPs are zeroized in the Gateway's handler, but the gRPC serialization buffers that carried them are not |
| `F-sshkey-dup-1` (GW) | low | two versions of the `ssh-key` crate coexist (the SSH library's boundary vs the platform's own use) |
| `F-lockfeed-fleet-scale-1` (GW) | low | lock-feed reconnects have no jitter and a fleet-wide lock's teardown fans out synchronously — at very large fleets this can herd |
| `F-pty-wantreply-1` (GW) | low | the inner-leg PTY request doesn't ask for a reply, so a node-side PTY allocation failure is silently swallowed rather than surfaced |
| `F-gendesync-1` (GW) | low | a latent busy-renew path in Gateway identity renewal could desync the generation counter; it surfaces fail-closed as a repair-needed lock |
| `F-cert-local-validation-1` (GW) | low | by-design note: the SSH library locally checks certificate expiry and self-signature ahead of the Control Plane's authoritative checks |
| `F-gw-breakglass-accepted-notes-1` (GW) | low | consolidated break-glass review notes (metrics, fan-out, attestation, disambiguation) recorded so they aren't re-flagged |
| `F-proxy-maxaddr-1` (GW) | info | the PROXY v2 parser caps the address block at a fixed size |
| `F-context-gatewayid-bind-1` (GW) | info | the signed decision context binds the session id but not the gateway id; the mTLS channel identity covers the gap |
| `F-hardening-1` (Agent), `F-hardening-residuals-s23` (GW) | low | the sandbox residuals described above (Landlock degrade, OTLP threads, `ioctl`/`clone3` breadth) |
| `F-supplychain-set-only-1` (Agent) | low | release transparency via Rekor signed timestamp only — no Merkle inclusion proof (fails closed if the timestamp is absent) |
| `F-supplychain-repro-inputs-1` (Agent) | info | independent rebuilds must match documented preconditions (pinned toolchain, `protoc` version) — some build inputs aren't pinned by the workflow itself |
| `F-docker-2` (Agent) | info | container base images are pinned by tag, not digest |

## What was proven

The production sign-off maps all 115 requirements to direct tests: **113
proven, 0 partial, 2 gaps** — the two gaps being the GitOps reconciler,
descoped by decision (not built, not documented as available). The nine
load-bearing invariants — deny-fails-closed, lock supremacy, no
self-approval, inner-key custody, customer-key unreadability, no-TOFU,
single-use tokens, clone detection, verify-before-run — each carry a direct
break-it test. The verdict that accompanies this: production-grade **under
the operator preconditions** — which is the next page.

## Next

- [Production hardening](hardening.md) — the preconditions, as an ordered
  checklist.
- [Supply chain](supply-chain.md) — verifying that what you run is what was
  built.
- [Session recording](../admin-guides/session-recording.md) — the
  customer-key seal in practice.
- [FAQ](../faq.md) — the short answers, including "can staff read my
  recordings?"
