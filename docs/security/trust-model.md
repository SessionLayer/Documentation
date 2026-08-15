# Trust model

Deploying SessionLayer means trusting exactly this: what the platform can
and cannot see, what it promises never to do, and every documented accepted
risk, stated in plain language for the security reviewer who has to sign
off on the deployment. Nothing here is marketing.

## Why this is an intercepting proxy

SessionLayer records sessions because the Gateway terminates and
re-originates SSH: it decrypts your session, taps it, and re-encrypts it to
the node. A pure pass-through jump host sees only ciphertext and can never
give you recording, command logs, or file-transfer audit. SessionLayer can,
precisely because it is a man-in-the-middle you installed on purpose.

## What "zero trust" means here

Zero trust describes the access-decision model: no implicit network trust,
every session re-verified, every credential short-lived. It does not mean
trust nothing; the Gateway and the CAs are a fully-trusted
[Tier-0](../reference/glossary.md) component. The platform relocates trust,
from long-lived SSH keys scattered across hundreds of nodes and laptops into
one audited, hardened, short-lived-certificate control point.

If your threat model rejects any plaintext-visible intermediary, use
end-to-end SSH and accept the loss of recording and audit. That trade-off is
real, and this page states it rather than papering over it.

## What each component can see

| Component | Public surface | Sees SSH plaintext? | Holds long-lived secrets? |
|---|---|---|---|
| Control Plane | HTTPS: API, Dashboard-facing endpoints, OIDC pages | No, never | CA key references (private keys live in the database under a KEK, or in Azure Key Vault or AWS KMS for the three SSH CAs); no session keys |
| Gateway | SSH (users), WSS (agents) | Yes, the only component that does | its own renewable mTLS identity; per-session keys that never persist |
| Agent | none (outbound only) | No (it splices ciphertext) | its renewable mTLS identity |

The load-bearing invariant is "only the Gateway sees session plaintext",
not "the Control Plane is private" (it is not; it serves your users'
browsers). Consequences, each pinned by a test in the sign-off suite:

- The Control Plane never receives an inner-leg private key: the Gateway
  generates the per-session keypair and sends only the public key for
  signing (with Vault, the sign-only endpoint, never one that returns
  keys).
- Recordings are sealed to the
  [customer recording key](../reference/glossary.md) before upload. The
  Control Plane holds only your public key; replay decrypts in your
  browser. A compromised Control Plane, a malicious platform admin, or
  SessionLayer itself can read recording metadata, never content or
  keystrokes.
- Session bytes never traverse the coordination bus in HA, and telemetry
  spans carry IDs and durations, never content.

## The promises (deliberate non-behaviors)

Eight things the platform must not do, re-verified in the production
sign-off (seven by direct negative tests; the eighth, the GitOps
reconciler touching runtime state, is held by that component's deliberate
non-existence):

1. No long-lived SSH key is ever a standing access path. All access rides
   short-lived certificates; a bare key offered as standing auth is
   refused.
2. No host or node identity is ever trusted on first use in the platform's
   own verification: node enrollment requires a host anchor, an unknown
   host key aborts the session in both connectivity models, and Agent and
   Gateway enrollment are anchored too, never TOFU. The boundary is that how
   your users' SSH clients verify the Gateway's own front-door
   host key is client configuration, which no server can force. Distribute
   the Gateway's host-key material and require strict checking in managed
   client configs (see the Gateway-verification section of
   [SSH access](../user-guide/ssh-access.md); the ProxyJump risk below is
   the same boundary).
3. The Control Plane never observes session plaintext.
4. A deny, lock, or authorization decision never fails open. Allow may fail
   open in narrow, documented ways; deny always fails closed, and deny
   wins, including when the Control Plane is down, when the lock feed is
   degraded, and in break-glass mode.
5. Session bytes never ride the coordination bus.
6. No GitOps reconciler mutates runtime state (locks, sessions, grants):
   GitOps is not shipped at all, see [the FAQ](../faq.md).
7. The Control Plane never issues an inner-leg private key.
8. Source IP is never positive evidence of identity: everywhere it appears,
   it can only reduce access.

Number 4 is the safety spine and worth restating operationally: locks live
on an actively pushed deny-list that every Gateway holds locally, so
revocation keeps working under total datastore loss; a Gateway that cannot
confirm its deny-list refuses what it cannot verify.

## Port forwarding and X11: granted, bounded, metadata-only

Port forwarding (`ssh -L`/`-R`) and X11 are admitted only when the
session's signed grant carries the matching capability
(`port_forward_local`, `port_forward_remote`, `x11`). There is no
Gateway-side switch of any kind; the grant is the sole mechanism, verified
the same way as every other capability. Two independent controls hold the
line: the Gateway's per-channel admission gate, and the inner-leg session
certificate, which carries `permit-port-forwarding` / `permit-X11-forwarding`
only for granted capabilities and never `permit-agent-forwarding`, so even
if the Gateway's own gate were somehow bypassed, the node's `sshd` refuses
an unpermitted forward on its own. Agent forwarding stays refused always,
everywhere, by design.

A granted forward is not a network escape: the node dials a local
forward's target and hosts a remote forward's listener, so a tunnel
reaches only what the node itself can reach, the same boundary your
node-level rules already assume. Locks tear down live tunnels like any
other channel, and tunnels count against the per-connection channel cap.

Forwarded bytes are opaque, a database protocol, an HTTP API, an X11
session, with no universal decode and no way to redact, so capturing them
raw would be a materially weaker privacy posture than the platform's
purpose-decoded, customer-key-sealed recordings. Forwarded content is
therefore never captured: the sealed recording carries tamper-evident
open/close markers, and the audit stream gets one metadata event per
tunnel (capability, direction, target, byte counts, duration), delivered
when the session's recording finalizes, the same timing as file-transfer
audit ([Audit events](../reference/audit-events.md)). If you need content
inspection of forwarded traffic, put an inspecting proxy at the target.
SessionLayer tells you a tunnel existed, where it went, and how much moved,
not what it said.

## Accepted risks, in plain language

Every risk below was weighed deliberately against its operational lever,
not waved through. The big ones first, each with your operational lever.

### Break-glass user presence is enforced by the key, not the server (BG-1)

The Gateway's SSH stack verifies possession of a break-glass FIDO2 key but
cannot assert the touch (user-presence) flag server-side; the library
provides no seam for it. A break-glass key provisioned without
touch-required could therefore be exercised silently by malware on the
operator's machine. Your lever: provision break-glass keys touch-required,
always. This is a hard [deployment precondition](hardening.md), and the
compensating controls (alert on every use, forced strict recording,
mandatory review, lock supremacy, time-boxing) all stand regardless.
Original severity high; accepted with the precondition.

### Device-flow phishing has an inherent residual

An attacker can initiate an OIDC device flow and social-engineer a victim
into approving it, a property of the device grant itself, industry-wide.
SessionLayer's posture: device flow is fallback-only (certificates and keys
are primary), the verification page is a full PKCE relying party, the
approving browser's source context is correlated and audited, and strict
approver-IP enforcement exists but defaults off (exact matching over-denies
NAT/mobile users). Your lever: enable enforcement where your population
allows; train the code-matching habit.

### Tamper evidence is hash-chain + WORM, not an external anchor

Audit events and recordings are hash-chained and land in object-locked
storage; any mutation, removal, or reorder is detectable. But the audit
chain head lives in the same Postgres as the data, so an attacker with full
database superuser control who also defeats the append-only trigger could
rewrite history and its chain. The externally-anchored Merkle root that
would defeat even that is deliberately deferred and not shipped. Do not
design your compliance story around it. The same stance appears in the
supply-chain verifier: release transparency is proven by Rekor's signed
timestamp, not by a Merkle inclusion proof. Your levers: compliance-mode
WORM, the off-box SIEM forward (your copy of the chain, outside the blast
radius), a restricted database role, and the node-local `sshd` second
trail.

### A sustained partition can under-count session slots (AR-GW-LEASE-PARTITION)

If a Gateway loses the Control Plane for longer than about 22.5 minutes
(shipped defaults) while sessions run on, the
[session-limit](../admin-guides/session-limits.md) accounting can
transiently under-count those slots until the sessions really end. No
over-admission occurs during the partition (new sessions fail closed), the
hard cap holds whenever the Control Plane is reachable, and each occurrence
is visible in the reaper/lifecycle meters. This is inherent: a partitioned
Gateway cannot hold fleet-wide accounting, and the alternative, counting
unreachable Gateways' leases as live forever, turns every partition into a
permanent capacity leak.

### A JIT grant does not inherit a rule's source-IP narrowing

`permit_cidrs` on a standing allow rule narrows that rule and nothing else.
An approved [JIT](../admin-guides/jit-access.md) grant is evaluated as its own
allow, carrying no source condition, so a location control expressed only that
way does not constrain where a JIT connect may come from. This is inherent to
the model: a grant is an out-of-band human approval keyed on requester, node
and login, the policy carries no network-scope field, and inheriting one from
an unrelated standing rule would refuse approvals an approver did sanction.
The obvious workaround does not work, and cannot be made to. A source
condition on a `deny` rule is never evaluated, so expressing the range as a
deny denies from everywhere rather than from outside it. That is deliberate:
gating denies on source once allowed an unknown or out-of-range source to drop
a deny altogether, making source IP positive evidence that removed a block, and
a deny which ignores source is the fix. Your lever is therefore the only one
that can exist: the Gateway's `ssh.source_ip_allowlist`, applied at TCP accept
before any SSH banner and so ahead of rules, JIT and break-glass alike. See
[RBAC](../admin-guides/rbac.md).

### Tunnel-only sessions can idle out while genuinely in use

Forwarded port-forward and X11 bytes are never captured, and they do not
stamp the idle clock either, so a session carrying only `-L`/`-R`/X11 traffic
and no shell activity can reach `ssh.inner.max_session_idle_secs` while it is
still doing work. The failure direction is safe: it ends sessions too eagerly
and never extends access. Your lever, and the one that matters: do not raise
that timeout fleet-wide to compensate. Doing so weakens the idle bound for
every interactive shell, trading a real security property for convenience.
Size it for shells, and expect long-lived pure tunnels to reconnect.

### ProxyJump's no-TOFU guarantee depends on client configuration

On the ProxyJump path the Gateway presents a host-CA certificate, but SSH
servers must also advertise their plain host key: a client without the
`@cert-authority` line, running with lax host-key checking, would silently
trust-on-first-use the Gateway's own key. The server cannot force
client-side verification; no SSH server can. Your lever: distribute the
`@cert-authority` line and require `StrictHostKeyChecking yes` in managed
client configs, and pre-provision the Gateway's own front-door host key the
same way, per the Gateway-verification section of
[SSH access](../user-guide/ssh-access.md) (promise 2 above scopes what "no
TOFU" does and does not cover client-side).

### Compliance-mode erasure is crypto-shred, and only you can do it

A compliance-WORM recording cannot be deleted by anyone, including the
platform, before its retention period expires (retention is yours to set;
keep it at or above your regime's floor). Within that window, GDPR-style
erasure for such a recording reduces to destroying your customer recording
key material, which is in your hands, not SessionLayer's. This is the same
property that makes recordings unreadable to the platform; you cannot have
one without the other. If your regime requires erasure of individual
recordings, run governance mode.

### Recording content boundaries

Keystroke capture means secrets typed at prompts are captured: sealed to
your key, unreadable to the platform, but present in the recording you can
decrypt. Treat recording replay authority accordingly. Also, legacy
`scp`-over-exec transfers land their raw bytes in the terminal capture
(modern SFTP-based transfers are content-free, names/sizes/hashes only),
and a replay/export signed URL, though single-object, ciphertext-only, and
5-minutes short, cannot be revoked within its lifetime. Forwarded
port-forward/X11 traffic is the inverse case: never captured at all,
metadata only (see the forwarding section above).

### Tier-0 hardening has enumerated residuals

The Gateway/Agent sandbox (privilege drop, seccomp, Landlock, coredumps
off) carries documented edges: kernels without Landlock degrade loudly
instead of refusing to boot, on both components, unless you opt out with the
Gateway's `hardening.landlock.required` or the Agent's
`--require-full-landlock` (network-egress confinement needs Linux 6.7 or
newer, notably on arm64); opt-in OTLP telemetry threads start before
Landlock's domain in one path (backstopped by the NetworkPolicy and
seccomp); `ioctl` and `clone3` cannot be fully narrowed by seccomp (bounded;
no tty fd is exposed, and namespace escapes are killed). Swap is a separate
exposure: disable or encrypt it on Gateway hosts. Your lever: the
[hardening checklist](hardening.md), the OS/container layer exists
precisely to catch what the in-process layer cannot.

## The full residual inventory

The remaining accepted risks on the books, lower severity,
engineering-level, kept here so nothing is discoverable only by reading
source. This table is the register.

What it lists is residual *risk*: something with operator-visible
consequence, whether or not you have a lever for it. Review observations that
changed no behaviour and expose nothing are deliberately not here, because
listing them would imply an exposure that does not exist.

This list was last reconciled against the shipped source on 28 July 2026:
every entry below was re-read against the current code, anything since fixed
was dropped rather than carried forward, and nothing here is phrased as
expiring on a future event.

Three entries are the exception, because they describe a measurement or a
latent path that no reading of the source settles, and they say so where they
appear: the first-boot timing figure, the certificate-serial-allocator note,
and the identity-renewal desync latency claim, whose compensating control was
confirmed even though the path itself was not reproduced. Read the date above
as how stale this page might be.

| Component | Sev | Plain meaning |
|---|---|---|
| CP | med | the restricted `cp_runtime` DB password is set once at first migration from a placeholder, ships with a dev default, and has no in-app rotation. Set a real one before first boot and rotate via `ALTER ROLE` ([hardening](hardening.md)); blast radius is capped by the role's grants |
| CP | med | machine-token and OIDC-state keys are per-instance. In HA, set the shared state HMAC key and expect machine tokens to be instance-local ([High availability](../admin-guides/high-availability.md)) |
| CP | med | CA rotation does not verify your fleet's trust distribution finished before the old key drains. Sequence your config management ([Certificate authorities](../admin-guides/certificate-authorities.md)) |
| CP | med | if audit partition create-ahead lapses for months, recovering rows from the DEFAULT partition is a documented manual DBA procedure; inserts never fail meanwhile |
| CP | med | some config families (CAs, node/JIT/capability policies, service accounts, break-glass) have no read-only permission; reading them requires the management permission |
| CP | med | replay/export URLs are un-revocable within their 5-minute TTL (ciphertext-only, single-object) |
| CP | low | authorization loads the full rule/lock set per decision; O(rules) per connect, fine at realistic fleet sizes |
| CP | low | there is no per-capability deny primitive; capabilities are withheld by omission (default-deny per capability) |
| CP | low | a hypothetical malformed lock target stored outside the API would match everything (fail-closed over-blocking; API ingest rejects such targets) |
| CP | low | platform RBAC is additive-only, no deny bindings; remove bindings or use a lock |
| CP | low | the printed-once first-admin credential has no clock expiry; it self-disables on claim or once any admin exists. Claim it promptly |
| CP | low | that same credential is written to the Control Plane's log at first boot, because before any admin exists there is no other channel to a human. Log shipping attached to a fresh Control Plane captures it, and it stays in the log store after the claim. Claim promptly and treat first-boot logs as secret, or name an OIDC subject in configuration, which prints nothing at all ([install](../installation/control-plane.md)) |
| CP | low | a JIT grant revoked at the instant a session activates can be recorded as already-active rather than refused. Bounded by the Gateway's identity-scoped teardown on the next lock-feed push, the same "an allow may briefly fail open, a deny never does" model used throughout. The concurrency was reasoned about rather than proven, so treat the bound as unproven rather than disproven |
| CP | low | auth rate limiting is fixed-window; a boundary-straddling burst can pass about 2x the limit momentarily |
| CP | high | authentication rate limiting is keyed on the client address, and a request that reached the Control Plane through an L7 proxy presents one it cannot resolve, so every client behind that proxy shares a single bucket. On shipped configuration one unauthenticated caller can spend the whole allowance and deny interactive sign-in, device approval and machine-token issuance to everyone behind the same proxy. Stripping client-supplied forwarding headers does not prevent it: a correctly behaving proxy inserting the true address produces the same unresolved value. Your lever: cap each source IP at the ingress, which raises exhausting the bucket to `ceil(limit / per-source-cap)` distinct sources and makes the real exposure materially smaller. Graded on the shipped state rather than the mitigated one, because that lever sits outside the product where nothing verifies or warns about it, and because a *global* ingress cap in place of a per-source one is worse than none, adding a second shared bucket one hop upstream |
| CP | low | REST mTLS accepts a revoked-but-unexpired internal client cert (no CRL/OCSP); leaves are short-TTL and authorization still requires an explicit binding |
| CP | low | mTLS agent join does not check your operator PKI's CRL/OCSP at bootstrap; the resulting platform credential is lockable regardless |
| CP | low | OIDC discovery/JWKS timeouts are fixed literals and a changed `jwks_uri` needs a restart |
| CP | low | an identity resolved via device flow carries no OIDC group claims into that authorization; group-only rules may not match a device-flow session, identity-named rules are unaffected |
| CP | low | certificate serials have no unique/monotonic allocator (no KRL story); revocation is by lock and short TTL, not serial. Carried forward without re-checking against the current source |
| CP | low | first boot blocks while CA cold start, bootstrap and audit partitioning run. About 150 s is a measurement taken on one machine, not a bound the platform holds to, so size your startupProbe with margin above it rather than to it ([hardening](hardening.md)) |
| CP | low | two exactly concurrent requests with the same Idempotency-Key can both execute (retries after a response are safe) |
| CP | low | any DB integrity violation on config writes surfaces as a 409 name-conflict, occasionally mislabeling the cause |
| CP | low | no dry-run, bulk apply, revision history, or list filtering on the config API |
| CP | low | if an object-store delete fails after the row is claimed, a pruned-marked row can briefly coexist with the (encrypted) object, logged for reconciliation |
| CP | low | legal-hold custody and governance delete share one permission (`recording:delete`), no separation of duties between them |
| CP | low | a scoped-only auditor cannot list/discover recordings (fail-closed; they can still replay a specific in-scope one) |
| CP | low | replay and export both amount to a full-object ciphertext download; the permissions differ in name, not power |
| CP | info | outer-leg user-certificate verification supports ECDSA user CAs only |
| CP | info | the resolved identity/groups/source IP in an authorization request are asserted by the mTLS-authenticated Gateway, part of the Tier-0 trust, not an independent check |
| CP | info | a documented set of deliberate OIDC/OAuth deviations (for example, `at_hash` unvalidated because the access token is discarded) |
| GW | low | the recording cipher binds each frame's index but not the total count, so trailing-frame truncation of a stolen ciphertext decrypts cleanly; the CP-held whole-object digest and WORM catch it on the record of truth |
| GW | med | break-glass offline codes and tokens transit the Gateway heap in non-zeroized copies (unlike recorder and inner-key material, which is scrubbed); coredumps-off and no-swap are the compensating controls |
| GW | med | a datastore substitution that serves a successfully-read but empty lock snapshot on reconnect would shrink a Gateway's deny-set; the feed's epoch signal is advisory, not authoritative. The snapshot replace stores the incoming epoch without comparing it and clears the map with no empty-snapshot guard; losing the feed is the opposite case and retains the deny-set. Exploiting it means substituting the datastore behind an mTLS-authenticated feed, from inside the Tier-0 boundary |
| GW | med (practically low) | the `rsa` crate remains in the lockfile as an uncompiled optional dependency (RUSTSEC-2023-0071 scanner noise; never built into the binary) |
| GW | low | OTPs are zeroized in the Gateway's handler, but the gRPC serialization buffers that carried them are not |
| GW | low | two versions of the `ssh-key` crate coexist (the SSH library's boundary vs the platform's own use) |
| GW | low | a fleet-wide lock's teardown fans out synchronously over the affected channels; at very large fleets this can bunch. Reconnect backoff is separately jittered, so reconnects themselves do not herd |
| GW | low | the inner-leg PTY request does not ask for a reply, so a node-side PTY allocation failure is silently swallowed rather than surfaced |
| GW | low | a latent busy-renew path in Gateway identity renewal could desync the generation counter; it surfaces fail-closed as a repair-needed lock. Renewal refuses to adopt a mismatched generation and stops for repair rather than continuing, which is the compensating control the acceptance rests on, and that control was confirmed in the source. Whether the racing path is still reachable was not reproduced |
| GW | low | by-design note: the SSH library locally checks certificate expiry and self-signature ahead of the Control Plane's authoritative checks |
| GW | low | the readiness surface is shallow, so a wedged process can still answer it, and on bare-metal systemd nothing restarts it. On Kubernetes the shipped `tcpSocket` liveness probe covers this; on bare metal add `WatchdogSec` plus a heartbeat, or an external check |
| GW | info | the PROXY v2 parser caps the address block at a fixed size |
| GW | info | the signed decision context does carry a gateway id, but the Gateway never checks it against its own identity, so what actually binds a decision to the Gateway that asked for it is the mTLS channel rather than the signature |
| Agent, GW | low | the sandbox residuals described above (Landlock degrade, OTLP threads, `ioctl`/`clone3` breadth) |
| Agent | low | the Agent verifies its own binary and then executes it, so a file swapped in between the two is not caught. Inherent to any check-then-use on a writable path, and the residual that survives after the install path's own verify-then-swap window was closed. An attacker who can write the install directory could replace the binary outright, so own that directory root-only and keep it non-writable by the agent user |
| Agent | low | the `SHA256SUMS` file published with a release is not itself signed and is not covered by the release provenance, so it carries no integrity guarantee of its own and anyone able to write to the repository could replace it. Checking a download against it proves only that the two agree. The real guarantee is the separately signed binary and SBOM, so verify those signatures rather than relying on the checksum file ([supply chain](supply-chain.md)) |
| Agent | low | released artifacts embed a version string that can disagree with the tag they were published under, so `--version` may not match the release you fetched. Security-neutral, because signature verification keys off the signed tag and never the embedded string, but you cannot tell that from the mismatch alone |
| Agent | low | release transparency via Rekor signed timestamp only, no Merkle inclusion proof (fails closed if the timestamp is absent) |
| Agent | info | independent rebuilds must match documented preconditions (pinned toolchain, `protoc` version); some build inputs are not pinned by the workflow itself |

## What was proven

Every requirement the platform commits to is mapped to a direct test,
and the nine load-bearing invariants each carry a break-it test that
fails if the invariant is removed: deny-fails-closed, lock supremacy, no
self-approval, inner-key custody, customer-key unreadability, no-TOFU,
single-use tokens, clone detection, verify-before-run. Two requirements are
gaps rather than proofs, both concerning the GitOps reconciler, which was
descoped by decision and is not built or documented as available.

> **Note:** treat the summary above as a statement of intent you should
> verify rather than as evidence you can audit from this repository alone.
> What you *can* check from here is each invariant's test in the component
> repositories, which is where the break-it tests live.

The verdict that accompanies this: production-grade under the operator
preconditions, which is the next page.

## Next

- [Production hardening](hardening.md): the preconditions, as an ordered
  checklist.
- [Supply chain](supply-chain.md): verifying that what you run is what was
  built.
- [Session recording](../admin-guides/session-recording.md): the
  customer-key seal in practice.
- [FAQ](../faq.md): the short answers, including "can staff read my
  recordings?"
