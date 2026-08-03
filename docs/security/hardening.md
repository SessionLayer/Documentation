# Production hardening

SessionLayer's production sign-off is explicitly production-grade under the
operator preconditions, and this page is those preconditions: an ordered
checklist with commands. Work through it top to bottom before the platform
carries real access. Every item here exists because skipping it reopens a
documented risk.

The quick self-audit:

- [ ] 1. Clocks NTP-synced; kernels support Landlock (at or above 6.7 on
      arm64)
- [ ] 2. Real `cp_runtime` DB password; restricted role verified; Postgres HA
      with synchronous replication for authz/audit
- [ ] 3. A real generated KEK protecting every CA still on `local` (never the
      dev default); SSH CAs optionally adopted onto `azure_keyvault`
- [ ] 4. Customer recording key provisioned; private half offline
- [ ] 5. WORM mode chosen deliberately; audit forwarded off-box to a SIEM
- [ ] 6. A session-limit cluster default set (the shipped default is
      unlimited)
- [ ] 7. Gateway running the hardened profile; default-deny NetworkPolicy /
      firewall applied
- [ ] 8. Agents verify-before-run with a CT-pinned `trusted_root.json`
- [ ] 9. Break-glass FIDO2 keys are touch-required
- [ ] 10. HTTPS on every credential-bearing origin
- [ ] 11. (HA only) NATS bus authenticated + TLS via a per-Gateway sidecar,
      never on the broker the Gateways dial; shared OIDC state key
- [ ] 12. (arm64 only) hardened end-to-end validated on your arm hardware

## 1. Foundations: time and kernels

Certificates are backdated for skew and the Gateway expires grants
conservatively, but NTP discipline is an assumption, not an option. Minutes
of divergence on a node makes its `sshd` reject inner certificates. On every
Control Plane, Gateway, and node host:

```bash
timedatectl show -p NTPSynchronized    # expect: NTPSynchronized=yes
```

Landlock is part of the Gateway/Agent sandbox. Verify the kernel offers it:

```bash
grep -i landlock /boot/config-$(uname -r)   # expect CONFIG_SECURITY_LANDLOCK=y and landlock in CONFIG_LSM
uname -r                                    # arm64 hosts need >= 6.7 for network-egress Landlock
```

The rule for a hardening step that does not apply turns on why it did not. A
step that is requested and rejected fails startup: `run_as_user` on a process
that is not root, an unknown user, a Landlock or seccomp rule the kernel
supports but refuses. A kernel that lacks Landlock or seccomp entirely is the
single exception, and it degrades with a loud warning instead of refusing to
start.

> **Warning:** that exception is the one deliberate fail-open in the hardening
> stack, and it is opt-out on both Tier-0 components. Set
> `hardening.landlock.required` in the Gateway's config to make anything short
> of full enforcement abort startup, including the partial enforcement an older
> kernel ABI gives you
> ([Gateway configuration](../reference/config-gateway.md)). Run the Agent with
> `--require-full-landlock` for the same effect. Set both if your regime cannot
> accept a silently unconfined host, and lean on the container's read-only
> rootfs and dropped capabilities anywhere you cannot.

## 2. The database: restricted role, real password, synchronous replication

The Control Plane's runtime connects as `cp_runtime`, a restricted role
created by the migrations: no DDL, no superuser, and, the load-bearing part,
no `UPDATE`/`DELETE`/`TRUNCATE` on the audit table. A compromised Control
Plane process therefore cannot erase its own audit trail.

Set a real password before first boot: the migration sets it exactly once,
from a Flyway placeholder, and ships a dev default:

```properties
# Control Plane configuration: both MUST be set to the same real secret
# before the first migration runs (alphanumeric; no quotes or backslashes):
spring.flyway.placeholders.cpRuntimePassword=use-a-generated-secret-here
spring.r2dbc.password=use-a-generated-secret-here
```

Rotate later out-of-band: `ALTER ROLE cp_runtime PASSWORD '...'` as the DB
owner, plus a rolling restart with the updated `spring.r2dbc.password`.
Verify the restriction actually holds (`$CP_DATABASE_URL` is an owner-role
Postgres connection string for the Control Plane's database; `$TOKEN`, used
below, is an admin bearer. If you do not have one yet, obtaining the first
without any database access is
[part of the install](../installation/control-plane.md), and
[Authentication](../admin-guides/authentication.md) covers the schemes):

```bash
psql "$CP_DATABASE_URL" -c "SET ROLE cp_runtime; DELETE FROM runtime.audit_event WHERE false;"
# expect: ERROR:  permission denied for table audit_event
```

### What still needs the owner role

Locking the database down only works if you know what still reaches past
`cp_runtime`. Five procedures do. None belongs to an install, none is
routine, and each is here for a reason that does not expire:

| Procedure | Why the owner role, permanently |
|---|---|
| The verification above, and password rotation | `SET ROLE` and `ALTER ROLE` are owner operations by definition. An API that could grant them would be the owner |
| Fencing a database you are restoring away from | `REVOKE CONNECT` and `ALTER DATABASE` act on a cluster the Control Plane must not be connected to, so the Control Plane cannot be the thing that cuts it off |
| Rebuilding the internal mTLS CA | Every Control Plane instance has to be stopped first. No running Control Plane can offer an operation whose precondition is that it is not running |
| Shortening retention, or moving WORM back to `governance` | The API moves both in the safe direction only, at every permission level, because the other direction destroys evidence in one call. Out-of-band difficulty is the control here, not a missing feature |
| Capturing the audit chain head during a restore | It happens before any Control Plane starts, and starting one writes events that move the head you are trying to record |

The last three are covered where they arise, each with the statement to run:
rebuilding the internal mTLS CA and capturing the audit chain head in
[Disaster recovery](../operations/disaster-recovery.md), and weakening
retention or WORM mode in
[Session recording](../admin-guides/session-recording.md#weaken-the-setting-back-a-database-owner-operation).

Everything else in this guide, and the whole of installation, runs against
the REST API with a platform-RBAC token. You configure the Control Plane with
database credentials of its own, for Flyway and for `cp_runtime`, and after
that you never use one to drive the platform: claiming the first admin,
enrolling a Gateway, distributing CA trust, provisioning the recording key,
and reaching a recorded session that decrypts are all API calls.

The same logic extends above the application role: restrict who holds
actual Postgres superuser on this cluster. The audit trail's
non-repudiation depth assumes both the app's role and casual superuser
access are constrained, because a superuser can defeat the append-only
trigger (the Merkle-deferral risk in the [trust model](trust-model.md)).

Authorization and audit writes are the platform's record of truth, so run
Postgres HA with synchronous replication covering them. An async-only setup
can acknowledge an authorization or an audit row and then lose it in a
failover. Give the Control Plane's startupProbe comfortably more than 150
seconds, which is a measured first boot on one machine rather than a
guaranteed ceiling:
worst-case first boot (CA cold start, bootstrap, and audit partitions)
blocks that long by design rather than hang half-ready.

## 3. CA backends: `local`, and a key service for the three SSH CAs

Three of the four backends sign on the shipped build, and each key service stays
off until you configure it.

| Backend | Signs | Configured by |
|---|---|---|
| `local` | yes | nothing to set; every CA starts here at cold start |
| `azure_keyvault` | yes | `sessionlayer.ca.azure.*` |
| `aws_kms` | yes | `sessionlayer.ca.aws.*` |
| `vault` | no | not implemented in this build |

> **Warning:** `vault` still refuses `POST /v1/cas` and `PUT /v1/cas/{caId}`
> with a `422` saying the backend has no signer in this build. There is no
> configuration that turns it on, and a row that already carries it cannot
> issue: the failure surfaces at the first session or host certificate, which
> stops the platform brokering sessions. A Control Plane that has not
> configured `sessionlayer.ca.azure.*` or `sessionlayer.ca.aws.*` refuses that
> backend the same way, naming the property to set.

The internal mTLS CA is different: it cannot move to a key service at all. It
is deliberately absent from `/v1/cas` and has no rotate operation, so it stays
on `local` for the life of a deployment, and the KEK below protects it
regardless of what you do with the three SSH CAs. See
[Certificate authorities](../admin-guides/certificate-authorities.md)
for the two adoption procedures, and
[Data model](../reference/data-model.md#enums) for why the stored backend set
is wider than the usable one.

For every CA still on `local` — the internal mTLS CA always, the three SSH CAs
by default — the private key lives in the Control Plane's process,
envelope-encrypted under a key-encryption key sourced from operator
configuration, never from the database:

```properties
# 32 bytes, base64. Generate with: openssl rand -base64 32
sessionlayer.ca.local.kek-base64=<a real generated 32-byte key>
# Optional label recorded alongside wrapped material; never the key itself.
sessionlayer.ca.local.kek-reference=kms://your-org/sessionlayer-cp-kek
```

> **Warning:** the built-in dev KEK is a public constant, so a CA key wrapped
> under it is not protected at all. The Control Plane refuses to start when it
> is in effect unless `sessionlayer.ca.local.allow-dev-kek=true` is explicitly
> set. Never set that in production. If you hit the refusal, the fix is to set
> a real KEK, not the override.

The KEK must be stable across restarts, because cold start has to unwrap the CA
keys it wrapped on a previous boot. Hold it wherever you hold your other
process-level secrets, keep it out of the database and out of the same backup
stream as the database, and rotate it with the CA rotation procedure rather than
in place.

Adopting a key service for a SSH CA narrows the KEK's blast radius; it does not
remove the need for it. The internal mTLS CA's key never leaves the database,
so a database-plus-KEK compromise still forges signed authorization decisions
and impersonates the Control Plane to every Gateway and Agent, even on a
deployment that has moved every SSH CA off `local`. The compensating controls
for whatever remains on `local` are the ones in step 2: the restricted
`cp_runtime` role, constrained superuser access, and the host hardening in
step 7. The session CA is the one that mints what nodes trust, so treat a
Control Plane host as carrying that authority regardless of which backend
holds its key.

## 4. The customer recording key

Without it, recording cannot seal and, because recording is strict, sessions
are refused. With it, recordings are unreadable to the platform, including
to a fully compromised Control Plane. Generate, give the platform the public
half, and take the private half offline:

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

The `PUT` needs `recording:key-manage`, which nothing else on this checklist
uses, and the `GET` above it needs `rbac:read`. Neither implies the other.
Pointing recordings at a key someone controls is the one privilege that
breaks the platform's inability to read its own recordings, so it is not
folded into `settings:write`. Grant it as deliberately as you grant
`ca:manage`. The `-f` and the `:?` guard turn a `403` on the first line into a
loud failure there, instead of a `"version": null` body error on the second.
The submitted key is parsed before storage: private key material, a PEM blob,
a mismatched curve, and garbage are each a `422`.

Move `customer-recording-key.pem` into your offline key store (HSM-backed
where available) and delete local copies. Whoever holds this key can
decrypt every recording, and losing it makes every recording permanently
unreadable. Treat both directions seriously. Details:
[Session recording](../admin-guides/session-recording.md).

## 5. WORM mode and the off-box SIEM forward

This is the one step on the checklist with no right answer, and the one whose
wrong answer you cannot take back through the API. Decide before you paste
anything.

`governance`, the shipped default, is immutable against everyone except a
holder of `recording:delete`, whose deletions are audited and refused under
legal hold. `compliance` is immutable against everyone: not admins, not the
platform, not the storage root account, not you. Keep retention at or above 12
months for PCI/SOC 2/ISO-style regimes. Both are operator settings
(`settings:write`).

> **Warning:** `governance` to `compliance` is a one-way door, and this
> checklist does not choose for you. The API refuses the reverse with a `422`
> at every permission level, and reverting the setting releases nothing
> already written: every recording uploaded while `compliance` was in force
> stays un-deletable for its full retention window. If your regime requires
> the ability to erase (GDPR Art. 17), leave the mode at `governance`. Under
> `compliance`, answering an erasure request means destroying the customer
> private key, which makes every recording sealed under that key unreadable
> rather than the one that was asked about. The setting itself can be put
> back, by the database owner, with the procedure in
> [Session recording](../admin-guides/session-recording.md#weaken-the-setting-back-a-database-owner-operation).
> The locked objects cannot.

Set `WORM_MODE` to the mode you chose, then run the block. It is written so
that pasting it unedited leaves you on the reversible setting.

`PUT` replaces the whole resource: read it, apply your change, and send the
whole writable set back. The `jq` filter below is that set, complete. The
first four fields and `version` are required, so a body missing one is a
`400`; the three session-limit defaults are cleared by omission, and the
filter copies them from the `GET` so a deployment-pinned one is echoed back
unchanged rather than refused. Any field outside the set is a `400`. The
customer recording key is not in it: it is a separate sub-resource, and no
`PUT` here can change or clear the key step 4 provisioned. Field-by-field
rules: [Operator settings](../reference/api.md#the-writable-field-set).

```bash
WORM_MODE=governance     # or "compliance", having read the warning above

SETTINGS=$(curl -s https://cp.example.com/v1/operator-settings \
  -H "Authorization: Bearer $TOKEN")

curl -s -X PUT https://cp.example.com/v1/operator-settings \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$(printf %s "$SETTINGS" | jq --arg worm "$WORM_MODE" \
       '{auditRetentionDays, recordingRetentionDays,
          defaultWormMode, otpTtlSeconds, defaultMaxSessionSeconds,
          defaultIdleTimeoutSeconds, defaultMaxConcurrentSessions, version}
        | .defaultWormMode = $worm
        | .auditRetentionDays = 365
        | .recordingRetentionDays = 365')"
```

All three of these move in the safe direction only. Lengthening retention and
moving `governance` to `compliance` are accepted; the reverse is a `422` at
every permission level, because a single call in that direction destroys
evidence. Weakening one afterwards is the database-owner operation linked
above, on purpose.

Then ship audit off-box: the platform's tamper evidence is hash-chain plus
WORM, without an external anchor (deferred, see the
[trust model](trust-model.md)), so an independent, real-time copy of the
stream in your SIEM is your resistance against a privileged attacker
truncating history at the source. The default forwarder emits every
committed event as a structured `audit.forward` JSON log line, chain hashes
included. Point your collector at the Control Plane's logs, or install a
native `AuditForwarder` connector ([Audit](../admin-guides/audit.md)).

## 6. Set a session-limit cluster default

The shipped default is unlimited; the Control Plane warns at boot until you
set it:

```properties
sessionlayer.session-limits.default-max-concurrent=3
sessionlayer.session-limits.default-max-session-seconds=28800
sessionlayer.session-limits.default-idle-timeout-seconds=1800
```

> **Warning:** `default-max-session-seconds` is not the only bound on session
> length, and on a stock install it is not the binding one.
> `sessionlayer.authz.max-grant-ttl` defaults to `PT1H` and always applies, so
> the 28800 above yields a one-hour session until you raise the ceiling too.
> The complete formula is in
> [Session limits](../admin-guides/session-limits.md#what-bounds-a-sessions-duration),
> which also covers how each knob is enforced.

## 7. Gateway: hardened profile + default-deny network

The Gateway is Tier-0, the only place session plaintext exists. Run it with
the full in-process profile (privilege drop after binding `:22`, seccomp
enforce, Landlock, coredumps off):

```jsonc
// /etc/sessionlayer/gateway.json: the hardening block
"hardening": {
  "run_as_user": "sessionlayer",          // bare-metal: drop after bind; container: starts non-root
  "landlock": {
    "enabled": true,
    "read_only_paths": ["/etc/sessionlayer", "/etc/ssl/certs", "/etc/resolv.conf",
                        "/etc/hosts", "/etc/nsswitch.conf", "/lib", "/lib64", "/usr/lib",
                        "/dev", "/proc"],
    "read_write_paths": ["/var/lib/sessionlayer-gateway"]
  },
  "seccomp": { "mode": "enforce" }
}
```

Roll seccomp out as `off → log → enforce`: in `log` mode, run a full
shell/exec/SFTP session and confirm `dmesg`/auditd shows no unexpected
`SECCOMP` line before flipping to `enforce`. A hardening step that is
requested and rejected aborts startup, per step 1; a kernel with no Landlock
at all is the exception that degrades instead, and
`"landlock": { "required": true }` in the block above turns that case into an
abort as well. Set it on any host whose hardening you have to be able to
assert. Coredumps are off by default; leave them off (a core file from this
process is session plaintext), and disable or encrypt swap on Gateway hosts.

Then apply the default-deny egress layer: seccomp cannot filter by
destination, so network confinement is the second layer. On Kubernetes,
apply the shipped policy (it permits only cluster DNS, the Control Plane's
gRPC port, your node subnet on 22, and the WORM store) after scoping its
CIDRs to your fleet:

```bash
kubectl apply -f Gateway/deploy/kubernetes/networkpolicy.yaml
```

On bare metal, use the shipped systemd unit (OS sandbox directives and
capability bounding) and express the same egress set in nftables. The
deployment reference, including the container securityContext, lives in the
Gateway repository's `deploy/` directory and in
[Install the Gateway](../installation/gateway.md).

## 8. Agents: verify-before-run, with a CT-pinned trust root

Nodes must refuse to run or update to an unverified Agent binary. Pin the
Sigstore trust root by digest, once, from the authentic TUF distribution:

```bash
cosign trusted-root create --with-default-services > trusted_root.json
sha256sum trusted_root.json   # record and pin this digest in your config management
```

> **Warning:** `--with-default-services` needs cosign **v3.0.4 or newer**.
> Every release before it rejects the flag outright, including the whole 2.x
> line and 3.0.0–3.0.2 — being on 3.x is not sufficient. See
> [Supply chain](supply-chain.md) for the boundary and for what an omitted
> flag silently produces instead.
>
> **Warning:** production `trusted_root.json` must include CT logs (the
> standard Sigstore root does). The verifier requires the signing
> certificate's CT proof when the trust root carries CT keys, and a trust
> root that declares CT logs but has no usable key fails closed. A
> stripped, CT-less trust root silently disables that check. Only ship a
> root you fetched from the authentic TUF source and pinned by digest.

Then run every Agent with self-verification, and verify before every
install; the exact commands are in [Supply chain](supply-chain.md). Refresh
and re-pin the trust root quarterly and on Sigstore rotation announcements.
A fleet-wide verification failure right after a rotation is the stale-root
symptom, and the fix is refresh-and-repin, never disabling verification.

## 9. Touch-required FIDO2 break-glass keys

Provision every break-glass key with touch required: the
`ssh-keygen -t ecdsa-sk` default, never `-O no-touch-required`. The
platform cannot enforce user presence at the Gateway (accepted risk BG-1,
see the [trust model](trust-model.md)); the key's own touch requirement is
the control. Full procedure:
[Break-glass access](../admin-guides/break-glass.md).

> **Warning:** unlike every other item on this list, this one has no
> verification command. `GET /v1/breakglass/credentials` returns public
> metadata that does not include the flag, and nothing else can read it, so a
> registered credential cannot be surveyed for it afterwards. Treat it as a
> provisioning gate rather than an audit: on a fleet you inherited with
> credentials already registered, revoke and re-provision rather than assume.

## 10. HTTPS everywhere

Every credential-bearing origin, the Control Plane API, the OIDC endpoints,
the Dashboard, and the object store presigned URLs, must be HTTPS. The
Dashboard enforces this at build time: a production build pointing a
credential-bearing endpoint at cleartext `http` fails the build, with a
runtime backstop in its API client. Do not fight the guard; fix the URL.

## 11. HA-only additions

If you run [HA](../admin-guides/high-availability.md):

- Put the coordination bus behind TLS and authentication without asking the
  Gateway to speak either. The bundled NATS client is plaintext and
  unauthenticated by construction: it reads the broker's `INFO` greeting and
  stops reconnecting outright if that greeting advertises `tls_required` or
  `auth_required`. Turning TLS or credentials on at the broker the Gateways
  dial therefore takes HA signalling down fleet-wide, loudly and fail-closed,
  which is correct behavior and not what you wanted.

  The shape that works is a sidecar co-located with each Gateway, reached over
  loopback in plaintext, terminating TLS and authenticating outbound to the
  broker with subject authorization so only a node's owner can subscribe to
  its dial-back subject. The plaintext hop is then a loopback socket inside
  the Gateway's own network namespace, contained by the same default-deny
  policy as step 7. A broker-side sidecar does not work: the Gateway would
  still have to speak TLS to reach it. A deployment that would rather not run
  a sidecar can substitute its own TLS-capable `CoordinationBackend`
  implementation instead. See
  [High availability](../admin-guides/high-availability.md).
- Set the shared `sessionlayer.oidc.state-hmac-key` on every Control Plane
  instance so logins begun on one instance complete on another.
- The synchronous-replication requirement from step 2 is doubly load-bearing
  here.

## 12. arm64 validation

aarch64 is supported and CI-checked at build level, but the hardened
end-to-end suite runs on x86_64 runners. Before an arm64 production
rollout, run one full session (shell, exec, and SFTP, recording verified)
against your arm hardware with seccomp `enforce` and Landlock on, and
confirm kernel at or above 6.7 for the network-egress piece (step 1).

## Next

- [Trust model](trust-model.md): why each item above exists.
- [Supply chain](supply-chain.md): the verification commands step 8 points
  at.
- [Monitoring](../operations/monitoring.md): the alerts that tell you a
  precondition regressed.
- [Install the Gateway](../installation/gateway.md): the deployment
  artifacts referenced in step 7.
