# Session recording

Every session through SessionLayer is recorded — output **and keystrokes** —
sealed to a key that only you hold, and written to write-once storage. This
guide shows you how to provision the customer recording key, choose a WORM
mode, and replay or export recordings.

The single most important fact on this page: **the platform cannot read its
own recordings.** Each recording is encrypted to your (the operator's) public
key; the Control Plane stores only that public half, and the private half
never touches any SessionLayer component. A platform admin, a compromised
Control Plane, or SessionLayer's own developers can produce ciphertext — and
nothing else. Secrets typed at prompts are captured, but unreadable *from
the stored recording* to everyone except the holder of your key. The one
component that does see session plaintext — live, at capture, before sealing
— is the Gateway itself; that is the Tier-0 trade stated in the
[trust model](../security/trust-model.md), and why the
[hardening checklist](../security/hardening.md) treats Gateway placement and
integrity as preconditions.

## What gets captured

- **Terminal sessions** — asciicast v2: output, keystrokes, and window
  resizes, with real timing. Keystroke capture closes the "user hid the
  command behind a shell trick" gap.
- **Commands** — non-interactive `exec` runs record the command string and
  its output.
- **File transfers** — the SFTP protocol is decoded into a per-operation
  audit: operation, path, direction, size, and a streaming SHA-256 of the
  content. For SFTP (including modern `scp`, which rides the SFTP
  subsystem), **file content is never captured** — bytes are streamed into
  the hash and discarded.

> **Note:** one honest edge: legacy `scp` runs over an `exec` channel, and
> every exec channel is always terminal-captured (otherwise a crafted command
> line could suppress its own recording). So a legacy-protocol `scp`
> transfer's raw bytes do land inside the sealed recording, alongside its
> file-transfer audit. Modern OpenSSH (9.0+) uses SFTP for `scp` and is
> content-free.

Recording is **strict by default**: if a recording cannot start or fails
mid-session, the session is refused or torn down. No recording, no session.

## Provision the customer recording key

### Prerequisites

- [ ] Access to the Control Plane's Postgres (this is a deployment-level
      setting, deliberately not writable through the REST API).
- [ ] Somewhere genuinely offline to keep the private key — an HSM-backed
      store or your organization's key vault. Whoever holds it can decrypt
      every recording.

Generate a P-256 keypair and store the **public** half (DER SPKI) in the
operator settings row:

```bash
openssl ecparam -name prime256v1 -genkey -noout -out customer-recording-key.pem
openssl ec -in customer-recording-key.pem -pubout -outform DER | base64 -w0 > customer_pub.b64

psql "$CP_DATABASE_URL" -c "UPDATE config.operator_settings
  SET recording_customer_public_key = decode('$(cat customer_pub.b64)', 'base64')
  WHERE singleton = true;"
```

`$CP_DATABASE_URL` is your Control Plane's Postgres connection string. The
stored bytes are validated as a well-formed P-256 public key — pasting
garbage, a truncated blob, or (the scary one) a private key fails validation
and recording refuses to start rather than seal to junk.

> **Warning:** a fresh install has **no** customer key, and with strict
> recording on (the default), sessions are refused until you provision one.
> That is deliberate fail-closed behavior — the alternative would be storing
> your users' keystrokes in the clear. Provision the key as part of install,
> before first use.

Move `customer-recording-key.pem` to your offline store now and delete the
local copy. You will need it only in the browser, at replay time.

## Choose a WORM mode

Recordings land in an object-lock (WORM) S3-compatible bucket, configured by
`sessionlayer.recording.worm.*` (endpoint, bucket, region, credentials). The
bucket is created object-lock-enabled at startup, and the lock mode and
retention are baked into the signed upload — the uploader physically cannot
strip them. Two modes, chosen per deployment in operator settings
(`default_worm_mode`; the default is `governance`):

| | `compliance` | `governance` |
|---|---|---|
| Can *anyone* delete before retention expires? | **No** — not admins, not the platform, not the storage root account | Only a holder of `recording:delete`, audited, and never under legal hold |
| Legal/regulatory posture | maximum tamper evidence; suits regimes that mandate immutability (e.g. SOX/PCI-style retention) | immutability against everyone *except* a designated, audited erasure role |
| GDPR erasure | only by **crypto-shred** — destroying your customer key material, which is in your hands, not the platform's | the escape hatch: delete the object (every version), keep the audited metadata |

> **Warning:** compliance mode is a one-way door per object. If your regime
> requires the *ability* to erase (GDPR Art. 17), use governance mode — in
> compliance mode the platform genuinely cannot erase a recording, and
> "erasure" reduces to destroying the decryption key you hold. That tension
> between immutability and erasure is yours to resolve as data controller;
> the platform gives you both controls and records which you chose.

Default retention is 365 days; retention, legal hold, and governance deletion
are covered in [Audit](audit.md).

## Replay a recording

Replay happens in the Dashboard, and decryption happens **in your browser**:

1. Find the session under *Recordings* (filter by user, node, or session id),
   and open *Replay*.
2. The Dashboard calls `POST /v1/recordings/{id}/replay`, receiving a signed,
   single-object GET URL (5-minute lifetime) for the still-encrypted object —
   the bytes never pass through the Control Plane.
3. When prompted, provide the customer recording **private** key. It is used
   via the browser's WebCrypto to unseal the recording locally and **never
   leaves the browser** — no upload, no caching server-side.
4. Watch the terminal replay with real timing, keystrokes included.

Replay requires the `recording:replay` platform permission, honors node-label
/ user / time scoping, and is itself an audited action — "who watched this
session, when" is one query away, in the same stream as the session itself.

## Export a recording

```bash
# RECORDING_ID from GET /v1/recordings (filter by sessionId, identity, or nodeId).
curl -s -X POST https://cp.example.com/v1/recordings/$RECORDING_ID/export \
  -H "Authorization: Bearer $TOKEN"
```

The response is a signed URL for the **encrypted** object (`recording:export`
permission, audited, scoped like replay). What you download is SLREC1
ciphertext — decrypting it outside the Dashboard requires your private key
and an SLREC1-format unwrap (ECIES-P256 key unwrap, then AES-256-GCM frames).

> **Note:** a signed URL cannot be revoked within its 5-minute lifetime.
> That window is the accepted trade for never proxying bytes through the
> Control Plane — mitigated by the URL being single-object, short-lived, and
> pointing at ciphertext only.

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

- [Audit](audit.md) — retention, legal hold, governance delete, and the
  correlated event stream.
- [Trust model](../security/trust-model.md) — exactly what the platform can
  and cannot see.
- [Production hardening](../security/hardening.md) — compliance-WORM and
  customer-key preconditions for go-live.
- [File transfer](../user-guide/file-transfer.md) — the user's view of
  SFTP/SCP through the platform.
