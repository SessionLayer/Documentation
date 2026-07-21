# Agent runbook

The operator's field guide to the Agent: the exit-code contract your
orchestrator must honor, the two security log lines that page, and the
diagnosis for every recurring symptom. The Agent is outbound-only and
deliberately exposes **no inbound endpoint** — its signals are exit codes,
structured logs, and (optionally) OpenTelemetry spans.

## The exit-code contract

| Code | Meaning | Response |
|---|---|---|
| 0 | clean shutdown (SIGTERM/SIGINT) or `--once` completed | none |
| 1 | startup failure (config / enroll / persist / terminal startup-renew) | check logs; usually transient CP or disk — a restart is fine |
| 2 | **verify refused** — the binary is not a verified SessionLayer release (`verify` / `update` / `--verify-self`) | do **not** run or install it; fail closed. See [Supply chain](../security/supply-chain.md) |
| 3 | **generation mismatch — possible credential clone**; the CP auto-locked the identity | **security incident** (below). Do not auto-restart into a loop |
| 4 | **repair needed** — identity locked / unknown-rotated cert / stale generation | re-provision via the join-token API (below) |

> **Warning:** configure the orchestrator so codes 3 and 4 **page and do not
> silently restart** — a blind restart loop turns a security signal into
> noise. systemd: `Restart=on-failure` +
> `RestartPreventExitStatus=3 4`. On Kubernetes, `restartPolicy: OnFailure`
> *will* loop; alert on the exit code instead.

## Alert: `SECURITY: generation mismatch on renewal ... auto-locked` (exit 3)

Two live copies of the credential forked the generation counter — a clone —
or a crash landed in the narrow persist window (below). Either way the CP
auto-locked the identity, with **no auto-clear**.

1. Determine clone vs. crash: is there a second Agent process, or a copy of
   the data directory (`/var/lib/sessionlayer-agent/identity.json`),
   anywhere? A copy you didn't make is an incident.
2. Never simply release the lock — a possibly-cloned credential must not
   renew.
3. Re-provision: issue a fresh join token
   (`POST /v1/join-tokens` — automatable, see
   [Nodes](../admin-guides/nodes.md)), wipe the node's data directory,
   restart the Agent to re-enroll at generation zero.

**The self-lock window (accepted residual):** persist-before-adopt makes an
Agent-local crash safe, but a crash between the CP *committing* generation
N+1 and the Agent *persisting* it leaves them disagreeing; the next renewal
looks like a clone and auto-locks. This is fail-closed, never silent
corruption — recovery is the same re-provision. The window is only the
RPC-response/persist gap.

## Alert: `REPAIR-NEEDED: renewal rejected ...` (exit 4)

An incident lock on the identity, an unknown/rotated client certificate, or
the CP has advanced past this credential's generation. Renewal will **not**
self-heal — the credential works until expiry but cannot renew. If the lock
was intentional, resolve the incident first; otherwise re-provision as
above.

## Symptom: repeated transient renewal warnings, never succeeding

Likely a **CA-rotation lockout** or an unreachable CP. The Agent pins
exactly the CA chain from its last successful renewal; if the CP rotated its
internal mTLS CA and switched its server certificate to the new CA before
this Agent renewed onto it (or the Agent was offline past the overlap
window), every connect fails and the Agent retries until its certificate
expires — then needs re-provisioning. Check whether the CP's server
certificate chains to the anchors this Agent last stored. Operational rule:
CP CA rotation must keep the old issuer valid for server certificates until
the whole fleet has renewed.

## Symptom: the CP sees a renewal storm from one node

A short certificate TTL combined with a large skew backdate (or a CP clock
ahead of the node) makes every issued certificate born past its renewal
trigger. A post-renewal floor bounds the storm to about one renewal per
minute — but fix the root cause: the TTL/backdate ratio, or NTP.

## Symptom: control channel reconnects in a loop (node flaps offline)

Every reconnect re-runs the full TLS + mTLS + preface. The log names the
cause:

| Cause | Fix |
|---|---|
| Gateway serverAuth cert doesn't chain to the Agent's CA, or its SAN ≠ that endpoint's `--gateway-server-name` | with ≥2 Gateways, give each endpoint the name that Gateway is enrolled under (positionally zipped flags) |
| `VERSION_REJECT` — no common wire protocol version | upgrade order problem — see [Upgrades](upgrades.md); the Agent never downgrades |
| `HELLO_ACK` proposing heartbeat/frame values outside the wire contract's bounds | fix the Gateway's agent-transport config; both ends enforce the bounds |

A node whose Agent is not connected is simply "offline" to users — the same
generic post-authorization outcome as any unreachable node.

## Alert: `ALL Gateway control channels are down — this node is UNREACHABLE`

Every diverse channel is gone at once — a broad outage or a misconfiguration
hitting all endpoints. This is the documented degrade: the platform
deliberately builds no bespoke fallback beyond ≥2 failure-domain-diverse
channels. While it lasts, recover the node with **out-of-band tooling**
(console, cloud serial) — the platform never removed your native access. The
Agent keeps reconnecting with jittered backoff and logs `node is reachable`
when the first channel returns; no restart needed.

## Symptom: dial-backs fast-fail with `LOCAL_DIAL_FAILED`

The node's own `sshd` is down or not listening on `--splice-addr`
(default `127.0.0.1:22`). The Agent reports it immediately rather than
waiting out the Gateway's window; users see the generic node-offline error.
Fix the node's `sshd`.

## Hardening symptoms

- **Killed with `SIGSYS` / a seccomp kill in the container runtime:** a
  syscall outside the allow-list — a genuine anomaly, or (after a
  toolchain/dependency bump) a newly-needed syscall. Treat unexplained kills
  as a compromise signal first.
- **`Landlock is UNAVAILABLE ... ACCEPTED-RISK` / `PARTIALLY enforced`:**
  the kernel lacks Landlock (needs Linux ≥ 5.13; network egress ≥ 6.7).
  A documented, loud degrade — seccomp and the loopback-only splice still
  hold. Deploy a newer kernel, or pass `--require-full-landlock` to make
  this fatal in regulated environments.
- **Startup aborts with a hardening error** (e.g. the data-dir missing):
  fail-closed by design — the Agent will not run unhardened. Fix the
  path/permissions.

A successful start logs `Tier-0 runtime hardening applied` with the
Landlock status, seccomp syscall count, and the egress allow-list.

## Deployment preconditions

- **Non-root, always.** The container runs uid 65532 and the binary refuses
  euid 0 — a root Agent could read the node's host key and impersonate the
  node.
- **Data directory node-local.** The single-writer lock is `flock`, which is
  unreliable on network filesystems — never put
  `/var/lib/sessionlayer-agent` on NFS. Owned by the agent user; the
  manifest is written `0600`.
- **Shutdown grace ≥ ~40 s + buffer** (`terminationGracePeriodSeconds` /
  `TimeoutStopSec`): a SIGTERM during an in-flight renewal waits for the
  persist to finish. A mid-renew SIGKILL is crash-safe (atomic temp+rename)
  but not graceful.
- **NTP-synced clocks** — certificates are backdated for skew, and the Agent
  expires credentials conservatively.

One availability behavior worth knowing in advance: a terminal identity
outcome (exit 3/4) stops **new** dial-backs and closes the control channel,
but live spliced sessions are real users mid-work — they drain up to
`--drain-deadline-secs` (default 30) rather than being cut. The log line is
`terminal identity outcome — refusing new sessions and draining live ones`;
the process exits 3/4 once the drain completes.

## Observability

Exit codes and the `SECURITY` / `REPAIR-NEEDED` lines are the primary
signals — alert on both. With `OTEL_EXPORTER_OTLP_ENDPOINT` set, the Agent
emits spans (`agent.enroll`, `agent.renew`, `agent.dial_back`,
`agent.splice`) stamped with `sessionlayer.session_id`, so a trace pivots to
the audit chain and recording by the same id. Spans carry IDs, enums, and
durations — never tokens, keys, or session content.

## Next

- [Nodes](../admin-guides/nodes.md) — join tokens and re-provisioning.
- [Supply chain](../security/supply-chain.md) — exit code 2 and
  verify-before-run.
- [Troubleshooting](troubleshooting.md) — the platform-wide symptom index.
- [Monitoring](monitoring.md) — wiring these signals into pages.
