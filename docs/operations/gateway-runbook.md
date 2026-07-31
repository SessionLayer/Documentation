# Gateway runbook

The Gateway logs structured events through `tracing` (verbosity via `RUST_LOG`,
default `info`). Correlate everything by `session_id`, the join key into the
[audit stream](../admin-guides/audit.md), the recording, and the traces.

Many "failures" below are deny-wins working correctly. Before treating a
refusal as an outage, check whether the Gateway is refusing something it
genuinely cannot verify.

## Session and lock-feed reasons

| Log | Meaning | Action |
|---|---|---|
| `reason=lock_feed_unhealthy` | the pushed deny-list stream from the Control Plane is down; the Gateway refuses what it cannot verify (new registrations, dial-backs) | check the CP gRPC endpoint (`:9443`) and the `LockFeed` stream. Self-heals on reconnect (0.5-10 s). Persistent means the CP is down or the network is partitioned |
| `reason=breakglass_lock_feed_unhealthy` | a break-glass channel refused because the lock feed is unhealthy. Correct fail-closed behavior: the Gateway cannot confirm the absence of a lock | same as above. Existing channels run to grant expiry |
| `outcome=recording_unavailable` (`break_glass=true` on the break-glass variant) | recording could not start; strict mode, always forced for break-glass, refuses the session | restore the recording path: confirm the customer key is present and the WORM store (S3/MinIO) is reachable, see [Session recording](../admin-guides/session-recording.md) |
| `reason=breakglass_no_grant_expiry` | the CP signed a break-glass allow without an expiry; refused because an override must be time-boxed | a CP contract or config issue, check the break-glass policy TTL |
| `reason=authorization_denied`, `break_glass=true` | a break-glass authorize was denied, usually a matching lock (deny wins) | correlate with the CP [decision log](../admin-guides/audit.md). This is policy, not a fault |
| `break-glass auth resolved to a non-BREAKGLASS access model` (warn) | token mis-binding or contract drift between the Gateway and CP | investigate. This should never happen in a healthy fleet |
| `at connection capacity; dropping` (warn) | the outer leg hit `ssh.max_connections` and refused a handshake at accept. There is no queue, so this is the saturation signal, not a latency rise | raise the cap and the file-descriptor limit together, or add a Gateway. See [Capacity planning](capacity-planning.md) |
| `non-sk-ecdsa security key offered; break-glass supports only sk-ecdsa` (warn) | an operator offered, for example, an `ed25519-sk` key for break-glass; it was routed to the ordinary pin path | re-provision the break-glass key as `ecdsa-sk`, see [Break-glass access](../admin-guides/break-glass.md) |

The high-priority break-glass alert is raised CP-side at authentication, so a
break-glass use alerts even when no session follows it. The activation recorded
at Authorize is the durable review record and does not alert again. An alert
with no matching activation therefore means the credential was used but the
connection never got a decision, which is worth investigating on its own.
Correlate an alert to the Gateway session by `session_id`. Startup itself
rejects a break-glass config that isn't time-boxed:
`break_glass.mid_session_expiry` must be `grace_then_kill` or `hard_kill`;
`run_to_ttl` fails to boot.

## Agent-transport reasons

The user always sees the single generic "target node is offline or
unavailable". These reasons are the operator-side truth:

| Log | Meaning | Action |
|---|---|---|
| `reason=no_agent_registered` | no control channel for this node | is the Agent up? A registration logs `agent control channel registered` |
| `reason=dial_back_timeout` | the Agent did not complete the dial-back in the window | check Agent health and the network path from Agent to Gateway |
| `reason=agent_refused_or_local_dial_failed` | the Agent refused, or its local dial to the node's `sshd` failed | check the node's own `sshd` (the Agent reports `LOCAL_DIAL_FAILED` fast) |
| `reason=missed_heartbeats` (`agent missed two heartbeats; deregistering`) | the Agent is genuinely gone, two full intervals of silence. A slow-but-alive Agent is not killed | network or process death on the node; it reconnects with backoff once healthy |
| `reason=agent_signal_saturated` | the Agent is alive and answering, but its control-channel queue stayed full for the whole dial-back window: a capacity shed | do not chase the Agent, look at session concurrency to that node |
| `control channel superseded by a newer connection` | normal after an Agent reconnect, for example a healed partition. The newest connection wins by design | none |
| `refusing a locked agent (deny wins)` / `dial-back refused (fail closed)` | a lock covers this agent identity, or a dial-back token failed a binding check | expected during incidents. The token is never logged |
| `agent transport waiting for the lock feed before serving agents` (at boot) | the transport will not serve agents until the deny-list's first snapshot arrives, deny wins | resolves when the lock feed connects. If the CP is down, agent nodes are correctly offline |
| `SECURITY/OPS: adopted a certificate already expired at this Gateway's clock` | the CP issued this Gateway a certificate already expired here, clock skew beyond the TTL or a CP TTL misconfig. The renew loop stops rather than storm the CP | fix NTP or the CP certificate TTL, then restart the Gateway. Its identity will otherwise expire. Treat as urgent |

Startup validates this surface and fails closed: an `OUTBOUND_AGENT` node with
the transport disabled is offline, never a silent fallback to an agentless
dial; a wildcard `listen_addr` without an `advertise_url` refuses to boot
(Agents would be told to dial back to `0.0.0.0`). Several numeric bounds are
checked at the same time: `max_frame_bytes` (64 KiB default) must exceed
`inner.max_packet_bytes` (32 KiB default); `dial_back_timeout_secs` (10 s
default) must be less than `dial_back_token_ttl_secs` (30 s default);
`heartbeat_interval_secs` must fall within 1-300 s and `max_frame_bytes`
within 4 KiB-1 MiB, enforced on both the Gateway and the Agent so neither
side can boot healthy and then be refused by the other; and `max_connections`
(4096 default) must be at least `max_agents` (1024 default).

## High availability operations

### Draining

On `SIGTERM`/`SIGINT` the Gateway drains in order (`ha.drain.*`):

1. `/readyz` flips to 503, but the Gateway keeps accepting for
   `pre_drain_grace_secs` (default 5 s). Size your load balancer so
   `probe_interval * unhealthy_threshold` fits inside this grace, so the LB
   deregisters the Gateway before it stops accepting.
2. Accept loops stop; presence releases (a standby claims immediately) and
   agent control channels close (agents fail over).
3. Live sessions, both this Gateway's own ingress sessions and relays it
   serves as an owner, finish to `deadline_secs` (default 30 s) rather than
   being cut instantly.
4. Anything still live at the deadline tears down through the
   recorder-finalize path, so no recording is orphaned.

Point your load balancer's health check at `GET
ha.drain.readyz_addr/readyz` (200 `ready` / 503 `draining`); an empty
`readyz_addr` disables it. A relayed session does not survive the death of
the owner it runs on: the client reconnects cheaply via its pinned key and
re-routes to the new owner. A session whose node is owned by the ingress
Gateway itself is unaffected by any other Gateway's drain.

### Presence

Several Gateways may hold a live control channel for the same
node, but only one owns it. `presence: standby (another gateway owns this
node)` is normal, a non-owner keeps its channel warm and takes over the
instant the owner goes stale (about 30 s). A failed heartbeat means "not the
owner this tick": routing to it fails closed and self-heals next tick.

### Presence-refresh flap on large fleets

Symptom: a healthy Gateway holding
many nodes intermittently marks its own nodes stale; sessions fail closed;
ownership flaps. Cause: the per-node heartbeat fan-out (about 16-wide) did
not finish inside the staleness TTL, from a slow CP or a very large
per-Gateway ownership. Fixes, in order: cut CP heartbeat latency; add
Gateways; or raise `ha.presence.heartbeat_interval_secs` /
`staleness_ttl_secs` in lockstep on both the Gateway and the CP. Watch the
`presence heartbeat failed` rate.

### NATS

The built-in client is plaintext and unauthenticated, for a trusted
network only. Production fronts it with a TLS-terminating, authenticating
sidecar, or a NATS leaf-node TLS boundary, with subject authorization (only
the owner may subscribe to its own dial-back subject; only ingress Gateways
may publish), or substitutes a TLS-capable `CoordinationBackend` entirely.
If the broker demands TLS or auth the client cannot speak, it logs one loud
error and stops: HA signaling is then down and remote-owned sessions fail
closed until the broker or sidecar is fixed and the Gateway restarted. A
publish to an owner-less subject succeeds silently, so an absent owner
surfaces only as the bounded `ha.routing.relay_timeout_secs` fail-closed
wait. As defense in depth on top of that publish-side authorization, the
owner itself drops any stale or replayed signal (an `owner_nonce` older than
its current presence nonce) and caps concurrent relays per node. Relay
throughput as an owner shows up as `event=peer_relay_serving` /
`event=peer_relay_closed`.

## Hardening operations

Roll seccomp out in stages: set `hardening.seccomp.mode` to `log` first, run
a full shell/exec/SFTP session, and confirm `dmesg`/auditd shows no
unexpected `SECCOMP` line before flipping to `enforce`. In `enforce`, an
unlisted syscall returns `EPERM` (the operation fails, the process lives),
but the exploitation set (`execve`, `ptrace`, module load, and similar) is
`KILL_PROCESS`.

> **Warning:** a Gateway process killed by seccomp has attempted a syscall it
> never legitimately makes. Treat it as a compromise signal and start
> incident response, not as a flake to restart-loop.

A requested hardening step that cannot apply for an operator-controlled
reason (privilege drop while not root, an unknown user, a rejected rule)
aborts startup. Only a kernel lacking Landlock or seccomp entirely degrades,
loudly, in which case lean on the container layer.

Enabling `hardening.landlock` confines all filesystem access: a
dynamically-linked binary needs the library directories (`/lib`, `/lib64`,
`/usr/lib`, since NSS loads `libnss_*.so` at runtime), `/etc/resolv.conf`,
`/etc/nsswitch.conf`, `/etc/hosts`, `/dev`, `/proc`, and the config/CA paths
read-only. The recorder's ciphertext spool lives under the data directory
(`recording-spool/`), in the read-write set; a missing path denies that
access and can tear a session down.

Coredumps are off by default and should stay off: a core from this process
is session plaintext. A crash then leaves no core; only a Rust panic leaves
a backtrace in the structured log. To capture a core for a non-production
repro, set `hardening.disable_coredumps=false`. On a paranoid host, also set
`sysctl fs.suid_dumpable=0` and systemd-coredump `Storage=none`: a
pipe-based `core_pattern` handler ignores `RLIMIT_CORE` and reads
`PR_SET_DUMPABLE` instead, so the dumpable flag is the gate that actually
matters. Disable or encrypt swap on the most sensitive fleets separately.

## The node-local second trail

In the agent model, the node's own `sshd` log independently records every
accepted session certificate's key ID (`session_id` plus identity); this
needs `LogLevel VERBOSE` on the node, see [Nodes](../admin-guides/nodes.md).
To investigate a session from the node's side:

```bash
# SESSION_ID from the platform audit stream or the Gateway logs.
journalctl -u ssh | grep "$SESSION_ID"
```

The Agent deliberately does not forward this log; its independence from the
Agent is what makes it a second trail. Ship it through the node's normal log
pipeline.

## Next

- [Troubleshooting](troubleshooting.md): symptom-first index across the
  whole platform.
- [High availability](../admin-guides/high-availability.md): the concepts
  behind the drain and presence machinery.
- [Monitoring](monitoring.md): the alerts that route you into this page.
- [Agent runbook](agent-runbook.md): the other half of the agent-transport
  story.
