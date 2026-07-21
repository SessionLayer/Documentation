# Audit

SessionLayer keeps **one correlated, append-only audit stream** for
everything: SSH session events from the Gateway and web/admin events from the
Control Plane land in the same store, joined by a correlation id. This guide
shows you how to search it, how to reconstruct a full story
(approve → connect → run → replay), and how retention, legal hold, and
deletion work — including the WORM-correct delete semantics.

## Prerequisites

- [ ] The `audit:read` platform permission (searches are additionally
      filtered to your binding's scope). Retention and deletion actions need
      `recording:delete`.
- [ ] A bearer token in `$TOKEN` ([Authentication](authentication.md)).

## Search the stream

`GET /v1/audit-events` searches newest-first with cursor pagination. The
dimensions cover everything an investigation pivots on — identity, target,
node and node label, session, source IP, capability, access model, and time:

```bash
# Everything alice did on prod web nodes last week:
curl -s -G https://cp.example.com/v1/audit-events \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "actor=alice@example.com" \
  --data-urlencode "nodeLabel=env=prod" \
  --data-urlencode "nodeLabel=role=web" \
  --data-urlencode "from=2026-07-13T00:00:00Z" \
  --data-urlencode "to=2026-07-20T00:00:00Z"

# Every break-glass session in the last 24 hours:
curl -s -G https://cp.example.com/v1/audit-events \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "accessModel=breakglass" \
  --data-urlencode "from=2026-07-20T09:00:00Z"

# Who has been creating locks:
curl -s -G https://cp.example.com/v1/audit-events \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "action=lock.create"
```

The `authz.decision` events in this stream are what other pages call the
**decision log** — the operator-side truth behind every generic
`access denied by policy`, carrying the matched rule or lock and the full
allow snapshot. It is not a separate store or file: search it with
`--data-urlencode "action=authz.decision"` like any other filter.

`nodeLabel` is repeatable and ANDed. Un-time-bounded searches default to the
last 90 days; a window wider than 366 days is rejected (`422`) rather than
scanned — narrow your range instead. Results honor your RBAC scope: an
auditor bound with a `node_labels`/`users`/time scope sees only in-scope
events, and fetching a single event outside your scope returns the same `404`
as a nonexistent one, so scoped access leaks no existence information.

Reading the audit trail is itself audited — reviewers appear in the same
stream they review.

## Reconstruct one story

Every event carries a `correlationId`. Given any point in a story — a JIT
approval, a session, a replay — one query returns the whole chain:

```bash
# CORRELATION_ID comes from any event in the chain (e.g. the session's events).
curl -s -G https://cp.example.com/v1/audit-events \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "correlationId=$CORRELATION_ID"
```

The result reads like a narrative: who requested access and why, who
approved it, the connect-time authorization decision (with the matched rule),
what the session did (commands, file-transfer operations), how it ended, and
who replayed the recording afterwards. There is no second log to stitch in —
web/admin actions and SSH events are the same stream by design. Config-change
events additionally carry before/after snapshots in their `detail` field.

## Tamper evidence

The stream is append-only (enforced by a database trigger) and hash-chained:
each event's hash covers the previous event's hash plus its own canonical
content, serialized so concurrent writers cannot fork the chain. Mutating,
removing, or reordering any row breaks the chain, and the chain verifier
recomputes it end to end. Recordings carry their own chain — see
[Session recording](session-recording.md). WORM storage plus these chains is
the baseline tamper evidence; the externally-anchored Merkle root is
deliberately deferred (see the [trust model](../security/trust-model.md)).

For depth beyond the platform's own controls: ship events off-box as they
commit (next section), and in the agent connectivity model the node's own
`sshd` log — which the platform cannot write to — records every accepted
session certificate's key id (`session_id + identity`), giving you a
tamper-independent cross-check by session id.

## Ship to your SIEM

Audit shipping is a **pluggable interface** (`AuditForwarder`): every
committed event is handed to the forwarder *after* commit, already carrying
its chain hashes so a downstream system can verify continuity independently.
Forwarding is best-effort with a bounded timeout and a loud warning on
failure — it can never roll back or slow the audited action itself.

The shipped default emits each event as a structured `audit.forward` JSON log
line — point your log collector at it and you have off-box audit today. For
a native connector (Splunk HEC, Kafka, syslog, …), a deployment provides its
own `AuditForwarder` bean, which replaces the default. The same pattern
applies to the storage seams: `AuditEventStore` (Postgres today) and
`RecordingStore` (S3/MinIO today) are interfaces, each proven against a
second implementation, so a deployment can substitute backends without
touching call sites.

> **Warning:** off-box forwarding to an independent SIEM is a production
> precondition, not an optional nicety — it is your tail-truncation
> resistance if a privileged party ever attacks the primary store. See
> [Production hardening](../security/hardening.md).

## Retention and legal hold

**Recordings**: default retention 365 days (operator-configured; keep it at
or above 12 months for PCI/SOC 2/ISO-style regimes). An hourly job prunes
`governance`-mode recordings past retention — erasing the object and marking
the metadata row pruned (provenance is retained). Compliance-mode and
legal-held recordings are never pruned.

Place or release a legal hold — a held recording is exempt from pruning
*and* deletion, in either WORM mode:

```bash
# RECORDING_ID from GET /v1/recordings (filter by sessionId, identity, or nodeId).
curl -s -X PUT https://cp.example.com/v1/recordings/$RECORDING_ID/legal-hold \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "held": true, "reason": "litigation hold — case 2026-041" }'
```

**Audit events** land in monthly range partitions that the Control Plane
provisions ahead automatically. Reclaiming expired partitions is deliberately
*not* something the restricted runtime database role can do — dropping audit
data is a DBA-level action outside the application's own reach, which is
exactly where you want that power during a compromise.

## Governance delete — the erasure escape hatch

For `governance`-mode recordings, a specifically privileged role
(`recording:delete`) can erase:

```bash
curl -s -X DELETE https://cp.example.com/v1/recordings/$RECORDING_ID \
  -H "Authorization: Bearer $TOKEN"
```

The delete is WORM-correct: on a versioned, object-locked bucket it
enumerates and removes **every object version and delete marker** — not the
naive keyed delete, which merely hides the object behind a marker while the
locked version quietly persists. The metadata row is retained, marked pruned
with who deleted it, and the deletion is audited. A compliance-mode or
legal-held recording refuses with `409` — for compliance mode, erasure is
only achievable by destroying the customer key you hold
([Session recording](session-recording.md)).

## Next

- [Session recording](session-recording.md) — the crown-jewel half of the
  audit story.
- [RBAC](rbac.md) — scoping auditors to exactly their remit.
- [Monitoring](../operations/monitoring.md) — alerting on audit-worthy
  signals, not just storing them.
- [Trust model](../security/trust-model.md) — what tamper evidence does and
  does not promise.
