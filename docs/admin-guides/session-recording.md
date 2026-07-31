# Session recording

Every session through SessionLayer is recorded, output and keystrokes,
sealed to a key that only you hold, and written to write-once storage. This
guide shows you how to provision the customer recording key, choose a WORM
mode, and replay or export recordings.

The single most important fact on this page: the platform cannot read its
own recordings. Each recording is encrypted to your (the operator's) public
key; the Control Plane stores only that public half, and the private half
never touches any SessionLayer component. A platform admin, a compromised
Control Plane, or SessionLayer's own developers can produce ciphertext, and
nothing else. Secrets typed at prompts are captured, but unreadable *from
the stored recording* to everyone except the holder of your key. The one
component that does see session plaintext, live, at capture, before
sealing, is the Gateway itself. That is the Tier-0 trade stated in the
[trust model](../security/trust-model.md), and why the
[hardening checklist](../security/hardening.md) treats Gateway placement and
integrity as preconditions.

## What gets captured

- Terminal sessions: recorded as asciicast v2, output, keystrokes, and
  window resizes, with real timing. Keystroke capture closes the "user hid
  the command behind a shell trick" gap.
- Commands: non-interactive `exec` runs record the command string and its
  output.
- File transfers: the SFTP protocol is decoded into a per-operation audit
  (operation, path, direction, size, and a streaming SHA-256 of the
  content). For SFTP (including modern `scp`, which rides the SFTP
  subsystem), file content is never captured. Bytes are streamed into the
  hash and discarded.

> **Note:** legacy `scp` runs over an `exec` channel, and every exec channel
> is always terminal-captured (otherwise a crafted command line could
> suppress its own recording). So a legacy-protocol `scp`
> transfer's raw bytes do land inside the sealed recording, alongside its
> file-transfer audit. Modern OpenSSH (9.0+) uses SFTP for `scp` and is
> content-free.

Recording is strict: if a recording cannot start or fails mid-session, the
session is refused or torn down. No setting relaxes this. No recording, no
session.

## Provision the customer recording key

### Prerequisites

- [ ] The `recording:key-manage` platform permission to write the key, and
      `rbac:read` to read the settings the commands below start from. Neither
      implies the other, and `recording:key-manage` implies nothing. A bearer
      token in `$TOKEN` ([Authentication](authentication.md)).
- [ ] Somewhere genuinely offline to keep the private key: an HSM-backed
      store or your organization's key vault. Whoever holds it can decrypt
      every recording.

Generate a P-256 keypair and give the platform the public half (DER SPKI):

```bash
openssl ecparam -name prime256v1 -genkey -noout -out customer-recording-key.pem
openssl ec -in customer-recording-key.pem -pubout -outform DER | base64 -w0 > customer_pub.b64

VERSION=$(curl -sf https://cp.example.com/v1/operator-settings \
  -H "Authorization: Bearer $TOKEN" | jq -er .version)
: "${VERSION:?could not read /v1/operator-settings: this step needs rbac:read too}"

curl -s -X PUT https://cp.example.com/v1/operator-settings/recording-customer-key \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "publicKey": "'"$(cat customer_pub.b64)"'",
        "sealAlgorithm": "ecies_p256",
        "version": '"$VERSION"' }'
```

The `curl -sf` and the `:?` guard are load-bearing. Without them a `403` on
the first line yields the string `null`, the `PUT` sends `"version": null`,
and you get a body error on the second call for a permission problem on the
first.

The key is parsed before anything is stored: a private key, a PEM blob, a
curve that does not match `sealAlgorithm`, and garbage bytes are each
rejected with a `422`. That check happens here rather than at the first
session, so a bad key fails while you are looking at it.

`recording:key-manage` is its own permission and no other administrative task
uses it. Whoever holds it can point future recordings at a key they control,
which is the one privilege that breaks the platform's inability to read its
own recordings, so it is deliberately not folded into `settings:write`.

> **Warning:** a fresh install has no customer key, and because recording is
> strict, sessions are refused until you provision one. That is deliberate
> fail-closed behavior. The alternative would be storing your users'
> keystrokes in the clear. Provision the key as part of install, before first
> use.

Move `customer-recording-key.pem` to your offline store now and delete the
local copy. You will need it only in the browser, at replay time.

> **Warning:** replacing this key later is forward-only. Recordings sealed
> under the outgoing key stay readable only by the outgoing private key, and
> the new key cannot read them. Keep every retired private key for at least as
> long as the recordings sealed under it.

## Rotate the customer key

A `PUT` when a key is already configured is a rotation, and needs two fields a
first provisioning does not: `expectedFingerprintSha256`, the lowercase hex
SHA-256 of the key you are replacing (a mismatch is a `409`, so a blind or
racing overwrite cannot succeed), and
`acknowledgeExistingRecordingsUndecryptable`, a boolean that must be `true`.
The fingerprint comes from the platform, not from your own copy of the key:
`GET /v1/operator-settings/recording-customer-key` returns it over the DER
SubjectPublicKeyInfo, which is the encoding the server hashed. The `version`
is the parent resource's, because both paths write the same singleton row and
share its counter.

```bash
FPR=$(curl -sf https://cp.example.com/v1/operator-settings/recording-customer-key \
  -H "Authorization: Bearer $TOKEN" | jq -er .fingerprintSha256)
VERSION=$(curl -sf https://cp.example.com/v1/operator-settings \
  -H "Authorization: Bearer $TOKEN" | jq -er .version)
: "${FPR:?could not read the current key}" "${VERSION:?could not read the settings version}"

openssl ecparam -name prime256v1 -genkey -noout -out customer-recording-key-2.pem
openssl ec -in customer-recording-key-2.pem -pubout -outform DER | base64 -w0 > customer_pub2.b64

curl -s -X PUT https://cp.example.com/v1/operator-settings/recording-customer-key \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "publicKey": "'"$(cat customer_pub2.b64)"'",
        "sealAlgorithm": "ecies_p256",
        "expectedFingerprintSha256": "'"$FPR"'",
        "acknowledgeExistingRecordingsUndecryptable": true,
        "version": '"$VERSION"' }'
```

Both extra fields are refused with a `422` on a first provisioning, where no
key and no recording exists: a caller that believes it is replacing a key when
there is none has lost track of the cluster's state. Move the new private half
offline as before, and keep the old one.

## Choose a WORM mode

Recordings land in an object-lock (WORM) S3-compatible bucket, configured by
`sessionlayer.recording.worm.*` (endpoint, bucket, region, credentials). The
bucket is created object-lock-enabled at startup, and the lock mode and
retention are baked into the signed upload. The uploader physically cannot
strip them. Two modes, chosen per deployment (the default is `governance`):

| | `compliance` | `governance` |
|---|---|---|
| Can *anyone* delete before retention expires? | No: not admins, not the platform, not the storage root account | Only a holder of `recording:delete`, audited, and never under legal hold |
| Legal/regulatory posture | maximum tamper evidence; suits regimes that mandate immutability (e.g. SOX/PCI-style retention) | immutability against everyone except a designated, audited erasure role |
| GDPR erasure | only by crypto-shred: destroying your customer key material, which is in your hands, not the platform's | the escape hatch: delete the object (every version), keep the audited metadata |

> **Warning:** compliance mode is a one-way door per object. If your regime
> requires the *ability* to erase (GDPR Art. 17), use governance mode. In
> compliance mode the platform genuinely cannot erase a recording, and
> "erasure" reduces to destroying the decryption key you hold, which makes
> every recording sealed under that key unreadable, not the one recording a
> data subject asked about. There is no per-recording shred. That tension
> between immutability and erasure is yours to resolve as data controller;
> the platform gives you both controls and records which you chose.

Set the mode, and the retention that goes with it, on the operator settings
resource (`settings:write`):

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
        | .defaultWormMode = "compliance"')"
```

Both fields move one way only. `governance` to `compliance` is accepted and
the reverse is a `422`, because it would make recordings that are currently
undeletable deletable. Retention likewise increases or stays put. The
restriction holds at every permission level, so weakening either one is a
deliberate out-of-band act by the database owner rather than an API call
someone can make in a hurry. Both apply to recordings made from then on, not
retroactively.

Default retention is 365 days; retention, legal hold, and governance deletion
are covered in [Audit](audit.md).

### Weaken the setting back: a database-owner operation

Reverting `defaultWormMode` to `governance`, or shortening either retention
window, is refused by the API at every permission level. It is available to
the owner of the Control Plane's database, and only there. Out-of-band
difficulty is the control; there is no missing feature and no escape hatch to
enable.

`$CP_DATABASE_URL` is an owner-role Postgres connection string for the Control
Plane's database, the same one the
[hardening guide](../security/hardening.md) uses. `config.operator_settings`
is a single-row table, so the `WHERE` clause is the singleton guard:

```bash
psql "$CP_DATABASE_URL" <<'SQL'
UPDATE config.operator_settings
   SET default_worm_mode = 'governance',
       version = version + 1,
       updated_at = now()
 WHERE singleton = true
RETURNING default_worm_mode, recording_retention_days, audit_retention_days, version;
SQL
```

```text
 default_worm_mode | recording_retention_days | audit_retention_days | version
-------------------+--------------------------+----------------------+---------
 governance        |                      365 |                  365 |       2
(1 row)

UPDATE 1
```

Shortening retention is the same statement with
`recording_retention_days` or `audit_retention_days` set instead. Bump
`version` in the same statement whichever column you touch: the API uses it
for optimistic concurrency, and a write that leaves it alone lets an admin
holding a pre-edit copy overwrite your change without a `409`.

Four things to know before you run it:

- No restart. Every `BeginRecording` re-reads this row, so the next session
  recorded after the commit uses the new mode. Nothing is cached and no
  Control Plane needs stopping.
- Nothing already written changes. The mode is stamped onto each object's
  lock at upload time. Recordings written while `compliance` was in force stay
  un-deletable for their full retention window after the revert, by anyone,
  including the storage root account. That is what compliance mode means.
- The database enforces the value, not the direction. `default_worm_mode`
  carries a `CHECK (default_worm_mode IN ('compliance', 'governance'))` and no
  trigger. The ratchet lives in the Control Plane's API layer, so the owner
  role is not fighting the schema.
- Verify through the API, not only in `psql`:
  `curl -s https://cp.example.com/v1/operator-settings -H "Authorization: Bearer $TOKEN" | jq '{defaultWormMode, version}'`.

## Replay a recording

Replay happens in the Dashboard, and decryption happens in your browser:

1. Find the session under **Recordings** (filter by user, node, or session
   id), and open **Replay**.
2. The Dashboard calls `POST /v1/recordings/{id}/replay`, receiving a
   signed, single-object GET URL (5-minute lifetime) for the still-encrypted
   object. The bytes never pass through the Control Plane.
3. When prompted, provide the customer recording *private* key. It is used
   via the browser's WebCrypto to unseal the recording locally and never
   leaves the browser: no upload, no caching server-side.
4. Watch the terminal replay with real timing, keystrokes included.

Replay requires the `recording:replay` platform permission, honors node-label
/ user / time scoping, and is itself an audited action: "who watched this
session, when" is one query away, in the same stream as the session itself.

## Export a recording

```bash
# RECORDING_ID from GET /v1/recordings (filter by sessionId, identity, or nodeId).
# $TOKEN is an admin bearer; see Authentication.
curl -s -X POST https://cp.example.com/v1/recordings/$RECORDING_ID/export \
  -H "Authorization: Bearer $TOKEN"
```

The response is a signed URL for the encrypted object (`recording:export`
permission, audited, scoped like replay). What you download is SLREC1
ciphertext. Decrypting it outside the Dashboard requires your private key
and an SLREC1-format unwrap (ECIES-P256 key unwrap, then AES-256-GCM
frames).

> **Note:** a signed URL cannot be revoked within its 5-minute lifetime.
> That window is the accepted trade for never proxying bytes through the
> Control Plane. It is mitigated by the URL being single-object, short-lived,
> and pointing at ciphertext only.

## Tamper evidence

Every recording carries a hash chain over its sealed event stream plus a
whole-object digest, both committed write-once in the Control Plane's
metadata. Recompute the chain from a decrypted object and compare heads:
alteration, removal, or reordering of any event changes the head. Combined
with WORM object-lock this is the baseline tamper evidence; an
externally-anchored Merkle root (proof against a *fully* compromised
platform) is deliberately deferred and documented in the
[trust model](../security/trust-model.md).

## Next

- [Audit](audit.md): retention, legal hold, governance delete, and the
  correlated event stream.
- [Trust model](../security/trust-model.md): exactly what the platform can
  and cannot see.
- [Production hardening](../security/hardening.md): compliance-WORM and
  customer-key preconditions for go-live.
- [File transfer](../user-guide/file-transfer.md): the user's view of
  SFTP/SCP through the platform.
