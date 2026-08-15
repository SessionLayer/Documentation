# Capacity planning

Load lands in three places that scale independently: a Gateway carries
session bytes and runs out of file descriptors and memory, the Control
Plane runs one decision path per session and runs out of CPU and database
connections, and Postgres accumulates every row a session leaves behind
plus one serialized audit chain. The caps below are the shipped defaults.
The throughput they imply depends on your workload, so each section names
the meter or query that measures it in your own deployment.

## Measure these first

| Question | Signal |
|---|---|
| How loaded is a Gateway? | `sessionlayer.gateway.live_sessions` gauge, and the `at connection capacity; dropping` warn line |
| Is the Control Plane meeting its latency budget? | `sessionlayer_session_establishment_seconds_bucket`, p95 against the 250 ms boundary |
| Is the database pool the bottleneck? | R2DBC pool utilization and pending-acquire panel on the shipped Grafana dashboard |
| How fast is recording storage growing? | `runtime.recording_ref.size_bytes` over session hours (query below) |
| How fast is audit growing? | Row count per monthly `audit_event` partition (query below) |

Meter definitions are in [Metrics](../reference/metrics.md); the dashboard
and alert rules that plot them are listed in
[Monitoring](monitoring.md).

## Sessions per Gateway

A Gateway bounds concurrency with four caps, all in
[Gateway configuration](../reference/config-gateway.md):

| Cap | Default | Counts |
|---|---|---|
| `ssh.max_connections` | 512 | concurrently *handshaking* connections, dropped at accept over the cap. It does not bound established sessions |
| `ssh.inner.max_channels_per_connection` | 16 | Session channels multiplexed over one connection |
| `ssh.agent.max_agents` | 1024 | Live agent control channels (outbound-agent nodes homed on this Gateway) |
| `ssh.agent.max_connections` | 4096 | Sockets handshaking on the agent transport, enforced before any TLS work |

Over `ssh.max_connections` the listener drops the accepted socket at once
and logs `at connection capacity; dropping`. There is no queue, so that log
line is your saturation signal, not a latency rise.

An outbound-agent node caps its own side at 32 concurrent splices
(`max_concurrent_splices` in [Agent configuration](../reference/config-agent.md)),
so a single agent-model node cannot carry more than 32 simultaneous
sessions regardless of Gateway headroom.

### What one live session costs

| Resource | Agentless node | Outbound-agent node |
|---|---|---|
| File descriptors | 2 (outer TCP socket, inner TCP socket to the node) | 1 (outer socket; the inner leg multiplexes over the agent's existing WebSocket) |
| Recording spool memory | Up to `ssh.recorder.spool_memory_threshold_bytes` (8 MiB) of ciphertext, then it spills to disk | Same |
| Recording spool disk | Everything past 8 MiB, up to `ssh.recorder.max_object_bytes` (4 GiB) | Same |
| Plaintext held | One partial frame, `ssh.recorder.frame_plaintext_bytes` (16 KiB), in a scrub-on-drop buffer | Same |
| Inner flow-control window | `ssh.inner.window_bytes` (2 MiB) per channel, in-flight bound rather than a fixed allocation | Same |

Two more descriptors are transient per session: one for the spool file once
it spills, and one for the HTTPS PUT to the object store at finalize.

The daemon runs a multi-threaded tokio runtime with no explicit worker
count, so it takes tokio's default of one worker per available core. Byte
forwarding is the dominant CPU cost, and it scales with throughput rather
than with session count.

> **Warning:** the shipped systemd unit
> (`Gateway/deploy/systemd/sessionlayer-gateway.service`) sets no
> `LimitNOFILE`, and the shipped Kubernetes manifest
> (`Gateway/deploy/kubernetes/gateway.yaml`) sets no `resources` block. At
> the default `ssh.max_connections` of 512 an agentless Gateway wants over
> 1024 descriptors, which is above the usual default soft limit. Set
> `LimitNOFILE` (or the container equivalent) and CPU/memory requests
> yourself before you raise the connection cap.

The recording spool writes to `<data_dir>/recording-spool`. In the shipped
manifest that path is an `emptyDir` with no `sizeLimit`, so worst-case spool
usage is live sessions multiplied by `ssh.recorder.max_object_bytes`. Size
the volume against your real per-session recording sizes (below), and set a
`sizeLimit`.

## Control Plane replicas

Every session drives a fixed set of gRPC calls into the Control Plane:

| Call | Times per session | Cost |
|---|---|---|
| One authentication RPC (`ResolvePin`, `ResolveOtp`, `ResolveUserCert`, `ResolveBreakglassKey`, …) | 1, capped at `ssh.max_auth_attempts` (6) per connection | Indexed lookup plus one audit write |
| `PollDeviceFlow` | Only for device-flow logins: one every `ssh.device_flow.heartbeat_interval_secs` (10 s) until approval or `poll_timeout_secs` (180 s) | Up to 18 polls per pending login |
| `Authorize` | 1, plus one more at any new channel open once the decision TTL has lapsed. The effective TTL is the smaller of `sessionlayer.authz.decision-ttl` (`PT45S`) and the Gateway's `ssh.reeval.max_decision_ttl_secs` ceiling (60 s), so 45 s at the shipped defaults | The heaviest call; see below |
| `SignSessionCertificate` | 1 (the inner leg is established once and every channel multiplexes over it) | CA signing, offloaded from the event loop |
| `BeginRecording`, `RequestUpload`, `FinalizeRecording` | 1 each, plus one `RequestUpload` per upload retry | Row writes plus a presigned URL mint |
| `ExtendSessionLease` | Only for `run_to_ttl` sessions: one per half lease window (`sessionlayer.session-limits.lease-extension`, default 15 minutes, so about every 7.5 minutes) | Single-row update |
| `NotifySessionEnd` | 1 | Releases the concurrency lease |

Two loads are independent of the session rate. Every Gateway holds one
long-lived `StreamLocks` stream. And in the agent model each Gateway sends
one `Heartbeat` per node whose agent control channel it holds, every
`ha.presence.heartbeat_interval_secs` (10 s), 16 concurrently, each a
transactional presence write. A fleet of 1,000 agent nodes therefore costs
roughly 100 presence writes per second with nobody logged in at all. That
is usually the dominant background load on a large agent deployment.
Standby Gateways heartbeat too, so raising the Agent's
the number of `--gateway-endpoint` values you pass multiplies that rate, one
channel each. (`--min-control-channels` does not: it only warns when live
channels drop below it.) The fan-out is about 16-wide, per
[Gateway runbook](gateway-runbook.md).

### What makes `Authorize` expensive

One `Authorize` reads the full data-plane rule set and the full lock set,
uncached, on every call, plus the session-limit policy table twice (once
for the concurrency cap, once for the duration and idle ceilings). Its cost
is therefore proportional to the size of `config.dp_rule`,
`runtime.access_lock`, and `config.session_limit_policy`, and not only to
your session rate. Keeping those tables small is a latency lever; releasing
expired locks matters for the same reason.

Certificate signing and other blocking crypto run on Reactor's
`boundedElastic` scheduler, whose default thread cap is ten times the CPU
count (reactor-core 3.8.6, overridable with
`reactor.schedulers.defaultBoundedElasticSize`). CPU count, not the R2DBC
pool, bounds concurrent signing.

The self-managed gRPC server allows 128 concurrent calls per connection and
sizes its handler pool at `max(4, 2 × CPU)`. Since one Gateway is one
connection, a busy Gateway can hold 128 calls in flight against a single
Control Plane replica.

### When another replica helps, and when it does not

| Symptom | Add a replica? |
|---|---|
| `sessionlayer_session_establishment_seconds` p95 above 250 ms with CPU saturated | Yes. The SLO is set as a histogram boundary at 250 ms in `application.properties`. |
| R2DBC pool utilization pinned with pending acquires | Yes, if Postgres has connection headroom (see the pool math below). Otherwise raise `spring.r2dbc.pool.max-size` first. |
| `sessionlayer.cert.sign` p95 above its 100 ms boundary | Yes if CPU-bound with the local backend. If the backend is Azure Key Vault or AWS KMS, the ceiling is that service's latency, not the replica count. |
| Audit writes lagging | No. Every audit insert serializes on one cluster-wide Postgres advisory lock to keep the hash chain linear, so replicas add no audit-write throughput. |
| Session-limit denials spiking (`sessionlayer.session.limit`) | No. That is policy working; check the cap, not the capacity. |

The availability SLO (99.9% on real session-CA sign requests, as encoded
in `prometheus-slo-rules.yaml`) is a redundancy requirement rather
than a throughput one: the session CA gates every new session and fails
closed, so run at least two replicas. The shipped manifest does, at 250m
CPU and 512Mi memory requested, 1 CPU and 1Gi limited, with the heap at 75%
of the limit.

## Postgres sizing and the connection pool

### Pool math

| Consumer | Connections | Note |
|---|---|---|
| One Control Plane replica, steady state | `spring.r2dbc.pool.max-size`, which ships at `20` (with `initial-size=5` and `max-acquire-time=10s`) | Review it against your own fleet rather than assuming the shipped value fits. Budget `replicas × max-size` |
| One Control Plane replica, startup | Plus a separate Flyway JDBC pool | Flyway is JDBC-only and startup-only; it takes a database-level lock, so a rolling restart of several replicas serializes rather than conflicting |
| Your own tooling | Whatever psql, backups, and dashboards hold | Count it |

Budget `replicas × max-size` for the runtime pools once you have set it, add
headroom for the Flyway pools during a rolling restart, then add your own
tools, and keep that total comfortably under the server's `max_connections`.

### What each session writes

| Table | Rows per session | Expires? |
|---|---|---|
| `runtime.ssh_session` | 1 | Never. No prune job touches it. |
| `runtime.session_lease` | 1 | Never. Released leases are marked, not deleted. |
| `runtime.recording_ref` | 1 | Never. A pruned recording keeps its row as provenance and loses only the object. |
| `runtime.audit_event` | 7 or more (below) | Only by dropping a whole monthly partition. |

Transient authentication rows (`oidc_login`, `device_flow`, `otp`,
`consumed_assertion`, `auth_rate_limit`, `idempotency_key`) are deleted by
an hourly maintenance sweep, so they do not accumulate.

`runtime.audit_event` is the growth driver and the most expensive write:
it carries eleven secondary indexes, nine B-tree and two GIN, plus a
composite primary key, and every one of them is cloned onto every monthly
partition. Budget index storage well above the table's own row storage.

### Partitioning

`runtime.audit_event` is range-partitioned monthly on `occurred_at`. The
Control Plane provisions six months ahead, at startup and again monthly, so
the `DEFAULT` catch-all partition stays empty. Reclaiming space means
dropping whole partitions, never deleting rows, which is what keeps
retention from fighting the append-only trigger.

## Recording storage growth

A recording is asciicast v2 sealed frame by frame, so the encryption
overhead is fixed and small:

| Component | Size |
|---|---|
| Object header (magic, algorithm, ephemeral P-256 point, wrapped data key) | 137 bytes, once per recording |
| Per sealed frame | 20 bytes (4-byte length prefix plus the 16-byte AES-GCM tag) per `ssh.recorder.frame_plaintext_bytes` of plaintext |

At the default 16 KiB frame size that is 0.12% expansion. Sealed object
size is therefore the asciicast plaintext plus about one part in 800, and
sizing the store means sizing the plaintext.

The plaintext depends on the capability mix:

| Capability | What lands in the recording |
|---|---|
| `shell` | Every output byte, every keystroke, and every resize, as JSON event lines. Roughly the terminal traffic plus, per event line, 10 bytes of framing, an elapsed-seconds timestamp, and any JSON escaping. |
| `exec` | The command line as an input event, then the command's full output. |
| `sftp` | Metadata only: one marker line per decoded file operation with path, direction, size, and a content SHA-256. Transferred bytes are hashed and discarded. |
| `scp` (OpenSSH 9.0+) | Same as `sftp`; modern `scp` rides the SFTP subsystem. |
| `scp` (legacy protocol) | The full transferred byte stream, because it runs over an `exec` channel and every exec channel is terminal-captured. See [Session recording](../admin-guides/session-recording.md). |
| `port_forward_local`, `port_forward_remote`, `x11` | Metadata only: one `opened` marker on admission and one `closed` marker carrying byte counts and duration. Forwarded bytes are never captured. |

There is no meaningful per-hour figure for a shell session, because the
number depends entirely on what your users run: an idle session at a prompt
writes almost nothing, and `tail -f` on a busy log writes continuously.
Measure your own fleet instead:

```sql
SELECT count(*) AS sessions,
       pg_size_pretty(sum(r.size_bytes)) AS total,
       pg_size_pretty((sum(r.size_bytes)
         / nullif(sum(extract(epoch FROM s.ended_at - s.started_at)) / 3600, 0))::bigint)
         AS per_session_hour
FROM runtime.recording_ref r
JOIN runtime.ssh_session s ON s.id = r.session_id
WHERE r.status = 'finalized'
  AND s.ended_at > now() - interval '7 days';
```

The same figures are on `GET /v1/recordings` as `sizeBytes`, so you can
break them down by identity or node through the [API](../reference/api.md)
without database access.

> **Warning:** a legacy `scp` transfer inflates twice over. Its bytes land
> in the recording, and non-UTF-8 bytes become the 3-byte replacement
> character while control bytes become 6-byte `\u00XX` JSON escapes. A
> binary transfer can therefore cost several times its own size in
> recording storage. Standardize on OpenSSH 9.0+ nodes to avoid it.

Two caps bound one object. `ssh.recorder.max_object_bytes` (4 GiB) fails
the recording closed if exceeded. `ssh.recorder.upload_timeout_secs` (30 s)
bounds the whole end-of-session PUT, so the largest object you can actually
upload is 30 seconds multiplied by your Gateway-to-store throughput. Raise
the timeout before you raise the object cap.

## Audit volume and retention

The narrowest successful session, standing access with a pinned key and one
shell channel, produces these seven events:

| Event | Emitted at |
|---|---|
| `pin.resolve` | Authentication (one per credential resolution; a different method substitutes its own event) |
| `authz.decision` | The connect-time decision |
| `session.sign` | Inner certificate signing |
| `recording.begin` | Recording registration |
| `recording.upload` | Upload credential issued at session end |
| `recording.finalize` | Hash-chain head committed |
| `session.end` | Session teardown |

Treat seven as a floor, not a constant. A JIT or break-glass session adds
its own approval and activation events, each per-channel re-authorization
adds another `authz.decision`, each upload retry adds another
`recording.upload`, and file transfers and tunnels add one event per
operation or tunnel at finalize. Reading the audit stream is
itself audited (`audit.search`, `audit.get`), so a busy Dashboard or SIEM
export adds events too. The full catalog is in
[Audit events](../reference/audit-events.md).

Measure your real rate per partition:

```sql
SELECT date_trunc('month', occurred_at) AS month, count(*)
FROM runtime.audit_event
GROUP BY 1 ORDER BY 1;
```

### Retention: drop versus delete

| Data | Mechanism | Cadence |
|---|---|---|
| Audit events | `DETACH` plus `DROP` of whole monthly partitions entirely older than the cutoff | Manual, see below |
| Recordings | Row-by-row: the object is erased and the metadata row marked pruned, batched at 1000 per cycle | Hourly job |
| Transient auth rows | `DELETE` by expiry | Hourly job |

Both windows default to 365 days
(`operator_settings.recording_retention_days` and
`operator_settings.audit_retention_days`), and the recording half runs
automatically. Only `governance`-mode recordings past `retention_until`
with no legal hold are eligible; `compliance` mode and legal holds are
never pruned. A backlog drains across cycles at 1000 per hour, so a large
first prune takes time.

> **Note:** audit retention is not automatic. The restricted `cp_runtime`
> database role deliberately has no `EXECUTE` on
> `runtime.audit_prune_before`, so dropping audit months is an owner-level
> action outside the application's reach. Plan a DBA-run job against the
> retention window you configured, or audit partitions accumulate forever.
> That is the intended trade: a compromised application credential cannot
> erase audit history. See [Audit](../admin-guides/audit.md).

## Next

- [Monitoring](monitoring.md): the SLOs, shipped dashboards, and alert rules.
- [High availability](../admin-guides/high-availability.md): adding Gateways rather than growing one.
- [Gateway configuration](../reference/config-gateway.md): every cap named above, with its default.
- [Data model](../reference/data-model.md): the tables these row counts land in.
