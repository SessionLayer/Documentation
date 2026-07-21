# Gateway runbook

The operator's field guide to the Gateway: what its log reasons mean, what to
do about each, and how draining, hardening, and the HA machinery behave when
you poke them. The Gateway logs structured events (`tracing`; verbosity via
`RUST_LOG`, default `info`) — correlate everything by `session_id`, which is
also the join key into the [audit stream](../admin-guides/audit.md), the
recording, and the traces.

A recurring theme below: many "failures" are the deny-wins design working.
Before treating a refusal as an outage, check whether the Gateway is
*correctly* refusing something it cannot verify.

## Session and lock-feed reasons

| Log | Meaning | Action |
|---|---|---|
| `reason=lock_feed_unhealthy` | the pushed deny-list stream to the Control Plane is down; the Gateway refuses what it can't verify (new registrations, dial-backs) | check the CP gRPC endpoint (`:9443`) and the `LockFeed` stream; self-heals on reconnect (0.5–10 s). Persistent → CP down or network partition |
| `reason=breakglass_lock_feed_unhealthy` | a break-glass channel refused because the lock feed is unhealthy — **correct** fail-closed behavior (it cannot confirm the absence of a lock) | same as above; existing channels run to grant expiry |
| `outcome=recording_unavailable` (`break_glass=true` on the break-glass variant) | recording could not start; strict mode (always forced for break-glass) refuses the session | restore the recording path: customer key present, WORM store (S3/MinIO) reachable — see [Session recording](../admin-guides/session-recording.md) |
| `reason=breakglass_no_grant_expiry` | the CP signed a break-glass allow without an expiry; refused because an override must be time-boxed | a CP contract/config issue — check the break-glass policy TTL |
| `reason=authorization_denied`, `break_glass=true` | a break-glass authorize was denied — usually a matching lock (deny wins) | correlate with the CP [decision log](../admin-guides/audit.md); this is policy, not a fault |
| warn: `break-glass auth resolved to a non-BREAKGLASS access model` | token mis-binding / contract drift between Gateway and CP | investigate — this should never happen in a healthy fleet |
| warn: `non-sk-ecdsa security key offered; break-glass supports only sk-ecdsa` | an operator offered e.g. an `ed25519-sk` key for break-glass; it was routed to the ordinary pin path | re-provision the break-glass key as `ecdsa-sk` ([Break-glass](../admin-guides/break-glass.md)) |

Break-glass **activation alerts are CP-side** (raised at authentication);
correlate an alert to the Gateway session by `session_id`.

## Agent-transport reasons (outbound-agent nodes)

The user always sees the single generic "target node is offline or
unavailable"; these reasons are the operator-side truth:

| Log | Meaning | Action |
|---|---|---|
| `reason=no_agent_registered` | no control channel for this node | is the Agent up? A registration logs `agent control channel registered` |
| `reason=dial_back_timeout` | the Agent didn't complete the dial-back in the window | node-side: Agent health, network path Agent→Gateway |
| `reason=agent_refused_or_local_dial_failed` | the Agent refused, or its local dial to the node's `sshd` failed | check the node's own `sshd` (the Agent reports `LOCAL_DIAL_FAILED` fast) |
| `reason=missed_heartbeats` (`agent missed two heartbeats; deregistering`) | the Agent is genuinely gone (two full intervals of silence — a slow-but-alive Agent is *not* killed) | network or process death on the node; it reconnects with backoff when healthy |
| `reason=agent_signal_saturated` | the Agent is alive and answering but its control-channel queue stayed full for the whole dial-back window — a capacity shed | don't chase the Agent; look at session concurrency to that node |
| `"control channel superseded by a newer connection"` | normal after an Agent reconnect (e.g. a healed partition); newest wins by design | none |
| `"refusing a locked agent (deny wins)"` / `"dial-back refused (fail closed)"` | a lock covers this agent identity, or a dial-back token failed a binding check | expected during incidents; the token is never logged |
| `"agent transport waiting for the lock feed before serving agents"` (at boot) | the transport won't serve agents until the deny-list's first snapshot arrives — deny wins | resolves when the lock feed connects; if the CP is down, agent nodes are correctly "offline" |
| `"SECURITY/OPS: adopted a certificate already expired at this Gateway's clock"` | the CP issued this Gateway a cert already expired here — clock skew beyond the TTL or a CP TTL misconfig. The renew loop **stops** rather than storm the CP | **urgent**: fix NTP or the CP certificate TTL, then restart the Gateway — its identity will otherwise expire |

Config sanity on this surface is enforced at startup, fail-closed: an
`OUTBOUND_AGENT` node with the transport disabled is simply offline (never a
silent fallback to an agentless dial); a wildcard `listen_addr` without an
`advertise_url` refuses to boot (Agents would be told to dial back to
`0.0.0.0`); heartbeat and frame-size bounds are validated on both ends.

## High availability operations

**Draining (SIGTERM).** The ordered sequence: `/readyz` flips to 503 while
the Gateway *keeps accepting* for `ha.drain.pre_drain_grace_secs` (default
5 s — size your LB so probe interval × unhealthy threshold fits inside it);
accepting stops; presence is released (a standby claims immediately) and
agent channels close (agents fail over); live sessions and served relays get
`ha.drain.deadline_secs` (default 30 s) to finish; stragglers are torn down
through the recorder-finalize path, so recordings are never orphaned. Health
endpoint: `GET <ha.drain.readyz_addr>/readyz` → `200 ready` / `503
draining`; unset disables it.

**Presence.** `presence: standby (another gateway owns this node)` is
normal — a non-owner keeps its channel warm and takes over when the owner
goes stale (~30 s). A failed heartbeat means "not the owner this tick";
routing to it fails closed and self-heals next tick.

**Presence-refresh flap (large fleets).** Symptom: a *healthy* Gateway
holding many nodes intermittently marks its own nodes stale; sessions fail
closed; ownership flaps. Cause: the per-node heartbeat fan-out (~16-wide)
didn't finish inside the staleness TTL — a slow CP or very large per-Gateway
ownership. Fixes, in order: cut CP heartbeat latency; add Gateways; raise
`ha.presence.heartbeat_interval_secs` / `staleness_ttl_secs` **in lockstep
on both Gateway and CP**. Watch the `presence heartbeat failed` rate.

**NATS.** The built-in client is plaintext/unauthenticated for a trusted
network — production fronts it with a TLS+auth sidecar
([High availability](../admin-guides/high-availability.md)). If the broker
advertises TLS/auth the client can't meet, it logs **one loud error and
stops** — HA signaling is then down and remote-owned sessions fail closed
until the broker/sidecar pairing is fixed and the Gateway restarted. A
publish to an owner-less subject succeeds silently, so an absent owner
surfaces only as the bounded `ha.routing.relay_timeout_secs` fail-closed
wait. Relay throughput as an owner: `event=peer_relay_serving` /
`event=peer_relay_closed`.

## Hardening operations

- **Roll seccomp out in stages** (`hardening.seccomp.mode`): `log` first, run
  a full shell/exec/SFTP session, confirm no unexpected `SECCOMP` line in
  `dmesg`/auditd, then `enforce`. In enforce, an unlisted syscall returns
  `EPERM` (the op fails, the process lives) — but the exploitation set
  (`execve`, `ptrace`, module load, …) is **KILL_PROCESS**.

> **Warning:** a `gateway` process killed by seccomp has attempted a syscall
> it never legitimately makes. Treat it as a compromise signal and start
> incident response — do not treat it as a flake and restart-loop it.

- **Fail-closed vs degrade:** a requested hardening step that can't apply for
  an operator-controlled reason (drop while not root, unknown user, rejected
  rule) **aborts startup**. Only a kernel lacking Landlock/seccomp entirely
  degrades, loudly (lean on the container layer there).
- **Landlock allow-set gotchas:** a dynamically-linked binary needs the
  library dirs (`/lib`, `/lib64`, `/usr/lib` — NSS loads `libnss_*.so` at
  runtime), `/etc/resolv.conf` + `/etc/nsswitch.conf` + `/etc/hosts`,
  `/dev`, `/proc`, and the config/CA paths read-only. The recorder's
  ciphertext spool lives under the data-dir (`recording-spool/`) — in the
  read-write set; a missing path denies that access and can tear sessions
  down.
- **Coredumps are OFF by default** and should stay off: a core from this
  process is session plaintext. A crash therefore leaves no core — only a
  Rust panic leaves a backtrace in the log. For a non-production repro you
  may set `hardening.disable_coredumps=false`. Belt-and-suspenders:
  `sysctl fs.suid_dumpable=0`, systemd-coredump `Storage=none`; and disable
  or encrypt swap on sensitive fleets.

## The node-local second trail

In the agent model, the node's own `sshd` log independently records every
accepted session certificate's key id (`session_id + identity`) — requires
`LogLevel VERBOSE` on the node ([Nodes](../admin-guides/nodes.md)). To
investigate a session from the node's side:

```bash
# SESSION_ID from the platform audit stream or the Gateway logs.
journalctl -u ssh | grep "$SESSION_ID"
```

The Agent deliberately does not forward this log — its independence from the
Agent is what makes it a second trail. Ship it via the node's normal log
pipeline.

## Next

- [Troubleshooting](troubleshooting.md) — symptom-first index across the
  whole platform.
- [High availability](../admin-guides/high-availability.md) — the concepts
  behind the drain/presence machinery.
- [Monitoring](monitoring.md) — the alerts that route you into this page.
- [Agent runbook](agent-runbook.md) — the other half of the agent-transport
  story.
