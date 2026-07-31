# Install the Gateway

Every SSH session in SessionLayer passes through the Gateway, the Rust
process that terminates and re-originates it and the only one that ever
sees plaintext. That [Tier-0](../reference/glossary.md) role is why this
page ends with more than a running process: a renewable mTLS identity
issued by the Control Plane, listening for SSH, and ready to broker
sessions to nodes.

Treat its placement accordingly, with dedicated hosts or a dedicated
namespace, minimal operator access, and the hardened profile below switched
on. The [trust model](../security/trust-model.md) explains why this one
component carries the blast radius.

Prerequisites:

- [ ] a running [Control Plane](control-plane.md), reachable from the Gateway
      host on the mTLS gRPC port
- [ ] the [Gateway](https://github.com/SessionLayer/Gateway) source checkout
- [ ] an admin bearer token holding `gateway:enroll`, for the one-time
      enrollment steps

## Pick a deployment model

| | Container (recommended) | Bare-metal / VM (systemd) |
|---|---|---|
| SSH port | high port (`:2222`), Service/LB maps `:22` to it | binds `:22` directly |
| Privilege | starts non-root (uid 65532) | starts root, drops after bind |
| Assets | `deploy/Dockerfile` + `deploy/kubernetes/gateway.yaml` | `deploy/systemd/sessionlayer-gateway.service` |
| Filesystem | read-only rootfs + Landlock | `ProtectSystem=strict` + Landlock |
| Egress control | `deploy/kubernetes/networkpolicy.yaml` | host firewall |

`deploy/kubernetes/gateway.yaml` ships a Deployment, a ConfigMap, and a
`LoadBalancer` Service mapping port `22` to the container's `2222`. Its
readinessProbe polls the Gateway's own `GET /readyz` surface
(`ha.drain.readyz_addr`), so the Service stops routing to a pod that is
unready or draining before the pod stops listening.

Build the hardened image (or the bare binary):

```bash
git clone https://github.com/SessionLayer/Gateway.git
cd Gateway
docker build -f deploy/Dockerfile -t sessionlayer-gateway .
# bare-metal alternative (Rust 1.95 toolchain + protoc):
# cargo build --release -p gateway && sudo install target/release/gateway /usr/local/bin/gateway
```

> **Note:** building from a clone means you run whatever the checkout contains.
> For anything beyond evaluation, build from a reviewed, pinned commit or tag,
> not a moving branch. [Supply chain](../security/supply-chain.md) covers
> verifying released artifacts.

## Write the config

The Gateway reads one JSON config file, from `--config <path>` or the
`SL_GATEWAY_CONFIG` environment variable. There is no built-in default path:
started with neither, the Gateway runs on compiled-in defaults, which listen
for nothing and point at `127.0.0.1`. Write the file to
`/etc/sessionlayer/gateway.json`, the path the container image, the systemd
unit and the Kubernetes manifest all pass. A minimal enrolling Gateway:

```json
{
  "cp_mtls_endpoint": "https://cp.example.com:9443",
  "data_dir": "/var/lib/sessionlayer-gateway",
  "bootstrap": {
    "enrollment_token": "",
    "ca_cert_path": "/etc/sessionlayer/cp-mtls-ca.pem",
    "gateway_name": "gw-1",
    "server_name": ""
  },
  "ssh": {
    "listen_addr": "0.0.0.0:2222",
    "host_key_path": "/var/lib/sessionlayer-gateway/host_key",
    "agent": {
      "listen_addr": "0.0.0.0:9444",
      "advertise_url": "wss://gw.example.com:9444"
    }
  }
}
```

Leave `bootstrap.enrollment_token` empty in the file and fill it in with the
real token, from your secrets manager or a templated config, right before
first start. It is a secret and the Gateway itself has no environment-variable
override for it. `server_name` empty means the host part of
`cp_mtls_endpoint` is used for server-certificate verification.

`ssh.agent.listen_addr` is the agent transport, and it is off unless you set
it. That is the port Agents dial and the port peer Gateways use for the byte
relay in HA, so a Gateway without it can serve agentless nodes only. Leave it
out if every node in reach is agentless; the next guide,
[Enroll nodes](../admin-guides/nodes.md), needs it. Set `advertise_url` to the
`wss://` URL Agents should dial back to: a wildcard `listen_addr` without it
is a startup error, since the Gateway hands that URL to Agents and `0.0.0.0`
is not something they can dial.

Every remaining knob (PROXY protocol, source-IP allowlist, addressing,
recorder, HA, hardening) is in the
[Gateway configuration reference](../reference/config-gateway.md).

## Enroll it (one-time trust bootstrap)

A Gateway proves itself to the Control Plane once, with an operator-provisioned
single-use enrollment token (the Gateway's equivalent of an Agent's join
token). From then on it holds a CP-issued renewable mTLS identity with a
generation counter, and it is a first-class, lockable principal. Two API calls,
both needing the `gateway:enroll` platform permission and nothing else. `$TOKEN`
is your admin bearer token.

`gateway:enroll` is its own permission rather than a reuse of `node:enroll`: a
Gateway is the only component that sees session plaintext, so admitting one is
a heavier authority than enrolling a node. Grant it deliberately, and see
[RBAC](../admin-guides/rbac.md) for how to put it in a role.

### 1. Export the internal mTLS CA certificate

This is the trust anchor the Gateway pins to recognize the genuine Control
Plane before it has any identity. It is public material: the CA certificate
only, never key material.

```bash
curl -s https://cp.example.com/v1/cas/mtls/trust-anchor \
  -H "Authorization: Bearer $TOKEN" \
  | jq -r .pem > cp-mtls-ca.pem
```

The response also carries `fingerprintSha256`. Check it against the copy you
land on the Gateway host, so a substituted anchor is caught before it is
trusted:

```bash
openssl x509 -in cp-mtls-ca.pem -outform der | sha256sum
```

Copy `cp-mtls-ca.pem` to the Gateway host at the `bootstrap.ca_cert_path` you
configured.

### 2. Mint a single-use enrollment token

The token is bound to the Gateway's name; only its SHA-256 lands in the
database:

```bash
curl -s https://cp.example.com/v1/gateway-enrollment-tokens \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{ "gatewayName": "gw-1", "ttlSeconds": 7200 }'
```

The response contains the raw token exactly once. Copy it now for out-of-band
delivery to the Gateway host. `GET /v1/gateway-enrollment-tokens` lists active
tokens as metadata only and never returns the value again, and
`DELETE /v1/gateway-enrollment-tokens/{id}` revokes an unused one.

### 3. Start it

Fill the real token into the config on the Gateway host, then start it:

```bash
# container: the image's default command is --config /etc/sessionlayer/gateway.json
docker run -d --name sessionlayer-gateway \
  -v /etc/sessionlayer:/etc/sessionlayer:ro \
  -v sessionlayer-gateway-data:/var/lib/sessionlayer-gateway \
  -p 2222:2222 -p 9444:9444 \
  sessionlayer-gateway

# bare-metal / systemd
sudo cp deploy/systemd/sessionlayer-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sessionlayer-gateway
```

The Gateway generates a keypair locally, sends a CSR, receives its
generation-0 mTLS identity, and persists it under `data_dir`. The private key
never leaves the Gateway. The token self-destructs on use, so a replay finds
nothing.

> **Note:** if a Gateway is ever compromised, you do not chase its
> certificate. [Lock it](../admin-guides/locks.md) instead. A locked Gateway
> is refused renewal and new work immediately.

## Turn on the hardened profile

The binary hardens itself at startup: privilege drop (bare-metal), a Landlock
filesystem and egress sandbox, and a seccomp syscall allow-list. The
container/systemd assets add the OS layer on top. Neither layer trusts the
other:

```json
"hardening": {
  "run_as_user": "sessionlayer",
  "landlock": {
    "enabled": true,
    "read_only_paths": ["/etc/sessionlayer", "/etc/ssl/certs", "/etc/resolv.conf",
                        "/etc/hosts", "/etc/nsswitch.conf", "/lib", "/lib64",
                        "/usr/lib", "/dev", "/proc"],
    "read_write_paths": ["/var/lib/sessionlayer-gateway"]
  },
  "seccomp": { "mode": "enforce" }
}
```

`read_only_paths` has no default, and Landlock denies whatever no rule
allows. An empty list therefore confines the Gateway to `data_dir` alone,
which costs it its own config file, the mTLS trust anchor, the system CA
bundle and DNS resolution. Start from the list above and add what your host
needs.

> **Note:** if recording is on, keep `ssh.recorder.spool_dir` inside
> `data_dir` (the daemon defaults it there). A spool path outside the Landlock
> read-write set, such as `/tmp`, is denied and tears the session down
> mid-stream.

Roll seccomp out as `off` → `log` (run a full session, check audit logs) →
`enforce`. A hardening step that is requested but cannot be applied fails
startup: `run_as_user` set on a process that is not root, an unknown user, or
a Landlock/seccomp rule the kernel supports but rejects. The single exception
is a kernel that lacks Landlock or seccomp entirely, which degrades with a
loud warning instead of refusing to start; lean on the container's read-only
rootfs and dropped capabilities on such a host. (`seccomp: enforce` on a
kernel with no seccomp support at all is the one case that still surfaces as
a startup error, since even probing for it takes a syscall.)

`landlock.required` is how you refuse that degrade. With it set, the Gateway
aborts unless Landlock enforces in full, so a host with no Landlock, or an
older kernel that can only enforce part of the ruleset, never carries
sessions. It is the Gateway's counterpart to the Agent's
`--require-full-landlock`, and on the component that sees session plaintext it
is worth setting once you have confirmed the fleet's kernels support it.

> **Warning:** the default-deny egress NetworkPolicy in
> `deploy/kubernetes/networkpolicy.yaml` is a load-bearing production
> control, not an optional extra. It scopes egress to cluster DNS, the
> Control Plane's mTLS gRPC port, the node subnet, and the WORM object store,
> and ingress to the SSH, agent-transport, and readiness ports only. A
> Gateway that can reach anything can exfiltrate anything: apply it, or its
> firewall equivalent, before real traffic. See the
> [hardening checklist](../security/hardening.md).

## Give it an address users can reach

Decide how users name nodes: wildcard DNS (`ssh deploy@web-01.ssh.example.com`
with a `*.ssh.example.com` record pointing at the Gateway), username encoding
(`ssh 'deploy%web-01'@gw.example.com`), or ProxyJump, and set the matching
config (`ssh.node_dns_suffixes`, `ssh.target_separator`, `ssh.proxy_jump`).
Details and the exact client experience are in
[SSH access](../user-guide/ssh-access.md) and
[Nodes](../admin-guides/nodes.md).

If the Gateway sits behind an L4 load balancer, enable PROXY protocol v2 and
list the LB's addresses. Headers from anyone else are rejected, and a missing
header from the LB is rejected too: fail closed both ways.

## Verify

```bash
ssh -p 2222 'deploy%web-01'@gw.example.com
# expect: a generic authentication failure. No access rules exist yet, so
# every credential is refused (denials are deliberately uninformative).
```

That is the platform working, not a misconfiguration. Continue with
[node enrollment](../admin-guides/nodes.md) and [RBAC](../admin-guides/rbac.md),
then connect for real.

## Next

- [Enroll nodes](../admin-guides/nodes.md)
- [RBAC](../admin-guides/rbac.md)
- [High availability](../admin-guides/high-availability.md)
- [Gateway configuration reference](../reference/config-gateway.md)
