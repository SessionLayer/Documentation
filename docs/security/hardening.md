# Production hardening

This is the go-live runbook. SessionLayer's production sign-off is
explicitly *"production-grade under the operator preconditions"* — and this
page is those preconditions, as an ordered checklist with commands. Work
through it top to bottom before the platform carries real access; every item
here exists because skipping it re-opens a documented risk.

The quick self-audit:

- [ ] 1. Clocks NTP-synced; kernels support Landlock (≥ 6.7 on arm64)
- [ ] 2. Real `cp_runtime` DB password; restricted role verified; Postgres HA
      with synchronous replication for authz/audit
- [ ] 3. Every CA on KMS / Key Vault / Vault — nothing on `local`, no dev KEK
- [ ] 4. Customer recording key provisioned; private half offline
- [ ] 5. WORM mode chosen deliberately; audit forwarded off-box to a SIEM
- [ ] 6. A session-limit cluster default set (the shipped default is
      **unlimited**)
- [ ] 7. Gateway running the hardened profile; default-deny NetworkPolicy /
      firewall applied
- [ ] 8. Agents verify-before-run with a CT-pinned `trusted_root.json`
- [ ] 9. Break-glass FIDO2 keys are touch-required
- [ ] 10. HTTPS on every credential-bearing origin
- [ ] 11. (HA only) NATS bus authenticated + TLS; shared OIDC state key
- [ ] 12. (arm64 only) hardened end-to-end validated on your arm hardware

## 1. Foundations: time and kernels

Certificates are backdated for skew and the Gateway expires grants
conservatively, but NTP discipline is an assumption, not an option — minutes
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

> **Warning:** on a kernel without Landlock the components start anyway, with
> a loud logged degrade — that is the one deliberate fail-open in the
> hardening stack. If your regime cannot accept the degrade, run the Agent
> with `--require-full-landlock`, which aborts instead.

## 2. The database: restricted role, real password, synchronous replication

The Control Plane's runtime connects as **`cp_runtime`**, a restricted role
created by the migrations: no DDL, no superuser, and — the load-bearing part
— **no `UPDATE`/`DELETE`/`TRUNCATE` on the audit table**. A compromised
Control Plane process therefore cannot erase its own audit trail.

Set a real password **before first boot** — the migration sets it exactly
once, from a Flyway placeholder, and ships a dev default:

```properties
# Control Plane configuration — both MUST be set to the same real secret
# before the first migration runs (alphanumeric; no quotes or backslashes):
spring.flyway.placeholders.cpRuntimePassword=use-a-generated-secret-here
spring.r2dbc.password=use-a-generated-secret-here
```

Rotate later out-of-band: `ALTER ROLE cp_runtime PASSWORD '...'` as the DB
owner, plus a rolling restart with the updated `spring.r2dbc.password`.
Verify the restriction actually holds:

```bash
psql "$CP_DATABASE_URL" -c "SET ROLE cp_runtime; DELETE FROM runtime.audit_event WHERE false;"
# expect: ERROR:  permission denied for table audit_event
```

The same logic extends above the application role: restrict who holds actual
Postgres **superuser** on this cluster — the audit trail's non-repudiation
depth assumes both the app's role *and* casual superuser access are
constrained, because a superuser can defeat the append-only trigger (the
Merkle-deferral risk in the [trust model](trust-model.md)).

Authorization and audit writes are the platform's record of truth, so run
Postgres HA with **synchronous replication** covering them — an async-only
setup can acknowledge an authorization or an audit row and then lose it in a
failover. Give the Control Plane's startupProbe **at least 150 seconds**:
worst-case first boot (CA cold start + bootstrap + audit partitions) blocks
that long by design rather than hang half-ready.

## 3. CAs: off `local`, onto KMS / Key Vault / Vault

The `local` backend keeps CA private keys in-process, envelope-encrypted
under a KEK — a dev convenience. In production, every CA's private key
belongs in a real key service, where signing happens without the key ever
entering the Control Plane's memory:

```bash
# Move the session CA to Vault's SSH engine (repeat per CA — user, session, host).
# CA_ID from GET /v1/cas; VERSION is the resource's current version.
curl -s -X PUT https://cp.example.com/v1/cas/$CA_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "backend": "vault",
    "keyReference": "ssh-client-signer/roles/sessionlayer-session",
    "algorithm": "ecdsa-p256",
    "version": '$VERSION'
  }'
```

Use different backends (or at least different key hierarchies) per CA for
custody separation — the session CA is the one that mints what nodes trust.
With Vault, the platform uses the sign-only endpoint (`/ssh/sign`); it never
calls `/ssh/issue`, which returns private keys.

> **Warning:** the Control Plane **fails closed at startup** if it finds the
> well-known dev KEK on a local CA without an explicit override. Do not set
> the override in production — if you see that failure, the fix is this step,
> not the escape hatch.

## 4. The customer recording key

Without it, recording cannot seal and (strict default) sessions are refused.
With it, recordings are unreadable to the platform — including to a fully
compromised Control Plane. Generate, store the public half, and take the
private half offline:

```bash
openssl ecparam -name prime256v1 -genkey -noout -out customer-recording-key.pem
openssl ec -in customer-recording-key.pem -pubout -outform DER | base64 -w0 > customer_pub.b64

psql "$CP_DATABASE_URL" -c "UPDATE config.operator_settings
  SET recording_customer_public_key = decode('$(cat customer_pub.b64)', 'base64')
  WHERE singleton = true;"
```

Move `customer-recording-key.pem` into your offline key store (HSM-backed
where available) and delete local copies. Whoever holds this key can decrypt
every recording; losing it makes every recording permanently unreadable —
treat both directions seriously. Details:
[Session recording](../admin-guides/session-recording.md).

## 5. WORM mode and the off-box SIEM forward

Choose the object-lock mode deliberately — `compliance` (nothing can delete
before retention, erasure = crypto-shred by you) for maximum tamper
resistance, `governance` (audited privileged deletion) where erasure duties
apply. Keep retention at or above 12 months for PCI/SOC 2/ISO-style regimes.

Then ship audit off-box: the platform's tamper evidence is hash-chain +
WORM, **without** an external anchor (deferred — see the
[trust model](trust-model.md)), so an independent, real-time copy of the
stream in your SIEM is your resistance against a privileged attacker
truncating history at the source. The default forwarder emits every
committed event as a structured `audit.forward` JSON log line, chain hashes
included — point your collector at the Control Plane's logs, or install a
native `AuditForwarder` connector ([Audit](../admin-guides/audit.md)).

## 6. Set a session-limit cluster default

The shipped default is **unlimited** — the Control Plane warns at boot until
you set it:

```properties
sessionlayer.session-limits.default-max-concurrent=3
sessionlayer.session-limits.default-max-session-seconds=28800
sessionlayer.session-limits.default-idle-timeout-seconds=1800
```

See [Session limits](../admin-guides/session-limits.md) for how each knob is
enforced.

## 7. Gateway: hardened profile + default-deny network

The Gateway is Tier-0 — the only place session plaintext exists. Run it with
the full in-process profile (privilege drop after binding `:22`, seccomp
enforce, Landlock, coredumps off):

```jsonc
// /etc/sessionlayer/gateway.json — the hardening block
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
requested but cannot apply **aborts startup** — the Gateway does not run
half-hardened. Coredumps are off by default; leave them off (a core file
from this process is session plaintext), and disable or encrypt swap on
Gateway hosts.

Then apply the **default-deny egress** layer — seccomp cannot filter by
destination, so network confinement is the second layer. On Kubernetes,
apply the shipped policy (permits only: cluster DNS, the Control Plane's
gRPC port, your node subnet on 22, and the WORM store) after scoping its
CIDRs to your fleet:

```bash
kubectl apply -f Gateway/deploy/kubernetes/networkpolicy.yaml
```

On bare metal, use the shipped systemd unit (OS sandbox directives +
capability bounding) and express the same egress set in nftables. The
deployment reference, including the container securityContext, lives in the
Gateway repository's `deploy/` directory and in
[Install the Gateway](../installation/gateway.md).

## 8. Agents: verify-before-run, with a CT-pinned trust root

Nodes must refuse to run or update to an unverified Agent binary. Pin the
Sigstore trust root by digest, once, from the authentic TUF distribution:

```bash
cosign trusted-root create > trusted_root.json
sha256sum trusted_root.json   # record and pin this digest in your config management
```

> **Warning:** production `trusted_root.json` must include CT logs (the
> standard Sigstore root does). The verifier requires the signing
> certificate's CT proof *when the trust root carries CT keys* — and a trust
> root that declares CT logs but has no usable key fails closed. A stripped,
> CT-less trust root silently disables that check; only ship a root you
> fetched from the authentic TUF source and pinned by digest.

Then run every Agent with self-verification, and verify before every
install: the exact commands are in [Supply chain](supply-chain.md). Refresh
and re-pin the trust root quarterly and on Sigstore rotation announcements —
a *fleet-wide* verification failure right after a rotation is the stale-root
symptom, and the fix is refresh-and-repin, never disabling verification.

## 9. Touch-required FIDO2 break-glass keys

Provision every break-glass key with touch required —
`ssh-keygen -t ecdsa-sk` default, never `-O no-touch-required`. The platform
cannot enforce user presence at the Gateway (accepted risk BG-1 — see the
[trust model](trust-model.md)); the key's own touch requirement is the
control. Full procedure:
[Break-glass access](../admin-guides/break-glass.md).

## 10. HTTPS everywhere

Every credential-bearing origin — the Control Plane API, the OIDC endpoints,
the Dashboard, the object store presigned URLs — must be HTTPS. The
Dashboard enforces this at build time: a production build pointing a
credential-bearing endpoint at cleartext `http` **fails the build** (with a
runtime backstop in its API client). Don't fight the guard; fix the URL.

## 11. HA-only additions

If you run [HA](../admin-guides/high-availability.md):

- The bundled NATS client speaks plaintext, unauthenticated — front the
  broker with a TLS-terminating, authenticating sidecar (or a leaf-node TLS
  boundary) with subject authorization. The client fails loud, not open, if
  the broker demands what it cannot speak.
- Set the shared `sessionlayer.oidc.state-hmac-key` on every Control Plane
  instance so logins begun on one instance complete on another.
- The synchronous-replication requirement from step 2 is doubly load-bearing
  here.

## 12. arm64 validation

aarch64 is supported and CI-checked at build level, but the hardened
end-to-end suite runs on x86_64 runners. Before an arm64 production rollout,
run one full session (shell + exec + SFTP, recording verified) against your
arm hardware with seccomp `enforce` + Landlock on, and confirm kernel ≥ 6.7
for the network-egress piece (step 1).

## Next

- [Trust model](trust-model.md) — why each item above exists.
- [Supply chain](supply-chain.md) — the verification commands step 8 points
  at.
- [Monitoring](../operations/monitoring.md) — the alerts that tell you a
  precondition regressed.
- [Install the Gateway](../installation/gateway.md) — the deployment
  artifacts referenced in step 7.
