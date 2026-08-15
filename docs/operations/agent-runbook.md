# Agent runbook

The Agent is outbound-only: it dials out to your Gateways and the Control
Plane (CP), and exposes no inbound endpoint at all. Its signals are exit
codes, structured logs, and, optionally, OpenTelemetry spans.

## The exit-code contract

| Code | Meaning | Response |
|---|---|---|
| 0 | clean shutdown (SIGTERM/SIGINT) or `--once` completed | none |
| 1 | startup failure (config, enroll, persist, or terminal startup-renew) | check logs, usually transient CP or disk. A restart is fine |
| 2 | verify refused, the binary is not a verified SessionLayer release (`verify` / `update` / `--verify-self`) | do not run or install it, fail closed. See [Supply chain](../security/supply-chain.md) |
| 3 | generation mismatch, a possible credential clone; the CP auto-locked the identity | security incident, see below. Do not auto-restart into a loop |
| 4 | repair needed, the identity is locked, its certificate is unknown or rotated, or its generation is stale | re-provision through the join-token API, see below |

Codes 3 and 4 are reachable from any identity RPC that can return them, not
only a mid-loop renewal: a fresh enrollment refusal (for example, the node is
locked) and a startup renewal both classify the same way.

> **Warning:** configure the orchestrator so codes 3 and 4 page and do not
> silently restart. A blind restart loop turns a security signal into noise.
> On systemd: `Restart=on-failure` and `RestartPreventExitStatus=3 4`. On
> Kubernetes, `restartPolicy: OnFailure` will loop, so alert on the exit code
> instead.

## Alert: `SECURITY: generation mismatch on renewal ... auto-locked` (exit 3)

Two live copies of the credential forked the generation counter, a clone, or
a crash landed in the narrow persist window (below). Either way the CP
auto-locked the identity, with no auto-clear.

1. Determine clone vs. crash: is there a second Agent process, or a copy of
   the data directory (`/var/lib/sessionlayer-agent/identity.json`),
   anywhere? A copy you did not make is an incident.
2. Never release the lock without investigating; a possibly cloned
   credential must not renew.
3. Re-provision: issue a fresh join token (`POST /v1/join-tokens`,
   automatable, see [Nodes](../admin-guides/nodes.md)), wipe the node's data
   directory, and restart the Agent to re-enroll at generation zero.

The self-lock window is an accepted residual: persist-before-adopt makes an
Agent-local crash safe, but a crash between the CP committing generation N+1
and the Agent persisting it leaves them disagreeing, and the next renewal
looks like a clone and auto-locks. This is fail-closed, never silent
corruption; recovery is the same re-provision. The window is only the
RPC-response/persist gap.

## Alert: `REPAIR-NEEDED: renewal rejected ...` (exit 4)

An incident lock on the identity, an unknown or rotated client certificate,
or the CP has advanced past this credential's generation. Renewal will not
self-heal: the credential works until expiry but cannot renew. If the lock
was intentional, resolve the incident first; otherwise re-provision as above.

## Symptom: repeated transient renewal warnings, never succeeding

Likely a CA-rotation lockout or an unreachable CP. The Agent pins exactly the
CA chain from its last successful renewal; if the CP rotated its internal
mTLS CA and switched its server certificate to the new CA before this Agent
renewed onto it, or the Agent was offline past the overlap window, every
connect fails and the Agent retries until its certificate expires, then
needs re-provisioning. Check whether the CP's server certificate chains to
the anchors this Agent last stored. Operational rule: CP CA rotation must
keep the old issuer valid for server certificates until the whole fleet has
renewed.

## Symptom: the CP sees a renewal storm from one node

A short certificate TTL combined with a large skew backdate, or a CP clock
ahead of the node, makes every issued certificate born past its renewal
trigger. A post-renewal floor (`RENEW_MIN_INTERVAL`, 60 s) bounds the storm
to about one renewal per minute, but fix the root cause: the TTL/backdate
ratio, or NTP.

## Configuration

The Agent takes no config file, only CLI flags:

| Flag | Default | Notes |
|---|---|---|
| `--gateway-endpoint` (repeatable) | none | `wss://` only. Omit to run identity-only. Pass it twice or more for HA: the Agent holds one control channel per endpoint concurrently and does not mesh |
| `--gateway-failure-domain` (repeatable) | the endpoint's host | a rack/AZ label, zipped positionally with `--gateway-endpoint`. With two or more endpoints they must span two or more domains |
| `--min-control-channels` | 1 | the degrade-warn threshold. The default means single-instance: only the all-lost signal fires. An HA operator sets 2 or more, so a drop from 2 to 1 also warns |
| `--gateway-server-name` (repeatable) | `gateway` | the enrolled name whose serverAuth SAN the Agent verifies for the corresponding endpoint, zipped positionally. Give each real Gateway its own name, or one name to apply to all |
| `--splice-addr` | `127.0.0.1:22` | the node's local `sshd`. Validated as loopback at startup; the Agent refuses to boot otherwise (see below) |
| `--max-concurrent-splices` | 32 | a dial-back beyond the cap is refused, never queued. Shared across all control channels |
| `--drain-deadline-secs` | 30 | how long live splices may finish after the Agent stops taking new work |

Reconnect backoff is 1 s to 30 s exponential with about 50% jitter, per
channel, indefinitely.

### Control-channel diversity for HA

The Agent dials out to two or more Gateways in distinct failure domains and
holds a control channel to each at once; it does not mesh, the channels are
independent dial-outs. Startup validates this and fails closed: given two or
more `--gateway-endpoint` values, the Agent refuses to boot unless they span
two or more distinct failure domains (a duplicate endpoint, or two channels
in one domain, is not real HA). Two Gateways on the same host are one domain
by default; label them, or use different hosts. With a single endpoint and
the default `--min-control-channels 1`, the Agent runs against one Gateway
with no diversity requirement.

A `DIAL_BACK_REQUEST` arriving on the channel to a given Gateway may only
dial back to that same Gateway: in the HA routing model the node's owning
Gateway signals over its own channel, so the dial-back endpoint always
matches the arriving channel. A Gateway that names a different Gateway's
endpoint is refused before anything is dialled, so a compromised Gateway
cannot task the Agent into connecting to another one.

## Symptom: control channel reconnects in a loop (node flaps offline)

Every reconnect re-runs the full TLS + mTLS + preface. The log names the
cause:

| Cause | Fix |
|---|---|
| Gateway serverAuth cert does not chain to the Agent's CA, or its SAN does not match that endpoint's `--gateway-server-name` | with two or more Gateways, give each endpoint the name that Gateway is enrolled under (positionally zipped flags) |
| `VERSION_REJECT`, no common wire protocol version | an upgrade order problem, see [Upgrades](upgrades.md). The Agent never downgrades |
| `HELLO_ACK` proposing heartbeat/frame values outside the wire contract's bounds | fix the Gateway's agent-transport config; both ends enforce the bounds |

A node whose Agent is not connected shows as offline to users, the same
generic post-authorization outcome as any unreachable node.

## Alert: `ALL Gateway control channels are down — this node is UNREACHABLE`

Every diverse channel is gone at once, a broad outage or a misconfiguration
hitting all endpoints. This is the documented degrade: the platform
deliberately builds no bespoke fallback beyond two or more failure-domain-
diverse channels. While it lasts, recover the node with out-of-band tooling
(console, cloud serial); the platform never removed your native access. The
Agent keeps reconnecting with jittered backoff and logs `node is reachable`
when the first channel returns; no restart is needed.

## Symptom: dial-backs fast-fail with `LOCAL_DIAL_FAILED`

The node's own `sshd` is down or not listening on `--splice-addr` (default
`127.0.0.1:22`). The Agent reports it immediately rather than waiting out
the Gateway's window; users see the generic node-offline error. Fix the
node's `sshd`.

## Why `--splice-addr` accepts only loopback

A `DIAL_BACK_REQUEST` carries no splice target. The Agent splices only to
its own locally-configured `--splice-addr`, validated as loopback
(`127.0.0.0/8` or `::1`) at startup; a routable address, the wildcard
`0.0.0.0`, or a hostname (which would hand the destination to DNS) all
refuse to start. No Gateway, however compromised, can redirect the splice or
use the Agent as a pivot into the node's subnet. This is structural, not a
runtime check on untrusted input.

The Agent's non-root posture backs the same boundary from the other
side: it runs as uid 65532 and therefore cannot read the node's host
key (`/etc/ssh/ssh_host_*`, root-only), so spoofing the node's identity
needs node-root compromise, not merely a compromised Agent: putting an
agent on the node raises this bar rather than lowering it. The
Gateway's no-TOFU host verification is what actually catches a splice
to an impostor; the Agent is not a party to that check and cannot
weaken it. `Agent/tests/splice_e2e.rs` asserts this directly, running
`cat /etc/ssh/ssh_host_ed25519_key` as uid 65532 on the node and
requiring it to fail.

## The node-local sshd second trail

The node's own `sshd` log is a second, tamper-independent record of every
session. The inner-leg certificate's `key_id` is `session_id` plus
identity, and a node running `LogLevel VERBOSE` (set in the canonical
`testing/docker/sshd/sshd_config`, and required on real nodes) logs that
key ID on every accepted certificate.

The Agent deliberately does not forward this log. The whole value of a
second trail is that it does not depend on the Agent: the Agent neither
writes it nor can suppress it, so it stays trustworthy even if the Agent
is compromised. Routing it through the Agent would collapse that
independence. Ship the node's `sshd` log through the node's own pipeline
(journald or syslog to your collector), never through the Agent, and
correlate the two trails on `session_id`.

## Hardening symptoms

- Killed with `SIGSYS`, or a seccomp kill in the container runtime: a
  syscall outside the allow-list, either a genuine anomaly or, after a
  toolchain or dependency bump, a newly-needed syscall. Treat unexplained
  kills as a compromise signal first.
- `Landlock is UNAVAILABLE ... ACCEPTED-RISK` / `PARTIALLY enforced`: the
  kernel lacks Landlock (needs Linux 5.13 or newer; network egress needs
  6.7 or newer). A documented, loud degrade; seccomp and the loopback-only
  splice still hold. Deploy a newer kernel, or pass
  `--require-full-landlock` to make this fatal in regulated environments.
- Startup aborts with a hardening error (for example, the data directory is
  missing): fail-closed by design, the Agent will not run unhardened. Fix
  the path or its permissions.

A successful start logs `Tier-0 runtime hardening applied` with the Landlock
status, seccomp syscall count, and the egress allow-list.

## Deployment preconditions

- Non-root, always. The container runs uid 65532, and the binary refuses
  euid 0: a root Agent could read the node's host key and impersonate the
  node.
- The data directory must be node-local. The single-writer lock is `flock`,
  unreliable on network filesystems; never put
  `/var/lib/sessionlayer-agent` on NFS. Owned by the agent user; the
  manifest is written `0600`.
- Shutdown grace of at least about 40 s plus buffer
  (`terminationGracePeriodSeconds` / `TimeoutStopSec`): a SIGTERM during an
  in-flight renewal waits for the persist to finish. A mid-renew SIGKILL is
  crash-safe (atomic temp and rename) but not graceful.
- NTP-synced clocks: certificates are backdated for skew, and the Agent
  expires credentials conservatively.

A terminal identity outcome (exit 3 or 4) stops new dial-backs and closes
the control channel, but live spliced sessions are real users mid-work: they
drain up to `--drain-deadline-secs` (default 30) rather than being cut. The
log line is `terminal identity outcome — refusing new sessions and draining
live ones`; the process exits 3 or 4 once the drain completes.

## Observability

Exit codes and the `SECURITY` / `REPAIR-NEEDED` lines are the primary
signals; alert on both. With `OTEL_EXPORTER_OTLP_ENDPOINT` set, the Agent
emits spans (`agent.enroll`, `agent.renew`, `agent.dial_back`,
`agent.splice`) stamped with `sessionlayer.session_id`, so a trace pivots to
the audit chain and recording by the same ID. When export is on, the
collector's port is auto-added to the Landlock egress allow-list. Spans
carry IDs, enums, and durations, never tokens, keys, or session content.

## Next

- [Nodes](../admin-guides/nodes.md): join tokens and re-provisioning.
- [Supply chain](../security/supply-chain.md): exit code 2 and
  verify-before-run.
- [Troubleshooting](troubleshooting.md): the platform-wide symptom index.
- [Monitoring](monitoring.md): wiring these signals into pages.
