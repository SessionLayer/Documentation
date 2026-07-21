# Gateway configuration

The Gateway reads one JSON configuration file. Point it at the file with `--config /path/to/gateway.json`
or the `SL_GATEWAY_CONFIG` environment variable; with neither set, built-in defaults apply (SSH
server disabled — a scaffold posture). This page lists every knob with its default, derived from
`gateway-core/src/config.rs` and drift-checked in CI.

Two properties hold everywhere:

- **Misconfiguration fails closed.** A misspelled or unknown key is a parse error, not a silently
  ignored setting. A named-but-unreadable file aborts startup — never a silent fallback to defaults.
- **Empty means off.** Listeners (`ssh.listen_addr`, `ssh.agent.listen_addr`,
  `ha.drain.readyz_addr`) are disabled when their address is empty.

A minimal production-shaped file:

```json
{
  "cp_mtls_endpoint": "https://cp.example.com:9443",
  "data_dir": "/var/lib/sessionlayer-gateway",
  "bootstrap": {
    "enrollment_token": "st-FAKE-ENROLLMENT-TOKEN",
    "ca_cert_path": "/etc/sessionlayer/cp-bootstrap-ca.pem",
    "gateway_name": "gw-1",
    "server_name": "controlplane"
  },
  "ssh": {
    "listen_addr": "0.0.0.0:22",
    "host_key_path": "/var/lib/sessionlayer-gateway/host_key"
  }
}
```

The line above shows a fake enrollment token; issue a real one from the Control Plane when you
[install the Gateway](../installation/gateway.md).

## Top level

| Key | Type | Default | Effect |
|---|---|---|---|
| `io_backend` | `epoll` \| `uring` | `epoll` | Async-I/O reactor for the byte-copy hot path. A `uring` request degrades to epoll when io_uring is unavailable — deny-safe. |
| `cp_endpoint` | string (URL) | `http://127.0.0.1:9090` | Legacy plaintext dev endpoint used only by the handshake smoke test. The production plane is `cp_mtls_endpoint`. |
| `cp_mtls_endpoint` | string (URL) | `https://127.0.0.1:9443` | The Control Plane mTLS gRPC endpoint (TLS 1.3). All authenticated RPCs go here. |
| `data_dir` | path | `/var/lib/sessionlayer-gateway` | Holds the persisted mTLS credential (leaf + key + CA chain + generation) and the single-writer lock. |

The remaining configuration lives in the `bootstrap`, `identity`, `ssh`, `ha`, and `hardening`
blocks below.

## Enrollment (`bootstrap`)

Omit the block entirely to leave the Gateway un-enrolled; set it to drive enroll-on-start. The
enrollment token is a secret — supply it out-of-band and never commit it. It is held in a
scrub-on-drop buffer and redacted from any debug output.

| Key | Type | Default | Effect |
|---|---|---|---|
| `bootstrap.enrollment_token` | string (secret) | — | The single-use, short-TTL enrollment token (issued by the Control Plane). |
| `bootstrap.ca_cert_path` | path | — | PEM trust anchor the Gateway pins to verify the Control Plane's server certificate pre-enrollment. A wrong-CA server is refused. |
| `bootstrap.gateway_name` | string | — | The stable Gateway name the token was provisioned for; bound into the CSR and issued certificate. A mismatch fails closed. |
| `bootstrap.server_name` | string | host of `cp_mtls_endpoint` | Server name (SNI/SAN) to verify the Control Plane certificate against. |

## Identity lifecycle (`identity`)

The renew-ahead loop for the Gateway's mTLS identity: renewal fires when a fraction of the
certificate TTL has elapsed, jittered to de-synchronise a fleet.

| Key | Type | Default | Effect |
|---|---|---|---|
| `identity.renew_ahead_fraction` | float 0–1 | `0.667` | Fraction of the certificate TTL that must elapse before renewal fires (renew with ~1/3 remaining). |
| `identity.renew_jitter_fraction` | float | `0.1` | ±jitter, as a fraction of the TTL, applied to the trigger. |
| `identity.startup_renew_below_fraction` | float | `0.5` | On startup, renew immediately if the remaining TTL fraction is at or below this. |
| `identity.connect_timeout_secs` | int (s) | `5` | Bound on establishing the gRPC transport to the Control Plane — fail-closed. |
| `identity.rpc_timeout_secs` | int (s) | `10` | Per-RPC deadline; a hung Control Plane never hangs the Gateway. |

## SSH front door (`ssh`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.listen_addr` | string | empty (disabled) | TCP listen address (`host:port`) for the outer SSH server. Behind a load balancer, bind `0.0.0.0:22` and set `ssh.proxy.lb_cidrs`. |
| `ssh.host_key_path` | path | empty | Persisted OpenSSH host key (ed25519). Empty generates an ephemeral key at startup — fine for tests; fix it in production to avoid client host-key churn. |
| `ssh.login_grace_secs` | int (s) | `300` | Login grace covering the whole outer handshake, including a slow OIDC device flow. Must exceed `ssh.device_flow.poll_timeout_secs`. |
| `ssh.handshake_timeout_secs` | int (s) | `10` | Bound on reading the PROXY v2 header before the SSH banner, so a stalling peer cannot hold an accept slot. |
| `ssh.max_connections` | int | `512` | Cap on concurrently handshaking connections; over the cap is dropped at accept. |
| `ssh.max_auth_attempts` | int | `6` | Per-connection cap on credential-resolution attempts (each is one Control Plane RPC). After the cap the connection is hard-rejected. |
| `ssh.source_ip_allowlist` | list of CIDR | empty (allow all) | Global source-IP gate, evaluated at TCP accept against the real client IP, before any SSH banner. Non-empty drops any source outside it. |
| `ssh.target_separator` | char | `%` | The username-encoding separator (`login%node`). |
| `ssh.node_dns_suffixes` | list | empty (off) | Wildcard-DNS domains: a matching suffix is stripped from the username's node half (`deploy%web-01.ssh.example.com` → `web-01`). Longest match wins; case-insensitive. |
| `ssh.cp_connect_timeout_secs` | int (s) | `5` | Bound on establishing the Control Plane mTLS transport for an auth/authorize RPC. |
| `ssh.cp_rpc_timeout_secs` | int (s) | `10` | Per-RPC deadline on every auth/authorize call; a hung Control Plane never hangs the SSH handshake. |

### PROXY protocol (`ssh.proxy`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.proxy.lb_cidrs` | list of CIDR | empty (off) | Trusted load-balancer CIDRs. Empty: PROXY protocol off, the TCP peer IP is the source. Non-empty: PROXY v2 is required from LB peers (missing/malformed rejected) and a non-LB peer is rejected outright — both directions fail closed. |

### ProxyJump host certificates (`ssh.proxy_jump`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.proxy_jump.enabled` | boolean | `false` | Terminate `ssh -J gw.example.com deploy@web-01` at the Gateway, presenting a host-CA-signed certificate for the node — no TOFU with one `@cert-authority` line. Off, a `direct-tcpip` forward is refused. |

### Device flow (`ssh.device_flow`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.device_flow.heartbeat_interval_secs` | int (s) | `10` | Keepalive cadence toward the SSH client while polling — below stock-client idle timeouts. |
| `ssh.device_flow.poll_timeout_secs` | int (s) | `180` | Overall device-flow deadline; on expiry the user gets "authentication timed out, please reconnect". Must be below `ssh.login_grace_secs`. |

### Node-facing leg (`ssh.inner`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.inner.connect_timeout_secs` | int (s) | `5` | Bound on the agentless TCP dial to the node; unreachable fails closed as "node offline". |
| `ssh.inner.handshake_timeout_secs` | int (s) | `10` | Per-step bound on the inner SSH handshake, user auth, and channel open; a stalling node aborts rather than parking on the idle timer. |
| `ssh.inner.window_bytes` | int (bytes) | `2097152` | Inner-channel initial flow-control window. |
| `ssh.inner.max_packet_bytes` | int (bytes) | `32768` | Inner-channel maximum packet size. |
| `ssh.inner.max_session_idle_secs` | int (s) | `900` | Idle bound on a live bridged session (both legs). Must be ≥ `ssh.login_grace_secs`. A tighter per-identity idle timeout from policy wins over this — tighten-only. |
| `ssh.inner.max_channels_per_connection` | int | `16` | Cap on session channels one connection may open (a local resource bound, distinct from session-limit policy). |

### Recorder (`ssh.recorder`)

Recording is mandatory by default: in strict mode a recording failure refuses or tears down the
session rather than running it unrecorded.

> **Warning:** `ssh.recorder.strict: false` lets sessions proceed in a documented degraded mode when
> recording setup or upload fails. It logs loudly, but sessions can then run unrecorded. Keep strict
> mode in production; break-glass sessions force strict regardless.

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.recorder.strict` | boolean | `true` | A recording setup/continuation failure refuses the session (fail closed). |
| `ssh.recorder.spool_dir` | path | unset | Directory for the ciphertext spool. Plaintext is never written to disk — only sealed frames. The daemon defaults it into a `data_dir` subpath so the spool sits inside the Landlock write set. |
| `ssh.recorder.spool_memory_threshold_bytes` | int (bytes) | `8388608` | Ciphertext held in memory before spilling to the spool — bounds RAM per session. |
| `ssh.recorder.max_object_bytes` | int (bytes) | `4294967296` | Hard cap on one recording's ciphertext object; exceeding it fails closed. |
| `ssh.recorder.frame_plaintext_bytes` | int (bytes) | `16384` | Plaintext buffered before a frame is sealed and flushed. |
| `ssh.recorder.upload_timeout_secs` | int (s) | `30` | Bound on the end-of-session PUT to the presigned WORM URL. |
| `ssh.recorder.upload_max_attempts` | int | `4` | Max attempts (including the first) for the upload; transient store faults retry with backoff. |
| `ssh.recorder.require_https` | boolean | `true` | Require an https WORM store URL. Set `false` only for a plain-http development MinIO. |
| `ssh.recorder.upload_ca_pem_path` | path | unset | PEM trust anchor for an https WORM store. Empty with an https URL fails the upload closed — no implicit web-PKI roots. |

### Re-evaluation and locks (`ssh.reeval`)

Per-channel policy recheck, lock-feed health, and what happens to a live session when its grant
expires.

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.reeval.max_decision_ttl_secs` | int (s) | `60` | Hard ceiling on the Control-Plane-supplied decision TTL; the effective TTL is the smaller, and `0` whenever the lock feed is unhealthy. |
| `ssh.reeval.grant_expiry_skew_secs` | int (s) | `30` | Clock-skew margin on grant expiry — a grant expires early. |
| `ssh.reeval.lock_expiry_skew_secs` | int (s) | `30` | Clock-skew margin on lock expiry — a deny expires late. Deny fails closed in both directions. |
| `ssh.reeval.lock_feed_unhealthy_after_secs` | int (s) | `30` | The lock feed is unhealthy after this long with no event or heartbeat; unhealthy forces per-channel re-validation. |
| `ssh.reeval.lock_feed_connect_timeout_secs` | int (s) | `5` | Bound on establishing the lock-feed mTLS stream. |
| `ssh.reeval.mid_session_expiry` | mode | `run_to_ttl` | What happens to a live standing/JIT session at grant expiry (modes below). A lock always overrides with immediate teardown. |
| `ssh.reeval.mid_session_grace_secs` | int (s) | `30` | Grace window for `grace_then_kill` between grant expiry and teardown. |

The three expiry modes — in every mode, new privileged channels are refused once the grant expires:

| Mode | Behaviour |
|---|---|
| `run_to_ttl` | In-flight channels run to their natural close. Least disruptive; the default for standing access. |
| `grace_then_kill` | Wait the grace window, then tear the session down. |
| `hard_kill` | Tear the session down immediately at expiry. |

### Break-glass (`ssh.break_glass`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.break_glass.enabled` | boolean | `true` | Whether this Gateway offers the break-glass authentication paths. Disabled, a break-glass credential simply does not resolve. |
| `ssh.break_glass.mid_session_expiry` | mode | `grace_then_kill` | Expiry behaviour for break-glass sessions, selected separately from `ssh.reeval.mid_session_expiry` — emergency sessions are time-boxed. |

Strict recording is always forced for break-glass sessions regardless of these knobs.

### Agent transport (`ssh.agent`)

The TLS 1.3 WebSocket listener Agents dial out to (client certificate required). The
gateway-to-gateway peer relay shares this listener.

| Key | Type | Default | Effect |
|---|---|---|---|
| `ssh.agent.listen_addr` | string | empty (disabled) | Listen address for the Agent transport. Off, an outbound-agent node is simply offline. Dev port is `9444`. |
| `ssh.agent.advertise_url` | string (URL) | derived from listen address | The `wss://` URL the Gateway tells an Agent to dial back to. |
| `ssh.agent.heartbeat_interval_secs` | int (s) | `20` | Ping cadence on the control channel; two missed intervals deregister the agent. |
| `ssh.agent.max_frame_bytes` | int (bytes) | `65536` | Max frame payload either peer may send. Must exceed `ssh.inner.max_packet_bytes` so a full SSH packet fits one frame. |
| `ssh.agent.dial_back_token_ttl_secs` | int (s) | `30` | TTL of a minted dial-back token. Must exceed the dial-back timeout. |
| `ssh.agent.dial_back_timeout_secs` | int (s) | `10` | How long to wait for a signalled Agent to open its stream before failing closed to "node offline". |
| `ssh.agent.handshake_timeout_secs` | int (s) | `10` | Bound on the whole TLS + WebSocket + preface handshake. |
| `ssh.agent.max_agents` | int | `1024` | Cap on live agent control channels. |
| `ssh.agent.max_connections` | int | `4096` | Cap on concurrently handshaking sockets, enforced before any TLS work — an unauthenticated peer cannot exhaust the Gateway. |

## High availability (`ha`)

Default is single-instance with an in-process signal bus and zero extra dependencies. Single and HA
modes run the same code paths; only the signal transport differs. See
[High availability](../admin-guides/high-availability.md).

| Key | Type | Default | Effect |
|---|---|---|---|
| `ha.mode` | `single_instance` \| `ha` | `single_instance` | Whether this Gateway runs alone or as one of several behind an L4 load balancer (enables the cross-gateway relay). |
| `ha.peer_relay_advertise_addr` | string | empty (derived) | The `host:port` a peer owner dials back for the direct byte relay. Empty derives it from the agent transport advertise URL — the relay shares that TLS listener. |

### Coordination bus (`ha.coordination`)

Carries only the dial-back signal — session bytes never traverse it.

| Key | Type | Default | Effect |
|---|---|---|---|
| `ha.coordination.backend` | `in_process` \| `nats` | `in_process` | The signal transport. In-process is the single-instance default with zero dependencies. |
| `ha.coordination.url` | string (URL) | — | NATS server URL (for example `nats://nats.internal:4222`). Required with the `nats` backend. |
| `ha.coordination.subject_prefix` | string | `sl` | NATS subject prefix. |

### Presence (`ha.presence`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ha.presence.heartbeat_interval_secs` | int (s) | `10` | How often this Gateway heartbeats ownership of every node it holds a live agent channel for. |
| `ha.presence.staleness_ttl_secs` | int (s) | `30` | Local owner-cache staleness bound. The authoritative staleness decision is the Control Plane's (`sessionlayer.ha.presence-staleness`). |

### Routing (`ha.routing`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ha.routing.relay_timeout_secs` | int (s) | `25` | How long the ingress Gateway waits for the owner to establish the direct relay before failing closed to "node offline". Sits above the owner's worst-case establish budget (~20 s) and well below the SSH login grace. |
| `ha.routing.cache_ttl_secs` | int (s) | `30` | Owner cache TTL. The per-session authoritative owner comes from the authorization response; the cache feeds staleness and observability. |

### Drain (`ha.drain`)

| Key | Type | Default | Effect |
|---|---|---|---|
| `ha.drain.pre_drain_grace_secs` | int (s) | `5` | After SIGTERM, report unready but keep accepting for this long, so the load balancer deregisters this Gateway before it stops listening. `0` stops accepting at once. |
| `ha.drain.deadline_secs` | int (s) | `30` | How long drain waits for live sessions to finish before finalizing recordings and exiting. |
| `ha.drain.readyz_addr` | string | empty (disabled) | `host:port` for the readiness surface (`GET /readyz`): `200` while serving, `503` once draining. |

## Runtime self-hardening (`hardening`)

In-process restrictions the `gateway` binary imposes on itself after binding its listeners. Every
sandbox step is off by default and independently toggled; see
[Production hardening](../security/hardening.md) for the recommended production profile. A step that
is requested but cannot be applied for a reason under your control aborts startup; only a
kernel-capability gap (no Landlock LSM, no seccomp at all) degrades with a loud warning.

| Key | Type | Default | Effect |
|---|---|---|---|
| `hardening.run_as_user` | string | empty (off) | User to drop to after binding — bind `:22` as root, run unprivileged. A name or bare numeric uid. Requested-but-not-root fails closed. |
| `hardening.run_as_group` | string | empty | Group to drop to; empty uses the resolved user's primary group. |
| `hardening.disable_coredumps` | boolean | `true` | Disables coredumps (`PR_SET_DUMPABLE=0`, `RLIMIT_CORE=0`) so a crash cannot spill SSH plaintext or keys to a core file. On by default. |

### Landlock (`hardening.landlock`)

Filesystem confinement (kernel ≥ 5.13): the process can reach only the configured paths, regardless
of file permissions.

| Key | Type | Default | Effect |
|---|---|---|---|
| `hardening.landlock.enabled` | boolean | `false` | Master switch. |
| `hardening.landlock.required` | boolean | `false` | Fail closed if Landlock cannot be fully enforced. Off degrades with a loud warning (backed by the container read-only rootfs); regulated deployments set it. |
| `hardening.landlock.read_only_paths` | list of path | empty | Absolute paths the Gateway may read (config, trust bundles, host key, `/etc/resolv.conf`, `/etc/ssl`). Missing paths are skipped with a warning. |
| `hardening.landlock.read_write_paths` | list of path | empty | Absolute paths the Gateway may read and write (the data dir, any recording spool). Keep tight. |

### seccomp (`hardening.seccomp`)

The syscall allow-list itself is fixed in code; only the posture is configurable.

| Key | Type | Default | Effect |
|---|---|---|---|
| `hardening.seccomp.mode` | `off` \| `log` \| `enforce` | `off` | `log` installs the filter but only logs unlisted syscalls (roll-out mode — no protection). `enforce` blocks unlisted syscalls with `EPERM`, and kills the process on a hard-deny set (`execve`, `ptrace`, module load, …) that signals compromise. |

> **Tip:** roll out seccomp with `hardening.seccomp.mode: "log"`, run representative sessions,
> check `dmesg`/auditd for unexpected syscalls, then flip to `enforce`.

## Environment

| Variable | Effect |
|---|---|
| `SL_GATEWAY_CONFIG` | Path to the JSON config file (the `--config` flag wins over it). |
| `RUST_LOG` | Tracing filter (default `info`). Logs never contain session plaintext or secrets. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Enables the OTLP trace exporter (unset ⇒ off). See [Metrics](metrics.md). |
| `OTEL_SERVICE_NAME` | Overrides the reported service name (default `sessionlayer-gateway`). |

## Next

- [Install the Gateway](../installation/gateway.md)
- [Control Plane configuration](config-control-plane.md)
- [Agent configuration](config-agent.md)
- [Ports](ports.md)
