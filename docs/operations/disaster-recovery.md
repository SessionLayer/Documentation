# Disaster recovery

A database restore is routine here and largely self-healing. Losing a key is
not. That asymmetry is what this page is organised around, because the
recovery you reach for depends entirely on which half of SessionLayer's
durable state you lost: the Postgres database and the WORM object store, both
of which you can back up, or the local-CA key-encryption key and the customer
recording key, which exist only in your own configuration and which nothing on
the platform can reconstruct.

## Prerequisites

- [ ] `$CP_DSN`: a Postgres connection string for the Control Plane database
      as the owner role, for example
      `postgres://sessionlayer:<owner-password>@db.example.com:5432/sessionlayer`.
      A few steps below are database operations, mostly because they run
      while no Control Plane is up. Each says why where it appears.
- [ ] `$TOKEN`: an admin bearer token for the steps that do go through the
      API ([Authentication](../admin-guides/authentication.md)).

## What a backup has to cover

| Asset | Where it lives | Without it |
|---|---|---|
| Control Plane database | your Postgres cluster | no policy, no component identities, no audit history, no recording metadata |
| Local-CA KEK (`sessionlayer.ca.local.kek-base64`) | Control Plane configuration or environment, never the database | every `local`-backend CA private key in that backup is ciphertext nothing can unwrap |
| Customer recording key, private half | your offline store, never any SessionLayer component | every recording sealed to it is permanently unreadable |
| WORM recording bucket | your object store | the sealed recording objects; their metadata survives in Postgres |
| Gateway `data_dir`, Agent data dir | each component's host | that component's mTLS credential, recoverable only by re-enrolling |

> **Warning:** the KEK is read from operator configuration at every start and
> is deliberately never written to the database, so a database backup on its
> own does not restore a working platform. Back the KEK up as carefully as
> the database, and somewhere the database backup is not.

## Restore the Control Plane's database

Gateways and Agents keep running while the Control Plane is down. They fail
closed: live sessions continue, new sessions and dial-backs are refused, and
the lock feed reconnects on its own once the Control Plane returns. You are
restoring the authority, not the data path.

### Order of operations

1. Stop every Control Plane instance, and make the pre-restore database
   permanently unable to accept another write. Revoking connection rights is
   the minimum (`REVOKE CONNECT ON DATABASE sessionlayer FROM PUBLIC,
   cp_runtime;` then `ALTER DATABASE sessionlayer CONNECTION LIMIT 0;`);
   destroying the instance once you have the backup you need is better. Do not
   rely on "nothing is pointed at it". The hash-chain warning below is why this
   one is unforgiving. This matters more than usual
   here, for the reason in [The audit hash chain](#the-audit-hash-chain).
2. Restore the snapshot by whatever mechanism produced it: `pg_restore`, a
   point-in-time recovery target, or a storage snapshot.
3. Record the restored audit-chain head before any Control Plane starts.
4. Start one Control Plane instance. Flyway runs the migrations, and
   cold-start CA provisioning is a no-op because the restored database
   already has an active CA of every kind.
5. Work through the three reconciliation sections below, then bring the rest
   of the instances up.

Capture the head at step 3:

```bash
psql "$CP_DSN" -c "SELECT seq, occurred_at, record_hash
    FROM runtime.audit_event ORDER BY seq DESC LIMIT 1"
```

```text
 seq  |          occurred_at          |                           record_hash
------+-------------------------------+------------------------------------------------------------------
 8412 | 2026-07-20 11:02:47.913204+00 | 9f2c1ab7e4d05836c7a1f0be2d47915c3e8a6b04df21c95870ae3fbb1d6c4082
(1 row)
```

Put that `seq` and `record_hash` in your change record. Nothing inside the
stream can express the discontinuity you are about to create, so the record
has to live outside it.

This one is SQL and always will be: it runs at step 3, before any Control
Plane starts, and starting one writes events and moves the head you are
trying to capture. Once the fleet is back up, the same three values are on
`GET /v1/audit-events` as `seq`, `prevHash` and `recordHash`, for a caller
whose `audit:read` binding is unscoped.

### The audit hash chain

Every audit row carries the previous row's hash plus its own, and a new event
chains onto whichever row has the highest `seq`. Restoring an older snapshot
therefore does not break the chain and does not fork it. Each restored row
still links to its predecessor, and the first event written after the restore
links to the restored head. Verification passes, before and after.

What is lost is what verification cannot see. Events written between the
snapshot and the failure are gone, and nothing in the surviving chain records
that they existed. Resistance to tail truncation is outside what the chain
proves, which is why off-box forwarding is a
[production precondition](../security/hardening.md) rather than a nicety.
Your SIEM copy is the only surviving record of the missing tail: every
forwarded event carries its chain hashes, so any event whose `record_hash` is
in the SIEM and not in the restored database is one you lost.

> **Warning:** if the pre-restore database ever accepts another write, you
> get two chains that both extend from the same head, both verify, and
> disagree about history. Nothing in the platform detects that. Fence the old
> database before the new one takes a single write.

There is nothing to re-seed and no repair to apply. The chain continues on
its own, and you could not patch it even if you wanted to:

```bash
psql "$CP_DSN" -c "UPDATE runtime.audit_event SET prev_hash = repeat('0',64) WHERE seq = 8412"
```

```text
ERROR:  runtime.audit_event is append-only: UPDATE is not permitted
CONTEXT:  PL/pgSQL function runtime.audit_event_immutable() line 2 at RAISE
```

To check the restored stream, verify that each row's `prev_hash` matches the
previous row's `record_hash` in `seq` order. Zero rows is a clean result:

```bash
psql "$CP_DSN" -c "WITH chain AS (
        SELECT seq, id, occurred_at, prev_hash,
               lag(record_hash) OVER (ORDER BY seq) AS prior_hash
        FROM runtime.audit_event
    )
    SELECT seq, id, occurred_at
    FROM chain
    WHERE prior_hash IS NOT NULL AND prev_hash IS DISTINCT FROM prior_hash
    ORDER BY seq"
```

```text
 seq | id | occurred_at
-----+----+-------------
(0 rows)
```

The same check runs over the API. `GET /v1/audit-events` exposes `seq`,
`prevHash` and `recordHash` to a caller whose `audit:read` binding is
unscoped, which is the linkage walk in another form. It has to be unscoped:
audit search filters to the caller's binding, and a walk over a filtered view
reads clean even when the rows it could not see contain the break. The SQL
above is here because a restore already has you at a `psql` prompt from the
previous step, not because the API cannot answer.

Two limits on the check, in either form, both deliberate. It verifies linkage
and ordering over the rows you still have, and does not recompute the record
hashes. Recomputing means reproducing the Control Plane's canonical event
encoding byte for byte, which is not part of the published contract, and a
platform recomputing its own hashes would prove nothing against a compromised
platform in any case. That is what the off-box SIEM copy is for. The check
also skips the oldest surviving row, because retention drops whole monthly
partitions, so after any prune the oldest row's `prev_hash` points at a row
that no longer exists. That is expected rather than a defect.

### Session leases

Every non-break-glass session holds a row in `runtime.session_lease`, and an
identity's concurrency is the count of its leases that are unreleased and not
yet expired. A restore rewinds that table, in both directions at once.

Leases resurrected for sessions that have long since ended split by expiry:

- Already expired: harmless. The count ignores them, and the backstop reaper
  releases them within its interval (`PT1H` by default) plus its grace
  (`sessionlayer.session-limits.reaper.grace`, which defaults to the
  lease-extension window and is floored to it so a Gateway's self-heal always
  outruns the reaper). Do nothing.
- Still in the future: these count. The identity is denied new sessions with
  the same generic "access denied by policy" any other denial produces, until
  those leases expire. The window is bounded by the grant expiry the
  snapshot captured, so at most the grant-expiry bound in
  [Session limits](../admin-guides/session-limits.md#what-bounds-a-sessions-duration).
  On a stock install that is the one-hour `sessionlayer.authz.max-grant-ttl`
  ceiling rather than the session-limit default, which is usually the shorter
  wait.

The opposite direction is quieter. Leases acquired after the snapshot are
gone, so those identities under-count until their sessions really end. A live
session re-acquires a lease at its next re-authorization; a session that
never re-authorizes leaves its slot uncounted, and the Control Plane logs
`lease already released/absent` against that session id for each one.

Find the leases that still count (`audit:read`). `activeOnly=true` is exactly
the predicate the cap evaluates, so what comes back is what is holding slots:

```bash
curl -s "https://cp.example.com/v1/session-leases?identity=alice@example.com&activeOnly=true" \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r '.items[] | [.id, .expiresAt] | @tsv'
```

```text
018f3c2a-7b41-7c02-9e55-4b7100000001    2026-07-20T16:34:12.271366Z
018f3c2a-7b41-7c02-9e55-9d0200000002    2026-07-20T16:31:58.114920Z
```

A ghost is not an expired lease. An expired one has already stopped counting,
and the reaper's later `releasedAt` stamp only tidies the row. A ghost is a
lease that still counts with no live session behind it, which you find by
comparing that list against `GET /v1/sessions` filtered the same way. The
difference is the over-count. A lease carrying no `expiresAt` is the
unbounded case and never ages out on its own.

`POST /v1/sessions/{sessionId}/terminate` does not help here: it pushes an
identity-scoped lock and tears the session down without touching the lease
row. For an identity you have confirmed has no live sessions, release its
leases one at a time (`lock:write`, and the reason is required because it
lands in the audit trail):

```bash
curl -s -X POST https://cp.example.com/v1/session-leases/$LEASE_ID/release \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "reason": "ghost lease after restore, change record CR-2291" }'
```

There is deliberately no bulk form. The next warning is why.

> **Warning:** do not release every unreleased lease as a matter of course.
> The concurrent-session cap is a security control, and a bulk release trades
> a bounded over-count, which denies legitimate users, for an under-count,
> which lets an identity exceed its cap until those sessions end. Prefer
> waiting for expiry, and release only for identities you have checked
> against what the Gateways are actually serving.

Watch `sessionlayer.session.limit{outcome=denied}` and
`sessionlayer.session.lease.live` while the restored fleet settles. See
[Session limits](../admin-guides/session-limits.md) for how the counting
works in normal operation.

### Presence and component identities

Presence self-heals and needs no intervention. Every restored row carries a
stale `last_seen`, so within one staleness window (about 30 seconds) each
Gateway either refreshes its own row or takes over a stale one at the next
nonce. Routing fails closed in the meantime, exactly as it does during a
[failover](../admin-guides/high-availability.md).

The ownership nonce does rewind to the snapshot's value. That counter's
monotonicity is enforced against the database's own history, and a restore
rewinds that history, so a dial-back signal captured before the restore is no
longer rejected on nonce alone. It stays refused by the relay token's own
expiry and its binding to node, session, Gateway, and principal.

Component identities do not self-heal, and this is where a restore usually
bites. The Control Plane pins each Gateway's certificate fingerprint and
accepts either the current one or the immediately previous one. So a snapshot
one renewal behind still admits the running Gateway, and needs nothing done to
it. A snapshot that predates more than one renewal pins neither, and the
Gateway is refused: `gateway.renew` records `fingerprint_mismatch`, and session
certificate signing is denied. A Gateway that enrolled after the snapshot has
no identity row at all. Those last two cases need a re-enrollment.

Confirm which case you are in before you act. `GET /v1/gateways` returns both
`fingerprintSha256` and `prevFingerprintSha256`, and the Gateway's own logs
show what it is presenting; if either matches, it is being admitted and
freeing its name would break a Gateway that was working.

Free the name, then follow the normal steps in
[Install the Gateway](../installation/gateway.md). Both halves are API calls,
and the whole procedure needs three permissions: `lock:write` to terminate,
`audit:read` to count, and `gateway:remove` to delete. `gateway:remove` is
separate from `gateway:enroll`, because admitting a Gateway and retiring one
are different authorities. Confirm you hold all three before you begin.
Holding only `gateway:remove` lets you force a removal but not do the safe
thing first, which is the worst position to discover halfway through.

Order matters, and the order is: stop the sessions, confirm, then delete.
Removal does not stop live sessions, and it removes the means of stopping
them: deleting the identity makes the Control Plane refuse that Gateway's
lock-feed subscription, so a later terminate has no path to reach it. Sessions
already bridged keep flowing until the Gateway's next authorization or
per-channel recheck, and one that opens no further channel runs to its grant
expiry.

Stop the sessions while the Gateway can still be told to:

```bash
# 1. Terminate each live session, or push an identity-scoped lock (lock:write).
curl -s -X POST https://cp.example.com/v1/sessions/$SESSION_ID/terminate \
  -H "Authorization: Bearer $TOKEN"

# 2. Count what is still running (audit:read).
curl -s "https://cp.example.com/v1/sessions?activeOnly=true" \
  -H "Authorization: Bearer $TOKEN" | jq '.items | length'
```

Do not wait for that count to reach zero. `activeOnly=true` filters on
the session's own end-stamp, not on whether its Gateway is alive, so a session
whose Gateway died without ending it stays active indefinitely because nothing
stamped it. A count that does not fall after a terminate is therefore the
signal that the Gateway is no longer receiving locks, not a reason to wait
longer. A Gateway you cannot reach is one you have to force.

That case is the normal one after a restore. Presence is stale by definition,
but the restored database is full of sessions with no end stamp, and those are
what the guard counts.

If the count does reach zero, remove cleanly. List the identities
(`gateway:enroll`), then delete the one you want (`gateway:remove`):

```bash
GW_ID=$(curl -s -G https://cp.example.com/v1/gateways \
  -H "Authorization: Bearer $TOKEN" --data-urlencode "name=gw-1" | jq -r '.items[0].id')

curl -s -X DELETE https://cp.example.com/v1/gateways/$GW_ID \
  -H "Authorization: Bearer $TOKEN"
```

The `name` filter runs in the database. Selecting client-side from an
unfiltered `GET` would read one 50-identity page, so on a larger fleet it
matches nothing, `$GW_ID` comes back empty, and the `DELETE` goes to
`/v1/gateways/` instead of failing readably.

An unforced `DELETE` against a Gateway holding fresh presence or unended
sessions is a `409` naming both counts, so this ordering is enforced rather
than merely advised: the delete refuses if you skipped the two steps above.

Add `?force=true` to remove it anyway. The forced removal ends the sessions
the guard was counting and is audited as a distinct action from an ordinary
one, so the two are never conflated afterwards.

> **Warning:** `force=true` is for a Gateway you know is not coming back. It is
> not a way to stop one that is still running. A forced removal ends that
> Gateway's live sessions and marks their recordings `failed`, which does not
> preserve them, it records that they were lost. Terminating first and
> confirming is what keeps the recordings.

Mint a fresh single-use enrollment token, clear the Gateway's `data_dir` so
it has no stale credential, and restart it. Ownership is keyed by the
Gateway's enrolled name rather than its identity id, so relay routing and
presence pick up again without further work.

Agents recover the same way from their own side. An Agent whose credential is
refused stops with exit code `4`, repair needed; clear its data dir and
re-join with a fresh join token, per the
[Agent runbook](agent-runbook.md). A node registered after the snapshot is
unknown to the restored database, so its Agent must re-join before any
Gateway can own it.

## A lost or compromised CA key

The three SSH CAs and the internal mTLS CA fail in very different ways.
[Certificate authorities](../admin-guides/certificate-authorities.md) covers
what each one signs and how rotation works; this table is the incident view.

| CA | If the private key leaks | If it is only lost | Recovery |
|---|---|---|---|
| `user` | An attacker mints user certificates the Gateway's outer leg accepts and impersonates any identity they name. Authentication only: every connection still runs full authorization, and no node trusts this CA. | Nothing in the Control Plane signs with it, so platform behavior is unchanged. Whatever issuer actually mints your user certificates is what broke. | Lock the affected identities, then rotate. Clients keep verifying through the overlap. |
| `session` | Total compromise of every node. The holder mints a certificate any node's `sshd` accepts, for any principal, without going through a Gateway: no authorization, no lock check, no recording, no audit event. | No new sessions anywhere. Signing fails closed, the signer health indicator goes down, and live sessions run on undisturbed. | Lock first, replace the key second, and get the incoming key into every node's `TrustedUserCAKeys` before the outgoing one stops being trusted. |
| `host` | An attacker mints host certificates that clients trusting this CA through `@cert-authority` accept, so they can impersonate the Gateway's ProxyJump front door. It grants no session and produces nothing a node's `sshd` accepts. The inner leg is unaffected: the Gateway accepts only a host certificate the Control Plane supplied and bound to the key the node presents at KEX. | ProxyJump host-certificate signing fails closed. Node host verification keeps working from material already stored. | Replace the key, then redistribute `@cert-authority` lines before the old one stops being trusted. |
| `mtls` | An attacker mints a decision-context signing leaf and forges signed authorization decisions, and impersonates the Control Plane to every Gateway and Agent that pins this CA. It cannot mint anything a node accepts; that is the session CA's job. | The Control Plane will not start: it mints its own gRPC server certificate from this CA at every boot and aborts fail-closed if it cannot. | Not reachable through `/v1/cas`. See [Rebuild the internal mTLS CA](#rebuild-the-internal-mtls-ca). |

> **Note:** the `user`/`session`/`host` rows above assume the `local` backend, still the default.
> A CA adopted onto `aws_kms` or `azure_keyvault`
> ([Certificate authorities](../admin-guides/certificate-authorities.md)) has a different story in
> both columns: the private key cannot leak through a Control Plane or database compromise, because
> it never leaves the key service. "Only lost" then means the key service is unreachable, its
> credential no longer grants signing, or the key itself was deleted, not a misplaced
> key-encryption key. Recovery is bounded by that service's own deletion protections rather than by
> anything the Control Plane holds: Key Vault's soft-delete and purge protection, KMS's deletion
> waiting period. Check `GET /v1/cas` (`backend`) before applying either column, and see
> [Losing a KMS-held CA key](#losing-a-kms-held-ca-key). The `mtls` row is unaffected: that CA
> cannot move off `local`.

In every leak case, lock before you replace the key. A
[lock](../admin-guides/locks.md) is immediate and un-overridable; the new key
is the durable fix that follows it.

Rotation is the call that replaces the key, and this build signs with `local`,
`aws_kms` and `azure_keyvault`. If a database carried from an older deployment
holds a CA on `vault`, that CA already cannot sign, and rotating it does not
self-heal by default: an empty rotate body inherits the CA's current
(non-signing) backend and is refused with the same `422` the write path gives.
Name the backend explicitly, `{"backend": "local"}` or one of the key-service
adoptions, to bring the kind back onto a key that works. See
[Certificate authorities](../admin-guides/certificate-authorities.md).

### What rotation does and does not fix

`POST /v1/cas/{caId}/rotate` provisions a fresh key as `incoming`, demotes the
current `active` to `outgoing`, and promotes the new one. All three states
stay trusted through the overlap, so no session is refused mid-rotation. It
handles the `user`, `session` and `host` CAs.

It does not distribute trust. Your nodes' `TrustedUserCAKeys` and your users'
`@cert-authority` lines must contain the incoming key before the outgoing one
drains, and the platform cannot check that for you.

It also does not remove the compromised key from the trusted set. The
outgoing key keeps verifying until you drain it, which is the entire point
during a planned rotation and precisely wrong after a leak. After a
compromise, drain the outgoing key as soon as your trust distribution has
landed, and rely on the lock for the interval in between.

> **Warning:** an empty request body regenerates the *same* backend, key
> reference, and algorithm the active CA already has - it is not a way to
> change any of the three. `backend`, `keyReference`, and `algorithm` are real,
> validated overrides for the incoming key, checked before anything is
> written: naming a backend this build has no signer for, a Key Vault reference
> that is unversioned or names a different vault, or a KMS reference that is an
> alias or names a different account, is a `422` and the CA is untouched.
> Adopting a key service, and moving a compromised key onto a new key version or
> a new key ARN, both require naming the new `backend`/`keyReference` explicitly
> in the request; re-sending an empty body against a key-service CA re-adopts
> the exact key it already points to.

### Rebuild the internal mTLS CA

`CaConfigService` exposes only the `user`, `session` and `host` kinds through
`/v1/cas`, so the internal mTLS CA cannot be listed, updated, deleted or
rotated over the API. There is no overlap machinery for it either: rebuilding
it invalidates every Gateway and Agent identity at once. Plan a maintenance
window; no session survives this.

Stop every Control Plane instance, then drop the CA rows. The Control Plane
self-provisions a replacement at the next gRPC server start, but only when no
active `mtls` config row exists, so both rows have to go:

```bash
psql "$CP_DSN" -c "DELETE FROM runtime.ca_key_material
    WHERE ca_config_id IN (SELECT id FROM config.ca_config WHERE ca_kind = 'mtls')"
psql "$CP_DSN" -c "DELETE FROM config.ca_config WHERE ca_kind = 'mtls'"
```

Start one Control Plane, then export the new trust anchor. The endpoint always
returns the `active` CA, so a rebuild that briefly leaves more than one `mtls`
row cannot hand you two concatenated certificates:

```bash
curl -s https://cp.example.com/v1/cas/mtls/trust-anchor \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r .pem > cp-mtls-ca.pem
```

Check the `fingerprintSha256` in the same response against the file you
distribute, so a truncated copy is caught before any Gateway trusts it:

```bash
openssl x509 -in cp-mtls-ca.pem -outform der | sha256sum
```

Distribute `cp-mtls-ca.pem` to every Gateway's `bootstrap.ca_cert_path` and
every Agent's `--bootstrap-ca-file`, then re-enroll each component as in
[Presence and component identities](#presence-and-component-identities).

### Losing the KEK

The KEK wraps every CA private key still on `local`; the internal mTLS CA is
always among them, since it cannot move. Each wrapped key is AES-256-GCM
ciphertext bound to its own row, so without the exact KEK bytes there is no
recovery of any of them, and no degraded mode: the Control Plane refuses to
start, because it cannot mint its own gRPC server certificate.

The `local` CA rebuild is the same shape as the mTLS one, applied to every CA
still on `local`, and it is a fleet rebuild rather than a rotation: a `local`
session, user, or host CA means redistributing `TrustedUserCAKeys` and
`@cert-authority` to every node and client, on top of re-enrolling every
component. Any SSH CA already adopted onto `aws_kms` or `azure_keyvault` is
unaffected: its key was never wrapped under the KEK, so losing the KEK cannot
touch it.

> **Warning:** `sessionlayer.ca.local.allow-dev-kek=true` is not a recovery
> path. The built-in dev KEK is a public constant and unwraps only keys that
> were wrapped under it, so setting it recovers nothing and makes any key
> subsequently wrapped under it readable by anyone holding the database.

Adopting a key service for a SSH CA is what shrinks this blast radius: that
CA's private key is never in the database at all, so losing the KEK cannot
reach it. The internal mTLS CA cannot be adopted, so it always sits in the
database under the KEK regardless of what you have done with the three SSH CAs.
That is what makes the KEK the platform's most sensitive secret, and why it
belongs somewhere the database's backups do not reach. See
[Production hardening](../security/hardening.md).

### Losing a KMS-held CA key

A CA adopted onto `aws_kms` has no private key in any backup, by construction.
The Control Plane stores the key ARN and the public half; the private half has
never existed outside KMS and cannot be exported from it. Nothing you restore
brings that key back, and nothing leaked from a database or a KEK gives it
away. "Recover the key" is not an operation here. "Rotate onto a key that
exists, then redistribute trust" is.

| What happened | Effect on signing | Recoverable |
|---|---|---|
| The role's `kms:Sign` grant was removed or narrowed | fails closed at the next certificate | yes: restore the grant, nothing was lost |
| The KMS key was disabled | fails closed at the next certificate | yes: re-enable the key |
| The KMS key is pending deletion | fails closed at the next certificate | yes, until the waiting period elapses: `aws kms cancel-key-deletion` |
| The KMS key was deleted, or its account or region is gone for good | fails closed at the next certificate | the key, never. The CA, yes: rotate onto a new key |
| The Control Plane database was lost, KMS intact | stops with the Control Plane | yes, and with no fleet change: the CA's public half is restored with the row and still matches the key in KMS |

The first three are access incidents rather than key loss. The key material is
untouched, the CA's pinned public key still matches it, and signing resumes the
moment access is back, with nothing to redistribute. Sessions already running
are undisturbed throughout; it is new sessions that stop, because the session
CA gates them.

A deleted key is the one that does not come back once its waiting period has
elapsed, and an account or region you have permanently lost has the same
effect. Recovery is a rotation onto a key that exists, followed by the trust
redistribution any rotation needs:

```bash
# CA_ID from GET /v1/cas; the keyReference is the replacement key's ARN.
curl -s -X POST https://cp.example.com/v1/cas/$CA_ID/rotate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: recover-session-ca-2026q3" \
  -d '{
        "backend": "aws_kms",
        "keyReference": "arn:aws:kms:eu-west-1:111122223333:key/1a2b3c4d-5e6f-4a8b-9c0d-1e2f3a4b5c6d",
        "algorithm": "ecdsa-p256"
      }'
```

> **Warning:** the replacement key has to be in the account, region and
> partition named by `sessionlayer.ca.aws.*`, because the ARN is checked against
> them and that anchor is process configuration no database row can override.
> Recovering into another region therefore means changing that configuration and
> restarting the Control Plane before the rotation, and a multi-Region key is not
> an escape from it: a replica's ARN names its own region. Work the restart into
> the plan rather than discovering it mid-incident.

If no KMS key is reachable at all and sessions are down, `{"backend": "local"}`
provisions a fresh key in the database under the KEK and gets the fleet signing
again on the same overlap-then-drain terms. Adopt KMS again once the account is
back. Either way the fleet's `TrustedUserCAKeys` has to learn the new public
half before the outgoing key drains, and the platform cannot check that for
you.

## Recording-store loss against customer-key loss

Recordings are sealed client-side to your public key and written to the WORM
store, so the two halves fail separately and only one of them is recoverable.

| What you lost | The recordings | What you still have |
|---|---|---|
| The WORM objects | unrecoverable; the ciphertext existed nowhere else | full metadata in Postgres and the audit stream: session, identity, node, times, size, WORM mode, hash-chain head, and the `recording.begin` / `recording.finalize` events. You can prove what was recorded, that it is now missing, and whether any object you recover is the one that was finalized. |
| The customer recording key, private half | permanently unreadable, by design | nothing that decrypts them, now or later. New sessions record normally once you provision a replacement key. |
| Both | gone twice over | metadata only |

> **Warning:** losing the customer recording key destroys every recording
> sealed to it, permanently. There is no platform-side recovery and there
> cannot be one: the Control Plane holds only your public half, the Gateway
> seals each recording's data key to it, and the private half never touches
> any SessionLayer component. That is the property the design buys, and the
> cost of it is that key custody is entirely yours. An escrowed copy in a
> second, independently controlled location is the only protection.

Before concluding that objects are gone, check for older versions. Object-lock
buckets are versioned, and a keyed delete adds a delete marker rather than
erasing the locked version, so an object deleted by accident or by a tool
that is not WORM-aware is usually still there behind the marker. The
platform's own governance delete is the exception: it enumerates and removes
every version, as described in [Audit](../admin-guides/audit.md). A store
that is merely unreachable is a different problem and shows up as sessions
refused with `outcome=recording_unavailable`; see the
[Gateway runbook](gateway-runbook.md).

Two things to keep in your backup plan:

- Retired customer keys. Replacing `recording_customer_public_key` is
  forward-only: it changes what future recordings seal to and does nothing to
  existing ones. Keep every retired private key for at least as long as the
  retention of the recordings sealed under it. Each recording's
  `encryptionKeyRef` names the key it needs.
- The bucket's own replication or backup. WORM protects an object against
  deletion, not against the loss of the store holding it.

## Next

- [Certificate authorities](../admin-guides/certificate-authorities.md): the
  rotation state machine and the backend choices behind this page.
- [High availability](../admin-guides/high-availability.md): surviving an
  instance loss, which is a different problem from surviving data loss.
- [Session recording](../admin-guides/session-recording.md): provisioning the
  customer key and replaying under it.
- [Troubleshooting](troubleshooting.md): symptom-first index if the restored
  fleet still misbehaves.
