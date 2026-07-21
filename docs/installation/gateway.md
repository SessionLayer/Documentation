# Install the Gateway

When you finish this page you have an enrolled Gateway: it holds a renewable
mTLS identity issued by the Control Plane, listens for SSH, and is ready to
broker sessions to nodes.

The Gateway is the platform's **Tier-0** component — the only process that ever
sees SSH session plaintext. Treat its placement accordingly: dedicated hosts or
a dedicated namespace, minimal operator access, and the hardened profile below
switched on. The [trust model](../security/trust-model.md) explains why this
one component carries the blast radius.

Prerequisites:

- [ ] a running [Control Plane](control-plane.md), reachable from the Gateway
      host on the mTLS gRPC port
- [ ] the [Gateway](https://github.com/SessionLayer/Gateway) source checkout
- [ ] access to the Control Plane's Postgres for the one-time enrollment steps

## Pick a deployment model

| | Container (recommended) | Bare-metal / VM (systemd) |
|---|---|---|
| SSH port | high port (`:2222`), Service/LB maps `:22` to it | binds `:22` directly |
| Privilege | starts non-root (uid 65532) | starts root, **drops after bind** |
| Assets | `deploy/Dockerfile` + `deploy/kubernetes/` | `deploy/systemd/sessionlayer-gateway.service` |
| Filesystem | read-only rootfs + Landlock | `ProtectSystem=strict` + Landlock |
| Egress control | `deploy/kubernetes/networkpolicy.yaml` | host firewall |

Build the hardened image (or the bare binary):

```bash
git clone https://github.com/SessionLayer/Gateway.git
cd Gateway
docker build -f deploy/Dockerfile -t sessionlayer-gateway .
# bare-metal alternative (Rust 1.95 toolchain + protoc):
# cargo build --release -p gateway && sudo install target/release/gateway /usr/local/bin/gateway
```

## Write the config

The Gateway reads one JSON config file, from `--config <path>` or the
`SL_GATEWAY_CONFIG` environment variable. A minimal enrolling Gateway:

```json
{
  "cp_mtls_endpoint": "https://cp.example.com:9090",
  "data_dir": "/var/lib/sessionlayer-gateway",
  "bootstrap": {
    "enrollment_token": "",
    "ca_cert_path": "/etc/sessionlayer/cp-mtls-ca.pem",
    "gateway_name": "gw-1",
    "server_name": ""
  },
  "ssh": {
    "listen_addr": "0.0.0.0:2222",
    "host_key_path": "/var/lib/sessionlayer-gateway/host_key"
  }
}
```

Leave `bootstrap.enrollment_token` empty in the file and inject the real token
from the environment at first start — it is a secret. `server_name` empty means
the host part of `cp_mtls_endpoint` is used for server-certificate
verification. Every knob (PROXY protocol, source-IP allowlist, addressing,
recorder, HA, hardening) is in the
[Gateway configuration reference](../reference/config-gateway.md).

## Enroll it (one-time trust bootstrap)

A Gateway proves itself to the Control Plane once, with an operator-provisioned
single-use enrollment token; from then on it holds a CP-issued renewable mTLS
identity with a generation counter, and it is a first-class, lockable
principal. Two operator steps, both against the Control Plane's database
(gateway enrollment deliberately has no REST endpoint — it is the trust
bootstrap that everything else rests on):

**1. Export the internal mTLS CA certificate** — the trust anchor the Gateway
pins to recognize the genuine Control Plane before it has any identity:

```bash
psql "$CP_DSN" -tAc "SELECT encode(k.ca_certificate,'base64')
    FROM runtime.ca_key_material k
    JOIN config.ca_config c ON c.id = k.ca_config_id
    WHERE c.ca_kind = 'mtls'" \
  | tr -d '\r\n' \
  | { echo '-----BEGIN CERTIFICATE-----'; fold -w64; echo; echo '-----END CERTIFICATE-----'; } \
  > cp-mtls-ca.pem
```

Copy `cp-mtls-ca.pem` to the Gateway host at the `bootstrap.ca_cert_path` you
configured.

**2. Mint a single-use enrollment token** bound to the Gateway's name (only its
SHA-256 lands in the database):

```bash
GW_ENROLL_TOKEN="gw-$(head -c16 /dev/urandom | xxd -p)"
TOKEN_HASH=$(printf %s "$GW_ENROLL_TOKEN" | sha256sum | cut -d' ' -f1)
psql "$CP_DSN" -c "INSERT INTO runtime.gateway_enrollment_token
    (id, token_hash, gateway_name, single_use, expires_at, created_by)
    VALUES (gen_random_uuid(), '$TOKEN_HASH', 'gw-1', true,
            now() + interval '2 hours', 'operator')"
echo "$GW_ENROLL_TOKEN"   # deliver to the Gateway host, then forget it
```

Start the Gateway with the token in its environment-injected config. It
generates a keypair locally, sends a CSR, receives its generation-0 mTLS
identity, and persists it under `data_dir` — the private key never leaves the
Gateway. The token self-destructs on use; a replay finds nothing.

> **Note:** if a Gateway is ever compromised, you do not chase its certificate —
> [lock it](../admin-guides/locks.md). A locked Gateway is refused renewal and
> new work immediately.

## Turn on the hardened profile

The binary hardens itself at startup — privilege drop (bare-metal), a Landlock
filesystem+egress sandbox, and a seccomp syscall allow-list — and the
container/systemd assets add the OS layer on top. Neither layer trusts the
other:

```json
"hardening": {
  "run_as_user": "sessionlayer",
  "landlock": { "enabled": true,
    "read_write_paths": ["/var/lib/sessionlayer-gateway"] },
  "seccomp": { "mode": "enforce" }
}
```

Roll seccomp out as `off` → `log` (run a full session, check audit logs) →
`enforce`. A hardening step that is requested but cannot be applied **fails
startup**; the single exception is a kernel that lacks the feature entirely,
which degrades with a loud warning.

> **Warning:** the default-deny egress NetworkPolicy in
> `deploy/kubernetes/networkpolicy.yaml` is a load-bearing production control,
> not an optional extra — a Gateway that can reach anything can exfiltrate
> anything. Apply it (or its firewall equivalent) before real traffic. See the
> [hardening checklist](../security/hardening.md).

## Give it an address users can reach

Decide how users name nodes — wildcard DNS (`ssh alice@web-01.ssh.example.com`
with a `*.ssh.example.com` record pointing at the Gateway), username encoding
(`ssh 'alice%web-01'@gw.example.com`), or ProxyJump — and set the matching
config (`ssh.node_dns_suffixes`, `ssh.target_separator`, `ssh.proxy_jump`).
Details and the exact client experience are in
[SSH access](../user-guide/ssh-access.md) and
[Nodes](../admin-guides/nodes.md).

If the Gateway sits behind an L4 load balancer, enable PROXY protocol v2 and
list the LB's addresses — headers from anyone else are rejected, and a missing
header from the LB is rejected too (fail closed both ways).

## Verify

```bash
ssh -p 2222 alice@gw.example.com
```

Before any access rules exist you get a generic authentication failure — that
is the platform working (denials are deliberately uninformative). Continue with
[node enrollment](../admin-guides/nodes.md) and [RBAC](../admin-guides/rbac.md),
then connect for real.

## Next

- [Enroll nodes](../admin-guides/nodes.md)
- [RBAC](../admin-guides/rbac.md)
- [High availability](../admin-guides/high-availability.md)
- [Gateway configuration reference](../reference/config-gateway.md)
