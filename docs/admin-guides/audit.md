# Audit

SessionLayer keeps one correlated, append-only audit stream for everything:
SSH session events from the Gateway and web/admin events from the Control
Plane land in the same store, joined by a correlation id. This guide shows
you how to search it, how to reconstruct a full story
(approve → connect → run → replay), and how retention, legal hold, and
deletion work, including the WORM-correct delete semantics.

## Prerequisites

- [ ] The `audit:read` platform permission (searches are additionally
      filtered to your binding's scope). Retention and deletion actions need
      `recording:delete`.
- [ ] A bearer token in `$TOKEN` ([Authentication](authentication.md)).

## Search the stream

`GET /v1/audit-events` searches newest-first with cursor pagination. The
dimensions cover everything an investigation pivots on: identity, target,
node and node label, session, source IP, capability, access model, and time:

```bash
# Every authorization decision about alice on prod web nodes last week:
curl -s -G https://cp.example.com/v1/audit-events \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "subject=alice@example.com" \
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

### `actor` and `subject` are not the same person

`actor` is who made the call. `subject` is who it was about. A session splits
across both, because the Gateway acts on the user's behalf: `authz.decision`
and `session.end` carry the Gateway's enrolled identity as `actor` and the
human as `subject`, while `recording.begin`/`upload`/`finalize` and the
`sftp.*` operations carry the human as `actor` and no subject.

One session by `alice@example.com`, filtered each way:

| Filter | What comes back |
|---|---|
| `subject=alice@example.com` | `authz.decision`, `session.end`, `otp.issue`, `pin.create` |
| `actor=alice@example.com` | `pin.resolve`, `recording.begin`, `recording.upload`, `recording.finalize`, `sftp.read`, `sftp.write` |

The two sets do not overlap, so neither filter alone answers "everything alice
did". Use `subject` for "what was decided about this person", `actor` for "what
this person or component performed", and `correlationId` (below) when you want
one session whole. Both filters match exactly and neither is validated, so a
wrong guess returns an empty page rather than an error, which reads exactly like
an event that was never recorded.

The `authz.decision` events in this stream are what other pages call the
decision log: the operator-side truth behind every generic
`access denied by policy`, carrying the matched rule or lock and the full
allow snapshot. It is not a separate store or file: search it with
`--data-urlencode "action=authz.decision"` like any other filter.

`nodeLabel` is repeatable and ANDed. Un-time-bounded searches default to the
last 90 days; a window wider than 366 days is rejected (`422`) rather than
scanned. Narrow your range instead. Results honor your RBAC scope: an
auditor bound with a `node_labels`/`users`/time scope sees only in-scope
events, and fetching a single event outside your scope returns the same
`404` as a nonexistent one, so scoped access leaks no existence information.

Reading the audit trail is itself audited: reviewers appear in the same
stream they review.

## Reconstruct one story

Every event carries a `correlationId`. Given any point in a story, a JIT
approval, a session, a replay, one query returns the whole chain:

```bash
# CORRELATION_ID comes from any event in the chain (e.g. the session's events).
curl -s -G https://cp.example.com/v1/audit-events \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "correlationId=$CORRELATION_ID"
```

The result reads like a narrative: who requested access and why, who
approved it, the connect-time authorization decision (with the matched rule),
what the session did (commands, file-transfer operations), how it ended, and
who replayed the recording afterwards. There is no second log to stitch in.
Web/admin actions and SSH events are the same stream by design. Config-change
events additionally carry before/after snapshots in their `detail` field.

## Tamper evidence

The stream is append-only (enforced by a database trigger) and hash-chained:
each event's `record_hash` covers the previous event's `record_hash` plus its
own canonical content, serialized under an advisory lock so concurrent writers
cannot fork the chain. Mutating, removing, or reordering any row breaks the
chain. Recordings carry their own chain. See
[Session recording](session-recording.md). WORM storage plus these chains is
the baseline tamper evidence; the externally-anchored Merkle root is
deliberately deferred (see the [trust model](../security/trust-model.md)).

The check you can run is a linkage walk: each row's `prev_hash` against the
previous row's `record_hash`, in `seq` order. It is available as SQL or over
the API, and
[Disaster recovery](../operations/disaster-recovery.md#the-audit-hash-chain)
carries the query. Three limits belong in any control narrative you write from
it:

- It verifies linkage and ordering, not content. Recomputing `record_hash`
  would mean reproducing the Control Plane's canonical event encoding byte for
  byte, which is not part of the published contract, and a platform
  recomputing its own hashes proves nothing against a compromised platform.
  Your off-box SIEM copy is what covers that, which is why it is a production
  precondition rather than a nicety.
- `GET /v1/audit-events` returns `seq`, `prevHash` and `recordHash` only to a
  caller whose `audit:read` binding is unscoped. Search results are
  scope-filtered, and a walk over a filtered view reads clean even when the
  rows it could not see contain the break, so a scoped reader is given no
  fields rather than a verification that does not verify.
- The oldest surviving row is skipped. Retention drops whole monthly
  partitions, so after any prune that row's `prev_hash` points at a row that
  no longer exists. Expected, not a finding.

For depth beyond the platform's own controls: ship events off-box as they
commit (next section), and in the agent connectivity model the node's own
`sshd` log, which the platform cannot write to, records every accepted
session certificate's key id (`session_id + identity`), giving you a
tamper-independent cross-check by session id.

## Ship to your SIEM

Audit shipping is a pluggable interface (`AuditForwarder`): every committed
event is handed to the forwarder *after* commit, already carrying its chain
hashes so a downstream system can verify continuity independently.
Forwarding is best-effort with a bounded timeout and a loud warning on
failure. It can never roll back or slow the audited action itself.

The shipped default emits each event as a structured `audit.forward` JSON
log line. Point your log collector at it and you have off-box audit today.
For a native connector (Splunk HEC, Kafka, syslog, …), a deployment provides
its own `AuditForwarder` bean, which replaces the default. The same pattern
applies to the storage seams: `AuditEventStore` (Postgres today) and
`RecordingStore` (S3/MinIO today) are interfaces, each proven against a
second implementation, so a deployment can substitute backends without
touching call sites.

> **Warning:** off-box forwarding to an independent SIEM is a production
> precondition, not an optional nicety. It is your tail-truncation
> resistance if a privileged party ever attacks the primary store. See
> [Production hardening](../security/hardening.md).

## Retention and legal hold

Recordings: default retention 365 days. Set it, and the audit window
alongside it, on the operator settings resource (`settings:write`):

`PUT` replaces the whole resource: read it, apply your change, and send the
whole writable set back. The `jq` filter below is that set, complete. The
first four fields and `version` are required, so a body missing one is a
`400`; the three session-limit defaults are cleared by omission, and the
filter copies them from the `GET` so a deployment-pinned one is echoed back
unchanged rather than refused. Any field outside the set is a `400`. The
customer recording key is not in it: it is a separate sub-resource, and no
`PUT` here can change or clear it. Field-by-field rules:
[Operator settings](../reference/api.md#the-writable-field-set).

```bash
SETTINGS=$(curl -s https://cp.example.com/v1/operator-settings \
  -H "Authorization: Bearer $TOKEN")

curl -s -X PUT https://cp.example.com/v1/operator-settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(printf %s "$SETTINGS" | jq '{auditRetentionDays, recordingRetentionDays,
          defaultWormMode, otpTtlSeconds, defaultMaxSessionSeconds,
          defaultIdleTimeoutSeconds, defaultMaxConcurrentSessions, version}
        | .auditRetentionDays = 400
        | .recordingRetentionDays = 400')"
```

Keep both at or above 12 months for PCI/SOC 2/ISO-style regimes. Either
value can be raised or left alone; lowering one is a `422` at every
permission level, because shortening the audit window drops partitions that
would otherwise have been kept. The ceiling is 36525 days, so that a typo
cannot ratchet retention somewhere the API can never bring it back from.
Deliberately weakening retention is a database-owner operation, not an API
call; the statement is in
[Session recording](session-recording.md#weaken-the-setting-back-a-database-owner-operation),
which covers both retention columns and the WORM mode, since they share one
row and one version counter. An hourly job prunes
`governance`-mode recordings past retention, erasing the object and marking
the metadata row pruned (provenance is retained). Compliance-mode and
legal-held recordings are never pruned.

Place or release a legal hold. A held recording is exempt from pruning *and*
deletion, in either WORM mode:

```bash
# RECORDING_ID from GET /v1/recordings (filter by sessionId, identity, or nodeId).
curl -s -X PUT https://cp.example.com/v1/recordings/$RECORDING_ID/legal-hold \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "held": true, "reason": "litigation hold, case 2026-041" }'
```

Audit events land in monthly range partitions that the Control Plane
provisions ahead automatically. Reclaiming expired partitions is
deliberately not something the restricted runtime database role can do.
Dropping audit data is a DBA-level action outside the application's own
reach, which is exactly where you want that power during a compromise.

## Governance delete: the erasure escape hatch

For `governance`-mode recordings, a specifically privileged role
(`recording:delete`) can erase:

```bash
curl -s -X DELETE https://cp.example.com/v1/recordings/$RECORDING_ID \
  -H "Authorization: Bearer $TOKEN"
```

The delete is WORM-correct: on a versioned, object-locked bucket it
enumerates and removes every object version and delete marker, not the
naive keyed delete, which merely hides the object behind a marker while the
locked version quietly persists. The metadata row is retained, marked
pruned with who deleted it, and the deletion is audited. A compliance-mode
or legal-held recording refuses with `409`. For compliance mode, erasure is
only achievable by destroying the customer key you hold
([Session recording](session-recording.md)).

## Next

- [Session recording](session-recording.md): the crown-jewel half of the
  audit story.
- [RBAC](rbac.md): scoping auditors to exactly their remit.
- [Monitoring](../operations/monitoring.md): alerting on audit-worthy
  signals, not just storing them.
- [Trust model](../security/trust-model.md): what tamper evidence does and
  does not promise.
